/**
 * Contract: Discount codes from `commerce.json`. One code per cart, matched
 * in any case, applied to cart cost and discount allocations, recorded on
 * orders by `checkoutComplete`, and shown in the StateSnapshot. Each test
 * uses its own episode so carts and orders do not leak between tests.
 */

import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { type ContractServer, FIXTURE_DIR, startContractServer } from './helpers.js';

// $19.99 each; no inventory entry, so any quantity is in stock.
const UNTRACKED_VARIANT = 'gid://shopify/ProductVariant/47242720215214';

let ctx: ContractServer;

beforeAll(async () => {
  ctx = await startContractServer();
});

afterAll(async () => {
  await ctx.server.close();
});

const CART_FIELDS = /* GraphQL */ `
  cart {
    id
    cost {
      subtotalAmount { amount }
      totalAmount { amount }
    }
    discountCodes { code applicable }
    discountAllocations {
      discountedAmount { amount currencyCode }
      targetType
      ... on CartCodeDiscountAllocation { code }
    }
  }
  userErrors { code field message }
`;

interface CartShape {
  readonly id: string;
  readonly cost: {
    readonly subtotalAmount: { readonly amount: string };
    readonly totalAmount: { readonly amount: string };
  };
  readonly discountCodes: readonly { readonly code: string; readonly applicable: boolean }[];
  readonly discountAllocations: readonly {
    readonly discountedAmount: { readonly amount: string; readonly currencyCode: string };
    readonly targetType: string;
    readonly code: string;
  }[];
}

interface Payload {
  readonly cart: CartShape | null;
  readonly userErrors: readonly { code: string; field: readonly string[]; message: string }[];
}

async function createCart(episode: string, quantity: number): Promise<CartShape> {
  const result = await ctx.query<{ cartCreate: Payload }>(
    /* GraphQL */ `mutation {
      cartCreate(input: { lines: [{ merchandiseId: "${UNTRACKED_VARIANT}", quantity: ${quantity} }] }) {
        ${CART_FIELDS}
      }
    }`,
    episode,
  );
  const cart = result.data?.cartCreate.cart;
  if (cart === undefined || cart === null) throw new Error('expected a cart');
  return cart;
}

async function applyCodes(episode: string, cartId: string, codes: string): Promise<Payload> {
  const result = await ctx.query<{ cartDiscountCodesUpdate: Payload }>(
    /* GraphQL */ `mutation {
      cartDiscountCodesUpdate(cartId: "${cartId}", discountCodes: ${codes}) { ${CART_FIELDS} }
    }`,
    episode,
  );
  if (result.data === undefined || result.errors !== undefined) {
    throw new Error(JSON.stringify(result.errors));
  }
  return result.data.cartDiscountCodesUpdate;
}

async function firstLineId(episode: string, cartId: string): Promise<string> {
  const result = await ctx.query<{
    cart: { lines: { nodes: readonly { id: string }[] } } | null;
  }>(`{ cart(id: "${cartId}") { lines(first: 1) { nodes { ... on CartLine { id } } } } }`, episode);
  const id = result.data?.cart?.lines.nodes[0]?.id;
  if (id === undefined) throw new Error('expected a cart line');
  return id;
}

async function setQuantity(
  episode: string,
  cartId: string,
  lineId: string,
  quantity: number,
): Promise<CartShape | null | undefined> {
  const result = await ctx.query<{ cartLinesUpdate: Payload }>(
    /* GraphQL */ `mutation {
      cartLinesUpdate(cartId: "${cartId}", lines: [{ id: "${lineId}", quantity: ${quantity} }]) {
        ${CART_FIELDS}
      }
    }`,
    episode,
  );
  return result.data?.cartLinesUpdate.cart;
}

describe('cartDiscountCodesUpdate', () => {
  it('applies a percent code typed in any case to the cart cost', async () => {
    const cart = await createCart('discount-percent', 1);

    const payload = await applyCodes('discount-percent', cart.id, '["welcome10"]');

    expect(payload.userErrors).toEqual([]);
    expect(payload.cart?.discountCodes).toEqual([{ code: 'WELCOME10', applicable: true }]);
    // 10% of 19.99 is 1.999, rounded to 2.00.
    expect(payload.cart?.discountAllocations).toEqual([
      {
        code: 'WELCOME10',
        targetType: 'LINE_ITEM',
        discountedAmount: { amount: '2.00', currencyCode: 'CAD' },
      },
    ]);
    expect(payload.cart?.cost.subtotalAmount.amount).toBe('19.99');
    expect(payload.cart?.cost.totalAmount.amount).toBe('17.99');
  });

  it('keeps a below-minimum code but applies it only while the subtotal reaches the minimum', async () => {
    const episode = 'discount-minimum';
    const cart = await createCart(episode, 1);

    // SAVE5 needs a 30.00 subtotal; 19.99 is below it.
    const below = await applyCodes(episode, cart.id, '["SAVE5"]');
    expect(below.cart?.discountCodes).toEqual([{ code: 'SAVE5', applicable: false }]);
    expect(below.cart?.discountAllocations).toEqual([]);
    expect(below.cart?.cost.totalAmount.amount).toBe('19.99');

    const lineId = await firstLineId(episode, cart.id);
    const above = await setQuantity(episode, cart.id, lineId, 2);
    expect(above?.discountCodes).toEqual([{ code: 'SAVE5', applicable: true }]);
    expect(above?.cost.subtotalAmount.amount).toBe('39.98');
    expect(above?.cost.totalAmount.amount).toBe('34.98');

    const dropped = await setQuantity(episode, cart.id, lineId, 1);
    expect(dropped?.discountCodes).toEqual([{ code: 'SAVE5', applicable: false }]);
    expect(dropped?.cost.totalAmount.amount).toBe('19.99');
  });

  it('reports an unknown code as not applicable and leaves the price unchanged', async () => {
    const cart = await createCart('discount-unknown', 1);

    const payload = await applyCodes('discount-unknown', cart.id, '["  NOPE "]');

    expect(payload.userErrors).toEqual([]);
    expect(payload.cart?.discountCodes).toEqual([{ code: 'NOPE', applicable: false }]);
    expect(payload.cart?.discountAllocations).toEqual([]);
    expect(payload.cart?.cost.totalAmount.amount).toBe('19.99');
  });

  it('holds one code: a new code replaces the old one and two codes are rejected', async () => {
    const episode = 'discount-one-code';
    const cart = await createCart(episode, 1);
    await applyCodes(episode, cart.id, '["WELCOME10"]');

    const replaced = await applyCodes(episode, cart.id, '["FREESHIP"]');
    expect(replaced.cart?.discountCodes).toEqual([{ code: 'FREESHIP', applicable: true }]);
    // A cart has no shipping charge yet, so free shipping allocates 0.00 to it.
    expect(replaced.cart?.discountAllocations).toEqual([
      {
        code: 'FREESHIP',
        targetType: 'SHIPPING_LINE',
        discountedAmount: { amount: '0.00', currencyCode: 'CAD' },
      },
    ]);
    expect(replaced.cart?.cost.totalAmount.amount).toBe('19.99');

    const rejected = await applyCodes(episode, cart.id, '["WELCOME10", "SAVE5"]');
    expect(rejected.userErrors).toEqual([
      {
        code: 'INVALID',
        field: ['discountCodes'],
        message: 'A cart can hold only one discount code',
      },
    ]);
    expect(rejected.cart?.discountCodes).toEqual([{ code: 'FREESHIP', applicable: true }]);

    const cleared = await applyCodes(episode, cart.id, '[]');
    expect(cleared.cart?.discountCodes).toEqual([]);
  });
});

const ADDRESS = /* GraphQL */ `{
  firstName: "Sam", lastName: "Buyer", address1: "1 Main St", city: "Toronto",
  province: "Ontario", country: "Canada", zip: "M5V 1A1"
}`;

interface OrderShape {
  readonly name: string;
  readonly subtotalPrice: { readonly amount: string };
  readonly totalShippingPrice: { readonly amount: string };
  readonly totalPrice: { readonly amount: string };
  readonly discountCode: {
    readonly code: string;
    readonly targetType: string;
    readonly amount: { readonly amount: string };
  } | null;
}

async function checkout(episode: string, cartId: string): Promise<OrderShape> {
  const result = await ctx.query<{ checkoutComplete: { order: OrderShape | null } }>(
    /* GraphQL */ `mutation {
      checkoutComplete(cartId: "${cartId}", input: {
        email: "sam@example.com", shippingAddress: ${ADDRESS}, shippingMethodHandle: "standard"
      }) {
        order {
          name
          subtotalPrice { amount }
          totalShippingPrice { amount }
          totalPrice { amount }
          discountCode { code targetType amount { amount } }
        }
        userErrors { code field message }
      }
    }`,
    episode,
  );
  const order = result.data?.checkoutComplete.order;
  if (order === undefined || order === null) throw new Error(JSON.stringify(result));
  return order;
}

describe('checkoutComplete with a Discount code', () => {
  it('reports no discount on a seeded order without a code', async () => {
    const snapshot = await ctx.snapshot('discount-seeded');

    expect(snapshot.orders.find((o) => o.name === '#1001')).toMatchObject({
      discountCode: null,
      discountAmount: '0.00',
    });
  });

  it('records a percent code and its amount on the order and in the StateSnapshot', async () => {
    const episode = 'discount-checkout-percent';
    const cart = await createCart(episode, 2);
    await applyCodes(episode, cart.id, '["Welcome10"]');

    const before = await ctx.snapshot(episode);
    expect(before.carts.find((c) => c.id === cart.id)).toMatchObject({
      discountCodes: ['WELCOME10'],
      appliedDiscountCode: 'WELCOME10',
    });

    const order = await checkout(episode, cart.id);

    // 39.98 - 4.00 (10%) + 9.99 shipping, below the 75.00 free-shipping threshold.
    expect(order).toEqual({
      name: order.name,
      subtotalPrice: { amount: '39.98' },
      totalShippingPrice: { amount: '9.99' },
      totalPrice: { amount: '45.97' },
      discountCode: { code: 'WELCOME10', targetType: 'LINE_ITEM', amount: { amount: '4.00' } },
    });
    const after = await ctx.snapshot(episode);
    expect(after.orders.find((o) => o.name === order.name)).toMatchObject({
      discountCode: 'WELCOME10',
      discountAmount: '4.00',
      totalPrice: '45.97',
    });
  });

  it('records the waived shipping charge as the amount of a free-shipping code', async () => {
    const episode = 'discount-checkout-freeship';
    const cart = await createCart(episode, 1);
    await applyCodes(episode, cart.id, '["freeship"]');

    const order = await checkout(episode, cart.id);

    expect(order.totalShippingPrice.amount).toBe('0.00');
    expect(order.totalPrice.amount).toBe('19.99');
    expect(order.discountCode).toEqual({
      code: 'FREESHIP',
      targetType: 'SHIPPING_LINE',
      amount: { amount: '9.99' },
    });
  });

  it('places an order without a discount when the code does not apply', async () => {
    const episode = 'discount-checkout-inapplicable';
    const cart = await createCart(episode, 1);
    await applyCodes(episode, cart.id, '["SAVE5"]');

    const before = await ctx.snapshot(episode);
    expect(before.carts.find((c) => c.id === cart.id)).toMatchObject({
      discountCodes: ['SAVE5'],
      appliedDiscountCode: null,
    });

    const order = await checkout(episode, cart.id);

    expect(order.totalPrice.amount).toBe('29.98');
    expect(order.discountCode).toBeNull();
    const after = await ctx.snapshot(episode);
    expect(after.orders.find((o) => o.name === order.name)).toMatchObject({
      discountCode: null,
      discountAmount: '0.00',
    });
  });
});

describe('a seeded order with a Discount code', () => {
  let seeded: ContractServer;
  let dataDir: string;

  beforeAll(async () => {
    // The fixture order #1001 bought one 19.99 item; here it used WELCOME10.
    dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'discount-seeded-'));
    fs.cpSync(FIXTURE_DIR, dataDir, { recursive: true });
    const ordersPath = path.join(dataDir, 'orders.json');
    const orders = JSON.parse(fs.readFileSync(ordersPath, 'utf8')) as Record<string, unknown>[];
    const [order] = orders;
    if (order === undefined) throw new Error('fixture has no orders');
    Object.assign(order, {
      discount_code: 'WELCOME10',
      discount_amount: '2.00',
      total_price: '27.98',
    });
    fs.writeFileSync(ordersPath, JSON.stringify(orders));
    seeded = await startContractServer(dataDir);
  });

  afterAll(async () => {
    await seeded.server.close();
    fs.rmSync(dataDir, { recursive: true, force: true });
  });

  it('shows the code and amount on the order and in the StateSnapshot', async () => {
    const episode = 'discount-seeded-code';
    const login = await seeded.query<{
      customerAccessTokenCreate: { customerAccessToken: { accessToken: string } | null };
    }>(
      /* GraphQL */ `mutation {
        customerAccessTokenCreate(input: { email: "jane.doe@example.com", password: "password123" }) {
          customerAccessToken { accessToken }
        }
      }`,
      episode,
    );
    const token = login.data?.customerAccessTokenCreate.customerAccessToken?.accessToken;
    if (token === undefined) throw new Error(JSON.stringify(login));

    const result = await seeded.query<{
      customer: { orders: { nodes: readonly Pick<OrderShape, 'name' | 'discountCode'>[] } };
    }>(
      `{ customer(customerAccessToken: "${token}") {
        orders(first: 5) { nodes { name discountCode { code targetType amount { amount } } } }
      } }`,
      episode,
    );

    expect(result.data?.customer.orders.nodes).toEqual([
      {
        name: '#1001',
        discountCode: { code: 'WELCOME10', targetType: 'LINE_ITEM', amount: { amount: '2.00' } },
      },
    ]);
    const snapshot = await seeded.snapshot(episode);
    expect(snapshot.orders.find((o) => o.name === '#1001')).toMatchObject({
      discountCode: 'WELCOME10',
      discountAmount: '2.00',
      totalPrice: '27.98',
    });
  });
});
