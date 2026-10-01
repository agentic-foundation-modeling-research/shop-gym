/**
 * Contract: the pre-v1.1 cart surface (create / add / update / remove /
 * query) and its cost shape. Uses no customer, checkout, or episode features.
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { type ContractServer, startContractServer } from './helpers.js';

const AISLEARENA_VARIANT = 'gid://shopify/ProductVariant/47642512195758'; // $79.99
const SHOPLISEUM_VARIANT = 'gid://shopify/ProductVariant/47242666836142'; // $19.99

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
    totalQuantity
    checkoutUrl
    cost {
      subtotalAmount { amount currencyCode }
      totalAmount { amount currencyCode }
      totalTaxAmount { amount }
    }
    buyerIdentity { email countryCode }
    lines(first: 10) {
      nodes { ... on CartLine { id quantity merchandise { ... on ProductVariant { id } } } }
    }
  }
  userErrors { code field message }
`;

interface CartShape {
  readonly id: string;
  readonly totalQuantity: number;
  readonly checkoutUrl: string;
  readonly cost: {
    readonly subtotalAmount: { readonly amount: string; readonly currencyCode: string };
    readonly totalAmount: { readonly amount: string; readonly currencyCode: string };
    readonly totalTaxAmount: { readonly amount: string } | null;
  };
  readonly buyerIdentity: { readonly email: string | null; readonly countryCode: string | null };
  readonly lines: {
    readonly nodes: readonly {
      readonly id: string;
      readonly quantity: number;
      readonly merchandise: { readonly id: string };
    }[];
  };
}
interface Payload {
  readonly cart: CartShape | null;
  readonly userErrors: readonly {
    readonly code: string | null;
    readonly field: readonly string[] | null;
    readonly message: string;
  }[];
}

describe('contract: cart lifecycle', () => {
  it('create -> add -> update -> remove -> query keeps ids, totals, and cost shape stable', async () => {
    const create = await ctx.query<{ cartCreate: Payload }>(/* GraphQL */ `
      mutation {
        cartCreate(input: { lines: [{ merchandiseId: "${AISLEARENA_VARIANT}", quantity: 1 }], buyerIdentity: { email: "buyer@example.com" } }) {
          ${CART_FIELDS}
        }
      }
    `);
    expect(create.errors).toBeUndefined();
    const created = create.data?.cartCreate.cart;
    if (!created) throw new Error('expected cart');
    expect(created.id).toMatch(/^gid:\/\/shopify\/Cart\//);
    expect(created.checkoutUrl).toBe('#');
    expect(created.totalQuantity).toBe(1);
    expect(created.cost).toEqual({
      subtotalAmount: { amount: '79.99', currencyCode: 'CAD' },
      totalAmount: { amount: '79.99', currencyCode: 'CAD' },
      totalTaxAmount: null,
    });
    expect(created.buyerIdentity).toEqual({ email: 'buyer@example.com', countryCode: null });
    const firstLineId = created.lines.nodes[0]?.id;
    if (firstLineId === undefined) throw new Error('expected a line');

    const add = await ctx.query<{ cartLinesAdd: Payload }>(/* GraphQL */ `
      mutation {
        cartLinesAdd(cartId: "${created.id}", lines: [
          { merchandiseId: "${AISLEARENA_VARIANT}", quantity: 1 }
          { merchandiseId: "${SHOPLISEUM_VARIANT}", quantity: 2 }
        ]) { ${CART_FIELDS} }
      }
    `);
    const added = add.data?.cartLinesAdd.cart;
    if (!added) throw new Error('expected cart');
    expect(added.totalQuantity).toBe(4);
    expect(added.lines.nodes.map((l) => [l.id === firstLineId, l.quantity])).toEqual([
      [true, 2],
      [false, 2],
    ]);
    expect(added.cost.subtotalAmount.amount).toBe('199.96');
    const secondLineId = added.lines.nodes[1]?.id;
    if (secondLineId === undefined) throw new Error('expected a second line');

    const update = await ctx.query<{ cartLinesUpdate: Payload }>(/* GraphQL */ `
      mutation {
        cartLinesUpdate(cartId: "${created.id}", lines: [{ id: "${secondLineId}", quantity: 1 }]) { ${CART_FIELDS} }
      }
    `);
    expect(update.data?.cartLinesUpdate.cart?.totalQuantity).toBe(3);
    expect(update.data?.cartLinesUpdate.cart?.cost.subtotalAmount.amount).toBe('179.97');

    const remove = await ctx.query<{ cartLinesRemove: Payload }>(/* GraphQL */ `
      mutation {
        cartLinesRemove(cartId: "${created.id}", lineIds: ["${firstLineId}"]) { ${CART_FIELDS} }
      }
    `);
    expect(remove.data?.cartLinesRemove.cart?.lines.nodes).toEqual([
      { id: secondLineId, quantity: 1, merchandise: { id: SHOPLISEUM_VARIANT } },
    ]);

    const lookup = await ctx.query<{ cart: CartShape | null }>(/* GraphQL */ `
      { cart(id: "${created.id}") { id totalQuantity cost { subtotalAmount { amount currencyCode } } } }
    `);
    expect(lookup.data).toEqual({
      cart: {
        id: created.id,
        totalQuantity: 1,
        cost: { subtotalAmount: { amount: '19.99', currencyCode: 'CAD' } },
      },
    });
  });

  it('cartLinesAdd on a stale cart id bootstraps a fresh cart; cart(id) on it is null', async () => {
    const result = await ctx.query<{ cartLinesAdd: Payload }>(/* GraphQL */ `
      mutation {
        cartLinesAdd(cartId: "gid://shopify/Cart/missing", lines: [{ merchandiseId: "${AISLEARENA_VARIANT}", quantity: 1 }]) {
          cart { id totalQuantity }
          userErrors { code field }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data?.cartLinesAdd.userErrors).toEqual([]);
    expect(result.data?.cartLinesAdd.cart?.id).not.toBe('gid://shopify/Cart/missing');
    expect(result.data?.cartLinesAdd.cart?.totalQuantity).toBe(1);

    const query = await ctx.query<{ cart: null }>(
      /* GraphQL */ `{ cart(id: "gid://shopify/Cart/missing") { id } }`,
    );
    expect(query.data).toEqual({ cart: null });
  });

  it('cartLinesUpdate on an unknown cart reports INVALID cartId', async () => {
    const result = await ctx.query<{ cartLinesUpdate: Payload }>(/* GraphQL */ `
      mutation {
        cartLinesUpdate(cartId: "gid://shopify/Cart/missing", lines: [{ id: "x", quantity: 1 }]) {
          cart { id }
          userErrors { code field message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data?.cartLinesUpdate).toEqual({
      cart: null,
      userErrors: [{ code: 'INVALID', field: ['cartId'], message: 'Cart not found' }],
    });
  });
});
