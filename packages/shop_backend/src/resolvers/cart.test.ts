import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { type SandboxSchemaResolvers, createSandboxSchema } from '../schema.js';
import { CartStore, InvalidCartStoreFileError, cartResolvers } from './cart.js';
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
const AISLEARENA_VARIANT = 'gid://shopify/ProductVariant/47642512195758'; // $79.99
const SHOPLISEUM_VARIANT = 'gid://shopify/ProductVariant/47242666836142'; // $19.99

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

interface IncrementalExecutionPatch {
  readonly data?: unknown;
  readonly errors?: readonly unknown[];
  readonly path?: readonly (string | number)[];
}

interface MultipartExecutionPart extends ExecutionResult {
  readonly incremental?: readonly IncrementalExecutionPatch[];
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
    return await readExecutionResult(response);
  };
}

async function readExecutionResult(response: {
  readonly headers: { get(name: string): string | null };
  json(): Promise<unknown>;
  text(): Promise<string>;
}): Promise<ExecutionResult> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.startsWith('multipart/mixed')) {
    return (await response.json()) as ExecutionResult;
  }
  return mergeMultipartExecution(contentType, await response.text());
}

function mergeMultipartExecution(contentType: string, body: string): ExecutionResult {
  const boundary = multipartBoundary(contentType);
  const result: { data?: unknown; errors?: readonly unknown[] } = {};
  for (const part of multipartJsonParts(body, boundary)) {
    if (part.errors !== undefined) {
      result.errors = part.errors;
    }
    if (part.data !== undefined) {
      result.data = mergeAtPath(result.data, [], part.data);
    }
    for (const patch of part.incremental ?? []) {
      if (patch.errors !== undefined) {
        result.errors = patch.errors;
      }
      if (patch.data !== undefined && patch.path !== undefined) {
        result.data = mergeAtPath(result.data, patch.path, patch.data);
      }
    }
  }
  return result;
}

function multipartBoundary(contentType: string): string {
  const match = /boundary="?([^";]+)"?/.exec(contentType);
  if (match?.[1] === undefined) {
    throw new Error(`Missing multipart boundary in content type: ${contentType}`);
  }
  return match[1];
}

function multipartJsonParts(body: string, boundary: string): MultipartExecutionPart[] {
  const delimiter = `--${boundary}`;
  return body
    .split(delimiter)
    .map((part) => part.replaceAll('\r\n', '\n').trim())
    .filter((part) => part.length > 0 && part !== '--')
    .map(parseMultipartJsonPart);
}

function parseMultipartJsonPart(part: string): MultipartExecutionPart {
  const headerEnd = part.indexOf('\n\n');
  if (headerEnd < 0) {
    throw new Error(`Malformed multipart response part: ${part}`);
  }
  const jsonText = part
    .slice(headerEnd + 2)
    .replace(/\n--$/, '')
    .trim();
  return JSON.parse(jsonText) as MultipartExecutionPart;
}

function mergeAtPath(
  current: unknown,
  path: readonly (string | number)[],
  patch: unknown,
): unknown {
  const [head, ...tail] = path;
  if (head === undefined) {
    return mergeValues(current, patch);
  }
  if (typeof head === 'number') {
    const copy = Array.isArray(current) ? [...current] : [];
    copy[head] = mergeAtPath(copy[head], tail, patch);
    return copy;
  }
  const copy = isRecord(current) ? { ...current } : {};
  copy[head] = mergeAtPath(copy[head], tail, patch);
  return copy;
}

function mergeValues(current: unknown, patch: unknown): unknown {
  if (!isRecord(current) || !isRecord(patch)) {
    return patch;
  }
  const merged: Record<string, unknown> = { ...current };
  for (const [key, value] of Object.entries(patch)) {
    merged[key] = mergeValues(merged[key], value);
  }
  return merged;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
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
        { merchandiseId: AISLEARENA_VARIANT, quantity: 2 },
        { merchandiseId: SHOPLISEUM_VARIANT, quantity: 3 },
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
                id: AISLEARENA_VARIANT,
                product: { handle: 'aislearena-anti-tick-collar' },
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
                id: SHOPLISEUM_VARIANT,
                product: { handle: 'shopliseum-mushroom-dog-toys' },
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
        { merchandiseId: AISLEARENA_VARIANT, quantity: 1 },
        { merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 },
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

const CARTHAEUM_VARIANT = 'gid://shopify/ProductVariant/47694728298670'; // $12.99
const BOGUS_VARIANT = 'gid://shopify/ProductVariant/999999999'; // not in the dataset

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
            { merchandiseId: "${AISLEARENA_VARIANT}", quantity: 1 },
            { merchandiseId: "${SHOPLISEUM_VARIANT}", quantity: 2 }
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
    const aisleArenaLineId = created.lines[0]?.id;
    const shopliseumLineId = created.lines[1]?.id;
    if (aisleArenaLineId === undefined || shopliseumLineId === undefined) {
      throw new Error('unreachable: cart should have two lines');
    }
    expect(created.lines[0]?.merchandiseId).toBe(AISLEARENA_VARIANT);
    expect(created.lines[1]?.merchandiseId).toBe(SHOPLISEUM_VARIANT);

    // 2. cartLinesAdd: AISLEARENA merges, CARTHAEUM is a new line.
    const addResult = await run(/* GraphQL */ `
      mutation {
        cartLinesAdd(
          cartId: "${created.id}"
          lines: [
            { merchandiseId: "${AISLEARENA_VARIANT}", quantity: 2 }
            { merchandiseId: "${CARTHAEUM_VARIANT}", quantity: 1 }
          ]
        ) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(addResult.errors).toBeUndefined();
    const added = unwrapCart(addResult.data, 'cartLinesAdd');
    // AISLEARENA qty=3, SHOPLISEUM qty=2, CARTHAEUM qty=1 → 6 total.
    expect(added.totalQuantity).toBe(6);
    // 3 * 79.99 + 2 * 19.99 + 1 * 12.99 = 239.97 + 39.98 + 12.99 = 292.94.
    expect(added.subtotal).toBe('292.94');
    expect(added.lines).toHaveLength(3);
    expect(added.lines[0]?.id).toBe(aisleArenaLineId); // merged → same id
    expect(added.lines[0]?.quantity).toBe(3);

    // 3. cartLinesUpdate with quantity: 0 removes the SHOPLISEUM line.
    const updateResult = await run(/* GraphQL */ `
      mutation {
        cartLinesUpdate(
          cartId: "${created.id}"
          lines: [{ id: "${shopliseumLineId}", quantity: 0 }]
        ) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(updateResult.errors).toBeUndefined();
    const updated = unwrapCart(updateResult.data, 'cartLinesUpdate');
    expect(updated.totalQuantity).toBe(4); // 3 AISLEARENA + 1 CARTHAEUM
    // 3 * 79.99 + 1 * 12.99 = 239.97 + 12.99 = 252.96.
    expect(updated.subtotal).toBe('252.96');
    expect(updated.lines).toHaveLength(2);
    expect(updated.lines.some((l) => l.id === shopliseumLineId)).toBe(false);

    // 4. cartLinesRemove drops the AISLEARENA line.
    const removeResult = await run(/* GraphQL */ `
      mutation {
        cartLinesRemove(cartId: "${created.id}", lineIds: ["${aisleArenaLineId}"]) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(removeResult.errors).toBeUndefined();
    const removed = unwrapCart(removeResult.data, 'cartLinesRemove');
    expect(removed.totalQuantity).toBe(1);
    expect(removed.subtotal).toBe('12.99');
    expect(removed.lines).toHaveLength(1);
    expect(removed.lines[0]?.merchandiseId).toBe(CARTHAEUM_VARIANT);
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

  it('cartLinesAdd bootstraps a fresh cart when the cartId is unknown', async () => {
    // A stale client cookie can outlive an in-memory cart store across server
    // restarts. Auto-bootstrap so `Add to cart` recovers without a user-visible
    // failure; the response carries the new id for the client to refresh.
    const carts = new CartStore();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartLinesAdd(
          cartId: "gid://shopify/Cart/cart-999"
          lines: [{ merchandiseId: "${AISLEARENA_VARIANT}", quantity: 1 }]
        ) {
          ${CART_PAYLOAD_FRAGMENT}
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const cart = unwrapCart(result.data, 'cartLinesAdd');
    expect(cart.id).toBe('gid://shopify/Cart/cart-1');
    expect(cart.totalQuantity).toBe(1);
    expect(cart.lines).toHaveLength(1);
    expect(cart.lines[0]?.merchandiseId).toBe(AISLEARENA_VARIANT);
  });
});

// Merchandise validation

interface UserErrorPayload {
  readonly code: string | null;
  readonly field: readonly string[] | null;
  readonly message: string;
}

function userErrorsOf(payload: unknown, key: string): readonly UserErrorPayload[] {
  const node = (payload as Record<string, Record<string, unknown>>)?.[key];
  return (node?.userErrors as readonly UserErrorPayload[] | undefined) ?? [];
}

function cartIdOf(payload: unknown, key: string): string | null {
  const node = (payload as Record<string, Record<string, unknown>>)?.[key];
  const cart = node?.cart as { readonly id: string } | null | undefined;
  return cart?.id ?? null;
}

describe('cartResolvers - merchandise validation', () => {
  it('cartCreate rejects an unknown merchandiseId without allocating a phantom cart', async () => {
    const carts = new CartStore();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartCreate(input: { lines: [{ merchandiseId: "${BOGUS_VARIANT}", quantity: 1 }] }) {
          cart { id }
          userErrors { code field message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(cartIdOf(result.data, 'cartCreate')).toBeNull();
    expect(userErrorsOf(result.data, 'cartCreate')).toEqual([
      {
        code: 'INVALID',
        field: ['merchandiseId'],
        message: `Merchandise not found: ${BOGUS_VARIANT}`,
      },
    ]);
    // The failed create must not consume the counter. The next real cart is cart-1.
    expect(carts.create().id).toBe('gid://shopify/Cart/cart-1');
  });

  it('cartLinesAdd rejects an unknown merchandiseId and leaves the existing cart unchanged', async () => {
    const carts = new CartStore();
    const cart = carts.create({ lines: [{ merchandiseId: AISLEARENA_VARIANT, quantity: 1 }] });
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartLinesAdd(
          cartId: "${cart.id}"
          lines: [{ merchandiseId: "${BOGUS_VARIANT}", quantity: 2 }]
        ) {
          cart { id }
          userErrors { code field message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(cartIdOf(result.data, 'cartLinesAdd')).toBe(cart.id);
    expect(userErrorsOf(result.data, 'cartLinesAdd')).toEqual([
      {
        code: 'INVALID',
        field: ['merchandiseId'],
        message: `Merchandise not found: ${BOGUS_VARIANT}`,
      },
    ]);
    // No phantom line was stored.
    expect(cart.lines).toHaveLength(1);
    expect(cart.lines[0]?.merchandiseId).toBe(AISLEARENA_VARIANT);
    expect(cart.lines[0]?.quantity).toBe(1);
  });

  it('cartLinesAdd rejects an unknown merchandiseId instead of bootstrapping a new cart', async () => {
    const carts = new CartStore();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartLinesAdd(
          cartId: "gid://shopify/Cart/cart-999"
          lines: [{ merchandiseId: "${BOGUS_VARIANT}", quantity: 1 }]
        ) {
          cart { id }
          userErrors { code field message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(cartIdOf(result.data, 'cartLinesAdd')).toBeNull();
    expect(userErrorsOf(result.data, 'cartLinesAdd')).toEqual([
      {
        code: 'INVALID',
        field: ['merchandiseId'],
        message: `Merchandise not found: ${BOGUS_VARIANT}`,
      },
    ]);
    // No cart was bootstrapped for the bad id.
    expect(carts.create().id).toBe('gid://shopify/Cart/cart-1');
  });

  it('cartLinesUpdate rejects switching a line to an unknown merchandiseId', async () => {
    const carts = new CartStore();
    const cart = carts.create({ lines: [{ merchandiseId: AISLEARENA_VARIANT, quantity: 1 }] });
    const lineId = cart.lines[0]?.id;
    if (lineId === undefined) throw new Error('unreachable');
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartLinesUpdate(
          cartId: "${cart.id}"
          lines: [{ id: "${lineId}", merchandiseId: "${BOGUS_VARIANT}", quantity: 3 }]
        ) {
          cart { id }
          userErrors { code field message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(userErrorsOf(result.data, 'cartLinesUpdate')).toEqual([
      {
        code: 'INVALID',
        field: ['merchandiseId'],
        message: `Merchandise not found: ${BOGUS_VARIANT}`,
      },
    ]);
    // The line keeps its original merchandise and quantity.
    expect(cart.lines[0]?.merchandiseId).toBe(AISLEARENA_VARIANT);
    expect(cart.lines[0]?.quantity).toBe(1);
  });
});

// ── Cart extra-field mutations (T4.4) ─────────────────────────────────────

interface CartExtraSummary {
  readonly discountCodes: readonly { readonly code: string; readonly applicable: boolean }[];
  readonly appliedGiftCards: readonly {
    readonly id: string;
    readonly lastCharacters: string | null;
  }[];
  readonly note: string;
  readonly attributes: readonly { readonly key: string; readonly value: string }[];
  readonly buyerIdentity: {
    readonly countryCode: string | null;
    readonly email: string | null;
    readonly phone: string | null;
  };
}

const CART_EXTRA_FIELDS = /* GraphQL */ `
  cart {
    id
    note
    attributes { key value }
    discountCodes { code applicable }
    appliedGiftCards { id lastCharacters }
    buyerIdentity { countryCode email phone }
  }
  userErrors { code field message }
`;

async function readExtras(
  run: (source: string) => Promise<ExecutionResult>,
  cartId: string,
): Promise<CartExtraSummary> {
  const result = await run(/* GraphQL */ `
    {
      cart(id: "${cartId}") {
        note
        attributes { key value }
        discountCodes { code applicable }
        appliedGiftCards { id lastCharacters }
        buyerIdentity { countryCode email phone }
      }
    }
  `);
  expect(result.errors).toBeUndefined();
  const data = result.data as { readonly cart: CartExtraSummary | null };
  if (data.cart === null) throw new Error('expected cart to be non-null');
  return data.cart;
}

describe('cartResolvers — extra-field mutations (T4.4)', () => {
  it('cartDiscountCodesUpdate stores codes and reflects them on Query.cart', async () => {
    const carts = new CartStore();
    const cart = carts.create();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartDiscountCodesUpdate(
          cartId: "${cart.id}"
          discountCodes: ["SUMMER10", "WELCOME"]
        ) {
          ${CART_EXTRA_FIELDS}
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const extras = await readExtras(run, cart.id);
    expect(extras.discountCodes).toEqual([
      { code: 'SUMMER10', applicable: true },
      { code: 'WELCOME', applicable: true },
    ]);
  });

  it('cartDiscountCodesUpdate accepts Hydrogen deferred cart fragments', async () => {
    const carts = new CartStore();
    const cart = carts.create();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartDiscountCodesUpdate(
          cartId: "${cart.id}"
          discountCodes: ["SUMMER10"]
        ) {
          ... @defer {
            cart {
              discountCodes { code applicable }
            }
          }
          userErrors { code field message }
          warnings { code message target }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      cartDiscountCodesUpdate: {
        cart: {
          discountCodes: [{ code: 'SUMMER10', applicable: true }],
        },
        userErrors: [],
        warnings: [],
      },
    });
  });

  it('cartDiscountCodesUpdate with null clears stored codes', async () => {
    const carts = new CartStore();
    const cart = carts.create({ discountCodes: ['SAVE5'] });
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartDiscountCodesUpdate(cartId: "${cart.id}", discountCodes: null) {
          cart { discountCodes { code } }
          userErrors { message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const extras = await readExtras(run, cart.id);
    expect(extras.discountCodes).toEqual([]);
  });

  it('cartBuyerIdentityUpdate persists country, email, and phone', async () => {
    const carts = new CartStore();
    const cart = carts.create();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartBuyerIdentityUpdate(
          cartId: "${cart.id}"
          buyerIdentity: {
            countryCode: CA
            email: "buyer@example.com"
            phone: "+15551234567"
          }
        ) {
          ${CART_EXTRA_FIELDS}
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const extras = await readExtras(run, cart.id);
    expect(extras.buyerIdentity).toEqual({
      countryCode: 'CA',
      email: 'buyer@example.com',
      phone: '+15551234567',
    });
  });

  it('cartBuyerIdentityUpdate is partial — omitted fields are preserved', async () => {
    const carts = new CartStore();
    const cart = carts.create({
      buyerIdentity: { countryCode: 'CA', email: 'old@example.com', phone: '+11111111111' },
    });
    const run = runWith(carts);
    await run(/* GraphQL */ `
      mutation {
        cartBuyerIdentityUpdate(
          cartId: "${cart.id}"
          buyerIdentity: { email: "new@example.com" }
        ) {
          cart { id }
          userErrors { message }
        }
      }
    `);
    const extras = await readExtras(run, cart.id);
    expect(extras.buyerIdentity).toEqual({
      countryCode: 'CA',
      email: 'new@example.com',
      phone: '+11111111111',
    });
  });

  it('cartNoteUpdate persists a free-form note', async () => {
    const carts = new CartStore();
    const cart = carts.create();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartNoteUpdate(cartId: "${cart.id}", note: "Please gift wrap.") {
          ${CART_EXTRA_FIELDS}
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const extras = await readExtras(run, cart.id);
    expect(extras.note).toBe('Please gift wrap.');
  });

  it('cartAttributesUpdate replaces stored attributes', async () => {
    const carts = new CartStore();
    const cart = carts.create({ attributes: [{ key: 'old', value: 'value' }] });
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartAttributesUpdate(
          cartId: "${cart.id}"
          attributes: [
            { key: "engraving", value: "Hello" }
            { key: "gift", value: "true" }
          ]
        ) {
          ${CART_EXTRA_FIELDS}
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const extras = await readExtras(run, cart.id);
    expect(extras.attributes).toEqual([
      { key: 'engraving', value: 'Hello' },
      { key: 'gift', value: 'true' },
    ]);
  });

  it('cartGiftCardCodesUpdate materializes AppliedGiftCard nodes with last4', async () => {
    const carts = new CartStore();
    const cart = carts.create();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartGiftCardCodesUpdate(
          cartId: "${cart.id}"
          giftCardCodes: ["GIFT-ABCD-1234", "AB"]
        ) {
          ${CART_EXTRA_FIELDS}
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const extras = await readExtras(run, cart.id);
    expect(extras.appliedGiftCards).toHaveLength(2);
    expect(extras.appliedGiftCards[0]?.lastCharacters).toBe('1234');
    expect(extras.appliedGiftCards[1]?.lastCharacters).toBe('AB');
    expect(extras.appliedGiftCards[0]?.id).toMatch(
      /^gid:\/\/shopify\/AppliedGiftCard\/[0-9a-f]{8}$/,
    );
    // GIDs are deterministic per code.
    expect(extras.appliedGiftCards[0]?.id).not.toBe(extras.appliedGiftCards[1]?.id);
  });

  it('cartGiftCardCodesAdd and cartGiftCardCodesRemove match Hydrogen helper mutations', async () => {
    const carts = new CartStore();
    const cart = carts.create({ giftCardCodes: ['GIFT-ABCD-1234'] });
    const run = runWith(carts);
    const addResult = await run(/* GraphQL */ `
      mutation {
        cartGiftCardCodesAdd(
          cartId: "${cart.id}"
          giftCardCodes: ["GIFT-ABCD-1234", "GIFT-WXYZ-5678"]
        ) {
          ${CART_EXTRA_FIELDS}
        }
      }
    `);
    expect(addResult.errors).toBeUndefined();
    const afterAdd = await readExtras(run, cart.id);
    expect(afterAdd.appliedGiftCards.map((card) => card.lastCharacters)).toEqual(['1234', '5678']);

    const removeId = afterAdd.appliedGiftCards[0]?.id;
    if (removeId === undefined) throw new Error('expected first gift-card id');
    const removeResult = await run(/* GraphQL */ `
      mutation {
        cartGiftCardCodesRemove(
          cartId: "${cart.id}"
          appliedGiftCardIds: ["${removeId}"]
        ) {
          ${CART_EXTRA_FIELDS}
        }
      }
    `);
    expect(removeResult.errors).toBeUndefined();
    const afterRemove = await readExtras(run, cart.id);
    expect(afterRemove.appliedGiftCards.map((card) => card.lastCharacters)).toEqual(['5678']);
  });

  it('extra-field mutations return INVALID userError when cartId is unknown', async () => {
    const carts = new CartStore();
    const run = runWith(carts);
    const result = await run(/* GraphQL */ `
      mutation {
        cartNoteUpdate(cartId: "gid://shopify/Cart/cart-999", note: "ignored") {
          cart { id }
          userErrors { code field message }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      cartNoteUpdate: {
        cart: null,
        userErrors: [{ code: 'INVALID', field: ['cartId'], message: 'Cart not found' }],
      },
    });
  });
});

describe('CartStore — persistence (T7.4)', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cart-store-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('writes the snapshot file on cart creation', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    const store = new CartStore({ persistencePath: filePath });
    const cart = store.create();

    expect(fs.existsSync(filePath)).toBe(true);
    const snapshot = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as {
      version: number;
      cartCounter: number;
      lineCounters: Record<string, number>;
      carts: Record<string, unknown>;
    };
    expect(snapshot.version).toBe(1);
    expect(snapshot.cartCounter).toBe(1);
    expect(snapshot.carts).toHaveProperty(cart.id);
  });

  it('persists line mutations through addLines / updateLines / removeLines', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    const storeA = new CartStore({ persistencePath: filePath });
    const cart = storeA.create();
    storeA.addLines(cart, [{ merchandiseId: VARIANT_A, quantity: 2 }]);
    const lineId = cart.lines[0]?.id;
    expect(lineId).toBeDefined();

    const storeB = new CartStore({ persistencePath: filePath });
    const reloaded = storeB.get(cart.id);
    expect(reloaded?.lines).toHaveLength(1);
    expect(reloaded?.lines[0]).toMatchObject({ merchandiseId: VARIANT_A, quantity: 2 });

    storeA.updateLines(cart, [{ id: lineId as string, quantity: 5 }]);
    const storeC = new CartStore({ persistencePath: filePath });
    expect(storeC.get(cart.id)?.lines[0]?.quantity).toBe(5);

    storeA.removeLines(cart, [lineId as string]);
    const storeD = new CartStore({ persistencePath: filePath });
    expect(storeD.get(cart.id)?.lines).toEqual([]);
  });

  it('round-trips a cart between store instances (the T7.4 acceptance check)', () => {
    const filePath = path.join(tmpDir, 'carts.json');

    // Run A: create the cart.
    const runA = new CartStore({ persistencePath: filePath });
    const cart = runA.create();
    runA.addLines(cart, [
      { merchandiseId: VARIANT_A, quantity: 3 },
      { merchandiseId: VARIANT_B, quantity: 1 },
    ]);
    runA.setNote(cart, 'gift wrap please');
    runA.setDiscountCodes(cart, ['SAVE10']);
    runA.setBuyerIdentity(cart, { email: 'buyer@example.com', countryCode: 'US' });

    // Run B: brand-new CartStore pointed at the same path.
    const runB = new CartStore({ persistencePath: filePath });
    const seen = runB.get(cart.id);
    expect(seen).toBeDefined();
    expect(seen?.id).toBe(cart.id);
    expect(seen?.lines).toHaveLength(2);
    expect(seen?.lines.map((l) => l.merchandiseId)).toEqual([VARIANT_A, VARIANT_B]);
    expect(seen?.lines.map((l) => l.quantity)).toEqual([3, 1]);
    expect(seen?.note).toBe('gift wrap please');
    expect(seen?.discountCodes).toEqual(['SAVE10']);
    expect(seen?.buyerIdentity).toEqual({
      countryCode: 'US',
      email: 'buyer@example.com',
      phone: null,
    });
  });

  it('preserves the cart counter so new carts in run B continue the sequence', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    const runA = new CartStore({ persistencePath: filePath });
    runA.create();
    runA.create();
    expect(runA.create().id).toBe('gid://shopify/Cart/cart-3');

    const runB = new CartStore({ persistencePath: filePath });
    expect(runB.create().id).toBe('gid://shopify/Cart/cart-4');
  });

  it('preserves line counters so re-loaded carts mint distinct line ids', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    const runA = new CartStore({ persistencePath: filePath });
    const cart = runA.create();
    runA.addLines(cart, [{ merchandiseId: VARIANT_A, quantity: 1 }]);
    const firstLineId = cart.lines[0]?.id;
    expect(firstLineId).toBeDefined();

    const runB = new CartStore({ persistencePath: filePath });
    const seen = runB.get(cart.id);
    if (seen === undefined) throw new Error('expected cart to be reloaded');
    runB.addLines(seen, [{ merchandiseId: VARIANT_B, quantity: 1 }]);
    expect(seen.lines).toHaveLength(2);
    expect(seen.lines[1]?.id).not.toBe(firstLineId);
    expect(seen.lines[1]?.id).toBe('gid://shopify/CartLine/cart-1-line-2');
  });

  it('clear() resets in-memory state without deleting the persistence file', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    const store = new CartStore({ persistencePath: filePath });
    const cart = store.create();
    expect(fs.existsSync(filePath)).toBe(true);

    store.clear();
    expect(store.get(cart.id)).toBeUndefined();
    expect(fs.existsSync(filePath)).toBe(true);

    // A new store at the same path still sees the cart.
    const reloaded = new CartStore({ persistencePath: filePath });
    expect(reloaded.get(cart.id)?.id).toBe(cart.id);
  });

  it('creates the parent directory when the persistence path lives under a missing folder', () => {
    const filePath = path.join(tmpDir, 'nested', 'subdir', 'carts.json');
    const store = new CartStore({ persistencePath: filePath });
    store.create();
    expect(fs.existsSync(filePath)).toBe(true);
  });

  it('treats an absent persistence file as an empty store', () => {
    const filePath = path.join(tmpDir, 'does-not-exist.json');
    expect(fs.existsSync(filePath)).toBe(false);
    const store = new CartStore({ persistencePath: filePath });
    expect(store.create().id).toBe('gid://shopify/Cart/cart-1');
  });

  it('throws InvalidCartStoreFileError on malformed JSON', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    fs.writeFileSync(filePath, '{ not valid json');
    expect(() => new CartStore({ persistencePath: filePath })).toThrowError(
      InvalidCartStoreFileError,
    );
  });

  it('throws InvalidCartStoreFileError when the snapshot version is wrong', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    fs.writeFileSync(
      filePath,
      JSON.stringify({ version: 99, cartCounter: 0, lineCounters: {}, carts: {} }),
    );
    expect(() => new CartStore({ persistencePath: filePath })).toThrowError(
      /unsupported snapshot version/,
    );
  });

  it('throws InvalidCartStoreFileError when the cart id does not match its map key', () => {
    const filePath = path.join(tmpDir, 'carts.json');
    fs.writeFileSync(
      filePath,
      JSON.stringify({
        version: 1,
        cartCounter: 1,
        lineCounters: { 'gid://shopify/Cart/cart-1': 0 },
        carts: {
          'gid://shopify/Cart/cart-1': {
            id: 'gid://shopify/Cart/cart-99',
            lines: [],
            discountCodes: [],
            giftCardCodes: [],
            buyerIdentity: { countryCode: null, email: null, phone: null },
            note: '',
            attributes: [],
          },
        },
      }),
    );
    expect(() => new CartStore({ persistencePath: filePath })).toThrowError(
      /must match the map key/,
    );
  });
});
