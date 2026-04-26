import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { type SandboxSchemaResolvers, createSandboxSchema } from '../schema.js';
import { CartStore, cartResolvers } from './cart.js';
import type { ResolverContext } from './index.js';

const VARIANT_A = 'gid://shopify/ProductVariant/100';
const VARIANT_B = 'gid://shopify/ProductVariant/200';

describe('CartStore.create', () => {
  it('allocates a deterministic cart-<n> GID with empty lines', () => {
    const store = new CartStore();
    const cart = store.create();
    expect(cart.id).toBe('gid://shopify/Cart/cart-1');
    expect(cart.lines).toEqual([]);
  });

  it('increments the counter across calls', () => {
    const store = new CartStore();
    const first = store.create();
    const second = store.create();
    expect(first.id).toBe('gid://shopify/Cart/cart-1');
    expect(second.id).toBe('gid://shopify/Cart/cart-2');
  });

  it('honors initial lines and merges duplicates', () => {
    const store = new CartStore();
    const cart = store.create({
      lines: [
        { merchandiseId: VARIANT_A, quantity: 2 },
        { merchandiseId: VARIANT_A, quantity: 3 },
        { merchandiseId: VARIANT_B },
      ],
    });
    expect(cart.lines).toHaveLength(2);
    const lineA = cart.lines[0];
    const lineB = cart.lines[1];
    if (lineA === undefined || lineB === undefined) throw new Error('unreachable');
    expect(lineA.merchandiseId).toBe(VARIANT_A);
    expect(lineA.quantity).toBe(5);
    expect(lineB.merchandiseId).toBe(VARIANT_B);
    expect(lineB.quantity).toBe(1);
  });

  it('treats null/undefined input as an empty cart', () => {
    const store = new CartStore();
    expect(store.create(null).lines).toEqual([]);
    expect(store.create(undefined).lines).toEqual([]);
    expect(store.create({}).lines).toEqual([]);
  });
});

describe('CartStore.get', () => {
  it('returns the same cart instance the store holds', () => {
    const store = new CartStore();
    const cart = store.create();
    expect(store.get(cart.id)).toBe(cart);
  });

  it('returns undefined for unknown cart ids', () => {
    const store = new CartStore();
    expect(store.get('gid://shopify/Cart/cart-999')).toBeUndefined();
  });
});

describe('CartStore.addLines', () => {
  it('appends new merchandise as a separate line with a deterministic id', () => {
    const store = new CartStore();
    const cart = store.create();
    store.addLines(cart, [{ merchandiseId: VARIANT_A, quantity: 2 }]);
    store.addLines(cart, [{ merchandiseId: VARIANT_B, quantity: 1 }]);
    expect(cart.lines).toHaveLength(2);
    expect(cart.lines[0]?.id).toBe('gid://shopify/CartLine/cart-1-line-1');
    expect(cart.lines[1]?.id).toBe('gid://shopify/CartLine/cart-1-line-2');
  });

  it('merges duplicate merchandiseIds by summing quantities', () => {
    const store = new CartStore();
    const cart = store.create();
    store.addLines(cart, [{ merchandiseId: VARIANT_A, quantity: 1 }]);
    store.addLines(cart, [{ merchandiseId: VARIANT_A, quantity: 4 }]);
    expect(cart.lines).toHaveLength(1);
    expect(cart.lines[0]?.quantity).toBe(5);
    // The merged line keeps its original id.
    expect(cart.lines[0]?.id).toBe('gid://shopify/CartLine/cart-1-line-1');
  });

  it('defaults quantity to 1 when omitted', () => {
    const store = new CartStore();
    const cart = store.create();
    store.addLines(cart, [{ merchandiseId: VARIANT_A }]);
    expect(cart.lines[0]?.quantity).toBe(1);
  });

  it('captures attributes per line', () => {
    const store = new CartStore();
    const cart = store.create();
    store.addLines(cart, [
      {
        merchandiseId: VARIANT_A,
        quantity: 1,
        attributes: [{ key: 'engraving', value: 'Hello' }],
      },
    ]);
    expect(cart.lines[0]?.attributes).toEqual([{ key: 'engraving', value: 'Hello' }]);
  });
});

describe('CartStore.updateLines', () => {
  it('overwrites quantity for a known line', () => {
    const store = new CartStore();
    const cart = store.create({ lines: [{ merchandiseId: VARIANT_A, quantity: 1 }] });
    const lineId = cart.lines[0]?.id;
    if (lineId === undefined) throw new Error('unreachable');
    store.updateLines(cart, [{ id: lineId, quantity: 5 }]);
    expect(cart.lines[0]?.quantity).toBe(5);
  });

  it('removes a line when quantity drops to zero', () => {
    const store = new CartStore();
    const cart = store.create({ lines: [{ merchandiseId: VARIANT_A, quantity: 1 }] });
    const lineId = cart.lines[0]?.id;
    if (lineId === undefined) throw new Error('unreachable');
    store.updateLines(cart, [{ id: lineId, quantity: 0 }]);
    expect(cart.lines).toEqual([]);
  });

  it('ignores updates targeting unknown line ids', () => {
    const store = new CartStore();
    const cart = store.create({ lines: [{ merchandiseId: VARIANT_A, quantity: 1 }] });
    store.updateLines(cart, [{ id: 'gid://shopify/CartLine/missing', quantity: 9 }]);
    expect(cart.lines).toHaveLength(1);
    expect(cart.lines[0]?.quantity).toBe(1);
  });

  it('overwrites merchandiseId and attributes when supplied', () => {
    const store = new CartStore();
    const cart = store.create({ lines: [{ merchandiseId: VARIANT_A, quantity: 2 }] });
    const lineId = cart.lines[0]?.id;
    if (lineId === undefined) throw new Error('unreachable');
    store.updateLines(cart, [
      {
        id: lineId,
        merchandiseId: VARIANT_B,
        attributes: [{ key: 'gift_wrap', value: 'true' }],
      },
    ]);
    expect(cart.lines[0]?.merchandiseId).toBe(VARIANT_B);
    expect(cart.lines[0]?.quantity).toBe(2);
    expect(cart.lines[0]?.attributes).toEqual([{ key: 'gift_wrap', value: 'true' }]);
  });
});

describe('CartStore.removeLines', () => {
  it('removes only the lines whose ids match', () => {
    const store = new CartStore();
    const cart = store.create({
      lines: [
        { merchandiseId: VARIANT_A, quantity: 1 },
        { merchandiseId: VARIANT_B, quantity: 1 },
      ],
    });
    const firstId = cart.lines[0]?.id;
    if (firstId === undefined) throw new Error('unreachable');
    store.removeLines(cart, [firstId]);
    expect(cart.lines).toHaveLength(1);
    expect(cart.lines[0]?.merchandiseId).toBe(VARIANT_B);
  });

  it('is a no-op for unknown ids', () => {
    const store = new CartStore();
    const cart = store.create({ lines: [{ merchandiseId: VARIANT_A, quantity: 1 }] });
    store.removeLines(cart, ['gid://shopify/CartLine/missing']);
    expect(cart.lines).toHaveLength(1);
  });
});

describe('CartStore round-trip lifecycle', () => {
  it('exercises create → addLines (merge) → updateLines → removeLines', () => {
    const store = new CartStore();
    const cart = store.create({ lines: [{ merchandiseId: VARIANT_A, quantity: 1 }] });

    store.addLines(cart, [
      { merchandiseId: VARIANT_A, quantity: 2 },
      { merchandiseId: VARIANT_B, quantity: 1 },
    ]);
    expect(cart.lines).toHaveLength(2);
    expect(cart.lines[0]?.quantity).toBe(3);

    const lineAId = cart.lines[0]?.id;
    const lineBId = cart.lines[1]?.id;
    if (lineAId === undefined || lineBId === undefined) throw new Error('unreachable');

    store.updateLines(cart, [{ id: lineAId, quantity: 10 }]);
    expect(cart.lines[0]?.quantity).toBe(10);

    store.removeLines(cart, [lineBId]);
    expect(cart.lines).toHaveLength(1);
    expect(cart.lines[0]?.merchandiseId).toBe(VARIANT_A);
  });
});

describe('CartStore.clear', () => {
  it('resets storage and the cart counter', () => {
    const store = new CartStore();
    const first = store.create();
    store.clear();
    expect(store.get(first.id)).toBeUndefined();
    const fresh = store.create();
    expect(fresh.id).toBe('gid://shopify/Cart/cart-1');
  });
});

// ── Query.cart resolver (T4.2) ────────────────────────────────────────────

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);
const BASE_URL = 'https://shop.example';
const TICKLESS_VARIANT = 'gid://shopify/ProductVariant/47642512195758'; // $79.99
const FUZZYARD_VARIANT = 'gid://shopify/ProductVariant/47242666836142'; // $19.99

const resolvers: SandboxSchemaResolvers = {
  Query: cartResolvers.Query,
  Mutation: cartResolvers.Mutation,
  Cart: cartResolvers.Cart,
  BaseCartLine: cartResolvers.BaseCartLine,
  Merchandise: cartResolvers.Merchandise,
};

interface ExecutionResult {
  readonly data?: unknown;
  readonly errors?: readonly unknown[];
}

function runWith(carts: CartStore) {
  const data = loadShopData(FIXTURE_DIR);
  const yoga = createYoga({
    schema: createSandboxSchema(resolvers),
    context: (): ResolverContext => ({ data, carts, baseUrl: BASE_URL }),
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

describe('cartResolvers — Query.cart', () => {
  it('returns null for an unknown cart id', async () => {
    const run = runWith(new CartStore());
    const result = await run(/* GraphQL */ `
      {
        cart(id: "gid://shopify/Cart/cart-999") {
          id
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ cart: null });
  });

  it('round-trips a known cart with materialized lines, totals, and merchandise', async () => {
    const carts = new CartStore();
    const cart = carts.create({
      lines: [
        { merchandiseId: TICKLESS_VARIANT, quantity: 2 },
        { merchandiseId: FUZZYARD_VARIANT, quantity: 3 },
      ],
    });
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      {
        cart(id: "${cart.id}") {
          id
          checkoutUrl
          totalQuantity
          note
          cost {
            subtotalAmount {
              amount
              currencyCode
            }
            totalAmount {
              amount
            }
            totalTaxAmount {
              amount
            }
          }
          lines(first: 10) {
            nodes {
              ... on CartLine {
                id
                quantity
                cost {
                  amountPerQuantity {
                    amount
                  }
                  totalAmount {
                    amount
                  }
                }
                merchandise {
                  ... on ProductVariant {
                    id
                    product {
                      handle
                    }
                  }
                }
              }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      cart: {
        id: cart.id,
        checkoutUrl: '#',
        totalQuantity: 5,
        note: '',
        // 2 * 79.99 + 3 * 19.99 = 159.98 + 59.97 = 219.95.
        cost: {
          subtotalAmount: { amount: '219.95', currencyCode: 'CAD' },
          totalAmount: { amount: '219.95' },
          totalTaxAmount: null,
        },
        lines: {
          nodes: [
            {
              id: 'gid://shopify/CartLine/cart-1-line-1',
              quantity: 2,
              cost: {
                amountPerQuantity: { amount: '79.99' },
                totalAmount: { amount: '159.98' },
              },
              merchandise: {
                id: TICKLESS_VARIANT,
                product: { handle: 'tickless-anti-tick-collar' },
              },
            },
            {
              id: 'gid://shopify/CartLine/cart-1-line-2',
              quantity: 3,
              cost: {
                amountPerQuantity: { amount: '19.99' },
                totalAmount: { amount: '59.97' },
              },
              merchandise: {
                id: FUZZYARD_VARIANT,
                product: { handle: 'fuzzyard-mushroom-dog-toys' },
              },
            },
          ],
        },
      },
    });
  });

  it('honors Cart.lines(first: N) by trimming the materialized list', async () => {
    const carts = new CartStore();
    const cart = carts.create({
      lines: [
        { merchandiseId: TICKLESS_VARIANT, quantity: 1 },
        { merchandiseId: FUZZYARD_VARIANT, quantity: 1 },
      ],
    });
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      {
        cart(id: "${cart.id}") {
          lines(first: 1) {
            nodes {
              ... on CartLine {
                quantity
              }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ cart: { lines: { nodes: [{ quantity: 1 }] } } });
  });

  it('returns an empty cart with zero totals when no lines have been added', async () => {
    const carts = new CartStore();
    const cart = carts.create();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      {
        cart(id: "${cart.id}") {
          totalQuantity
          cost {
            subtotalAmount {
              amount
            }
          }
          lines {
            nodes {
              ... on CartLine {
                id
              }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      cart: {
        totalQuantity: 0,
        cost: { subtotalAmount: { amount: '0.00' } },
        lines: { nodes: [] },
      },
    });
  });
});

// ── Cart mutations (T4.3) ─────────────────────────────────────────────────

const BLUESTEM_VARIANT = 'gid://shopify/ProductVariant/47694728298670'; // $12.99

interface CartLineSummary {
  readonly id: string;
  readonly quantity: number;
  readonly merchandiseId: string;
}

interface CartSummary {
  readonly id: string;
  readonly totalQuantity: number;
  readonly subtotal: string;
  readonly lines: readonly CartLineSummary[];
}

function unwrapCart(payload: unknown, key: string): CartSummary {
  if (typeof payload !== 'object' || payload === null) {
    throw new Error(`payload is not an object for ${key}`);
  }
  const node = (payload as Record<string, unknown>)[key];
  if (typeof node !== 'object' || node === null) {
    throw new Error(`payload.${key} is not an object`);
  }
  const cart = (node as Record<string, unknown>).cart;
  if (typeof cart !== 'object' || cart === null) {
    throw new Error(`payload.${key}.cart is null or not an object`);
  }
  const summary = cart as {
    readonly id: string;
    readonly totalQuantity: number;
    readonly cost: { readonly subtotalAmount: { readonly amount: string } };
    readonly lines: {
      readonly nodes: readonly {
        readonly id: string;
        readonly quantity: number;
        readonly merchandise: { readonly id: string };
      }[];
    };
  };
  return {
    id: summary.id,
    totalQuantity: summary.totalQuantity,
    subtotal: summary.cost.subtotalAmount.amount,
    lines: summary.lines.nodes.map((line) => ({
      id: line.id,
      quantity: line.quantity,
      merchandiseId: line.merchandise.id,
    })),
  };
}

const CART_PAYLOAD_FRAGMENT = /* GraphQL */ `
  cart {
    id
    totalQuantity
    cost {
      subtotalAmount {
        amount
      }
    }
    lines(first: 10) {
      nodes {
        ... on CartLine {
          id
          quantity
          merchandise {
            ... on ProductVariant {
              id
            }
          }
        }
      }
    }
  }
  userErrors {
    code
    field
    message
  }
`;

describe('cartResolvers — line mutations (T4.3)', () => {
  it('round-trips the canonical lifecycle: cartCreate → cartLinesAdd → cartLinesUpdate(0) → cartLinesRemove', async () => {
    const carts = new CartStore();
    const run = runWith(carts);

    // 1. cartCreate with two starting lines.
    const createResult = await run(/* GraphQL */ `
      mutation {
        cartCreate(input: {
          lines: [
            { merchandiseId: "${TICKLESS_VARIANT}", quantity: 1 },
            { merchandiseId: "${FUZZYARD_VARIANT}", quantity: 2 }
          ]
        }) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(createResult.errors).toBeUndefined();
    const created = unwrapCart(createResult.data, 'cartCreate');
    expect(created.id).toBe('gid://shopify/Cart/cart-1');
    expect(created.totalQuantity).toBe(3);
    // 1 * 79.99 + 2 * 19.99 = 79.99 + 39.98 = 119.97.
    expect(created.subtotal).toBe('119.97');
    expect(created.lines).toHaveLength(2);
    const ticklessLineId = created.lines[0]?.id;
    const fuzzyardLineId = created.lines[1]?.id;
    if (ticklessLineId === undefined || fuzzyardLineId === undefined) {
      throw new Error('unreachable: cart should have two lines');
    }
    expect(created.lines[0]?.merchandiseId).toBe(TICKLESS_VARIANT);
    expect(created.lines[1]?.merchandiseId).toBe(FUZZYARD_VARIANT);

    // 2. cartLinesAdd: TICKLESS merges, BLUESTEM is a new line.
    const addResult = await run(/* GraphQL */ `
      mutation {
        cartLinesAdd(
          cartId: "${created.id}"
          lines: [
            { merchandiseId: "${TICKLESS_VARIANT}", quantity: 2 }
            { merchandiseId: "${BLUESTEM_VARIANT}", quantity: 1 }
          ]
        ) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(addResult.errors).toBeUndefined();
    const added = unwrapCart(addResult.data, 'cartLinesAdd');
    // TICKLESS qty=3, FUZZYARD qty=2, BLUESTEM qty=1 → 6 total.
    expect(added.totalQuantity).toBe(6);
    // 3 * 79.99 + 2 * 19.99 + 1 * 12.99 = 239.97 + 39.98 + 12.99 = 292.94.
    expect(added.subtotal).toBe('292.94');
    expect(added.lines).toHaveLength(3);
    expect(added.lines[0]?.id).toBe(ticklessLineId); // merged → same id
    expect(added.lines[0]?.quantity).toBe(3);

    // 3. cartLinesUpdate with quantity: 0 removes the FUZZYARD line.
    const updateResult = await run(/* GraphQL */ `
      mutation {
        cartLinesUpdate(
          cartId: "${created.id}"
          lines: [{ id: "${fuzzyardLineId}", quantity: 0 }]
        ) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(updateResult.errors).toBeUndefined();
    const updated = unwrapCart(updateResult.data, 'cartLinesUpdate');
    expect(updated.totalQuantity).toBe(4); // 3 TICKLESS + 1 BLUESTEM
    // 3 * 79.99 + 1 * 12.99 = 239.97 + 12.99 = 252.96.
    expect(updated.subtotal).toBe('252.96');
    expect(updated.lines).toHaveLength(2);
    expect(updated.lines.some((l) => l.id === fuzzyardLineId)).toBe(false);

    // 4. cartLinesRemove drops the TICKLESS line.
    const removeResult = await run(/* GraphQL */ `
      mutation {
        cartLinesRemove(cartId: "${created.id}", lineIds: ["${ticklessLineId}"]) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(removeResult.errors).toBeUndefined();
    const removed = unwrapCart(removeResult.data, 'cartLinesRemove');
    expect(removed.totalQuantity).toBe(1);
    expect(removed.subtotal).toBe('12.99');
    expect(removed.lines).toHaveLength(1);
    expect(removed.lines[0]?.merchandiseId).toBe(BLUESTEM_VARIANT);
  });

  it('cartCreate with no input allocates an empty cart', async () => {
    const carts = new CartStore();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartCreate(input: {}) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const created = unwrapCart(result.data, 'cartCreate');
    expect(created.id).toBe('gid://shopify/Cart/cart-1');
    expect(created.totalQuantity).toBe(0);
    expect(created.subtotal).toBe('0.00');
    expect(created.lines).toEqual([]);
  });

  it('returns a cartId userError when cartLinesAdd targets an unknown cart', async () => {
    const carts = new CartStore();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartLinesAdd(
          cartId: "gid://shopify/Cart/cart-999"
          lines: [{ merchandiseId: "${TICKLESS_VARIANT}", quantity: 1 }]
        ) {
          cart { id }
          userErrors { code field message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      cartLinesAdd: {
        cart: null,
        userErrors: [{ code: 'INVALID', field: ['cartId'], message: 'Cart not found' }],
      },
    });
  });
});
