/**
 * Checkout + order domain tests: `commerceSettings`, the `checkoutComplete`
 * cart -> order transition with its validation paths, and `Query.order`.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { beforeEach, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { createSandboxSchema } from '../schema/index.js';
import { ShopState } from '../state/shop_state.js';
import type { ResolverContext } from './index.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);
const BASE_URL = 'http://sandbox.test';

const AISLEARENA_VARIANT = 'gid://shopify/ProductVariant/47642512195758'; // $79.99
const SHOPLISEUM_VARIANT = 'gid://shopify/ProductVariant/47242666836142'; // $19.99, qty 2

const data = loadShopData(FIXTURE_DIR);
const schema = createSandboxSchema();

interface ExecutionResult {
  readonly data?: unknown;
  readonly errors?: readonly unknown[];
}

function runWith(state: ShopState) {
  const yoga = createYoga({
    schema,
    context: (): ResolverContext => ({
      data: state.data,
      state,
      carts: state.carts,
      baseUrl: BASE_URL,
    }),
  });
  return async (source: string): Promise<ExecutionResult> => {
    const response = await yoga.fetch(`${BASE_URL}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: source }),
    });
    return (await response.json()) as ExecutionResult;
  };
}

const ADDRESS = /* GraphQL */ `{
  firstName: "Sam", lastName: "Buyer", address1: "1 Main St", city: "Toronto",
  province: "Ontario", country: "Canada", zip: "M5V 1A1"
}`;

const ORDER_FIELDS = /* GraphQL */ `
  id name orderNumber email financialStatus fulfillmentStatus processedAt
  subtotalPrice { amount } totalShippingPrice { amount } totalTax { amount } totalPrice { amount currencyCode }
  shippingMethod paymentMethod
  shippingAddress { formatted countryCodeV2 }
  lineItems(first: 10) { nodes { title quantity variant { id } } }
`;

function complete(cartId: string, input: string): string {
  return /* GraphQL */ `
    mutation {
      checkoutComplete(cartId: "${cartId}", input: ${input}) {
        order { ${ORDER_FIELDS} }
        userErrors { code field message }
      }
    }
  `;
}

interface CompletePayload {
  readonly checkoutComplete: {
    readonly order: Record<string, unknown> | null;
    readonly userErrors: readonly {
      code: string;
      field: readonly string[] | null;
      message: string;
    }[];
  };
}

let state: ShopState;
let run: ReturnType<typeof runWith>;

beforeEach(() => {
  state = new ShopState(data, 'test');
  run = runWith(state);
});

describe('Query.commerceSettings', () => {
  it('exposes the commerce.json rules in store currency', async () => {
    const result = await run(/* GraphQL */ `
      {
        commerceSettings {
          currencyCode taxRate
          freeShippingThreshold { amount currencyCode }
          shippingMethods { handle title price { amount } }
          paymentMethods { handle title }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      commerceSettings: {
        currencyCode: 'CAD',
        taxRate: 0,
        freeShippingThreshold: { amount: '75.00', currencyCode: 'CAD' },
        shippingMethods: [
          { handle: 'standard', title: 'Standard Shipping (5-7 days)', price: { amount: '9.99' } },
          { handle: 'express', title: 'Express Shipping (1-2 days)', price: { amount: '19.99' } },
        ],
        paymentMethods: [
          { handle: 'card', title: 'Credit card' },
          { handle: 'paypal', title: 'PayPal' },
        ],
      },
    });
  });
});

describe('checkoutComplete', () => {
  it('turns a guest cart into an order, drops the cart, and decrements stock', async () => {
    const cart = state.carts.create({
      lines: [{ merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 }],
    });
    const result = await run(
      complete(
        cart.id,
        `{ email: "sam@example.com", shippingAddress: ${ADDRESS}, shippingMethodHandle: "express" }`,
      ),
    );
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      checkoutComplete: {
        order: {
          id: 'gid://shopify/Order/1007',
          name: '#1007',
          orderNumber: 1007,
          email: 'sam@example.com',
          financialStatus: 'PAID',
          fulfillmentStatus: 'UNFULFILLED',
          processedAt: '2026-01-01T00:00:01.000Z',
          subtotalPrice: { amount: '19.99' },
          totalShippingPrice: { amount: '19.99' },
          totalTax: { amount: '0.00' },
          totalPrice: { amount: '39.98', currencyCode: 'CAD' },
          shippingMethod: 'express',
          paymentMethod: 'card',
          shippingAddress: {
            formatted: ['Sam Buyer', '1 Main St', 'Toronto Ontario M5V 1A1', 'Canada'],
            countryCodeV2: 'CA',
          },
          lineItems: {
            nodes: [
              {
                title: 'Shopliseum Mushroom Dog Toys - Red Mushroom',
                quantity: 1,
                variant: { id: SHOPLISEUM_VARIANT },
              },
            ],
          },
        },
        userErrors: [],
      },
    });

    const after = await run(/* GraphQL */ `
      {
        cart(id: "${cart.id}") { id }
        product(handle: "shopliseum-mushroom-dog-toys") {
          variants(first: 1) { nodes { id quantityAvailable } }
        }
        order(id: "gid://shopify/Order/1007") { name }
      }
    `);
    expect(after.data).toEqual({
      cart: null,
      product: { variants: { nodes: [{ id: SHOPLISEUM_VARIANT, quantityAvailable: 1 }] } },
      order: { name: '#1007' },
    });
  });

  it('defaults shipping and payment to the first configured methods and waives shipping above the threshold', async () => {
    const cart = state.carts.create({
      lines: [{ merchandiseId: AISLEARENA_VARIANT, quantity: 1 }],
      buyerIdentity: { email: 'from-cart@example.com' },
    });
    const result = await run(complete(cart.id, `{ shippingAddress: ${ADDRESS} }`));
    const payload = result.data as CompletePayload;
    expect(payload.checkoutComplete.userErrors).toEqual([]);
    expect(payload.checkoutComplete.order).toMatchObject({
      email: 'from-cart@example.com',
      shippingMethod: 'standard',
      paymentMethod: 'card',
      totalShippingPrice: { amount: '0.00' },
      totalPrice: { amount: '79.99', currencyCode: 'CAD' },
    });
  });

  it('attributes the order to the cart customer and lists it under customer.orders', async () => {
    const session = state.createSession(1);
    const cart = state.carts.create({
      lines: [{ merchandiseId: AISLEARENA_VARIANT, quantity: 1 }],
    });
    await run(/* GraphQL */ `
      mutation {
        cartBuyerIdentityUpdate(cartId: "${cart.id}", buyerIdentity: { customerAccessToken: "${session.accessToken}" }) {
          userErrors { code }
        }
      }
    `);
    const result = await run(complete(cart.id, `{ shippingAddress: ${ADDRESS} }`));
    const payload = result.data as CompletePayload;
    expect(payload.checkoutComplete.order).toMatchObject({ email: 'jane.doe@example.com' });

    const history = await run(/* GraphQL */ `
      {
        customer(customerAccessToken: "${session.accessToken}") {
          numberOfOrders
          orders(first: 5, sortKey: PROCESSED_AT, reverse: true) { totalCount nodes { name } }
        }
      }
    `);
    expect(history.data).toEqual({
      customer: {
        numberOfOrders: 2,
        orders: { totalCount: 2, nodes: [{ name: '#1007' }, { name: '#1001' }] },
      },
    });
  });

  it('reports INSUFFICIENT_STOCK and keeps the cart', async () => {
    const cart = state.carts.create({
      lines: [{ merchandiseId: SHOPLISEUM_VARIANT, quantity: 3 }],
    });
    const result = await run(
      complete(cart.id, `{ email: "sam@example.com", shippingAddress: ${ADDRESS} }`),
    );
    expect(result.data).toEqual({
      checkoutComplete: {
        order: null,
        userErrors: [
          {
            code: 'INSUFFICIENT_STOCK',
            field: ['cartId'],
            message: `Only 2 of 3 available for ${SHOPLISEUM_VARIANT}`,
          },
        ],
      },
    });
    expect(state.carts.get(cart.id)).toBeDefined();
    expect(state.listOrders()).toHaveLength(6);
  });

  it.each([
    [
      'unknown cart',
      'gid://shopify/Cart/nope',
      `{ email: "s@example.com", shippingAddress: ${ADDRESS} }`,
      'INVALID',
      ['cartId'],
    ],
    [
      'unknown shipping method',
      null,
      `{ email: "s@example.com", shippingAddress: ${ADDRESS}, shippingMethodHandle: "drone" }`,
      'INVALID',
      ['input', 'shippingMethodHandle'],
    ],
    [
      'unknown payment method',
      null,
      `{ email: "s@example.com", shippingAddress: ${ADDRESS}, paymentMethodHandle: "iou" }`,
      'INVALID',
      ['input', 'paymentMethodHandle'],
    ],
    [
      'missing zip',
      null,
      `{ email: "s@example.com", shippingAddress: { address1: "1 Main St", city: "Toronto", country: "Canada" } }`,
      'BLANK',
      ['input', 'shippingAddress', 'zip'],
    ],
    ['no email anywhere', null, `{ shippingAddress: ${ADDRESS} }`, 'BLANK', ['input', 'email']],
  ])('rejects %s with a user error', async (_label, cartId, input, code, field) => {
    const cart = state.carts.create({
      lines: [{ merchandiseId: AISLEARENA_VARIANT, quantity: 1 }],
    });
    const result = await run(complete(cartId ?? cart.id, input));
    expect(result.errors).toBeUndefined();
    const payload = result.data as CompletePayload;
    expect(payload.checkoutComplete.order).toBeNull();
    expect(payload.checkoutComplete.userErrors).toEqual([expect.objectContaining({ code, field })]);
    expect(state.listOrders()).toHaveLength(6);
  });

  it('rejects an empty cart', async () => {
    const cart = state.carts.create({});
    const result = await run(
      complete(cart.id, `{ email: "s@example.com", shippingAddress: ${ADDRESS} }`),
    );
    const payload = result.data as CompletePayload;
    expect(payload.checkoutComplete.userErrors).toEqual([
      expect.objectContaining({ code: 'EMPTY' }),
    ]);
  });
});

describe('Query.order', () => {
  it('resolves seeded orders by GID and null for unknown or malformed ids', async () => {
    const result = await run(/* GraphQL */ `
      {
        seeded: order(id: "gid://shopify/Order/1001") { name email shippingAddress { formatted } }
        missing: order(id: "gid://shopify/Order/4242") { name }
        malformed: order(id: "1001") { name }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      seeded: {
        name: '#1001',
        email: 'jane.doe@example.com',
        shippingAddress: {
          formatted: ['Jane Doe', '123 Bank Street', 'Apt 4', 'Ottawa ON K2P 1X3', 'Canada'],
        },
      },
      missing: null,
      malformed: null,
    });
  });
});
