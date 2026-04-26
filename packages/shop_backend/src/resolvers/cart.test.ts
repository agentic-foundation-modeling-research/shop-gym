import { describe, expect, it } from 'vitest';

import { CartStore } from './cart.js';

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
