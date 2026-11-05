/**
 * Tests for `ShopState`: dataset seeding, fork isolation, deterministic ids
 * and timestamps, and the checkout transition (`placeOrder`).
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import type { SandboxShopData } from '../data/types.js';
import { type NewAddress, type PlaceOrderInput, ShopState } from './shop_state.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const AISLEARENA_VARIANT = 'gid://shopify/ProductVariant/47642512195758'; // $79.99, untracked
const SHOPLISEUM_VARIANT = 'gid://shopify/ProductVariant/47242666836142'; // $19.99, qty 2
const CARTANVIL_VARIANT = 'gid://shopify/ProductVariant/47662525055150'; // available: false
const SHOPLISEUM_ID = 47242666836142;

const ADDRESS: NewAddress = {
  firstName: 'Sam',
  lastName: 'Buyer',
  company: null,
  address1: '1 Main St',
  address2: null,
  city: 'Toronto',
  province: 'Ontario',
  provinceCode: 'ON',
  country: 'Canada',
  countryCode: 'CA',
  zip: 'M5V 1A1',
  phone: null,
};

let cached: SandboxShopData | null = null;
function fixture(): SandboxShopData {
  cached ??= loadShopData(FIXTURE_DIR);
  return cached;
}

function checkout(
  state: ShopState,
  lines: readonly { merchandiseId: string; quantity: number }[],
  method = 'standard',
): PlaceOrderInput {
  const cart = state.carts.create({ lines: [...lines] });
  const shippingMethod = state.data.commerce.shipping_methods.find((m) => m.handle === method);
  const paymentMethod = state.data.commerce.payment_methods[0];
  if (shippingMethod === undefined || paymentMethod === undefined) {
    throw new Error('fixture commerce.json is missing methods');
  }
  return {
    cart,
    email: 'sam@example.com',
    shippingAddress: ADDRESS,
    shippingMethod,
    paymentMethod,
  };
}

describe('ShopState - seeding', () => {
  it('seeds customers and orders from the dataset', () => {
    const state = new ShopState(fixture(), 'default');
    expect(state.listCustomers().map((c) => c.email)).toEqual([
      'jane.doe@example.com',
      'marc.tremblay@example.com',
      'priya.nair@example.com',
      'sam.okafor@example.com',
    ]);
    expect(state.getOrder(1001)?.lineItems[0]?.variantId).toBe(SHOPLISEUM_ID);
    expect(state.ordersForCustomer(1)).toHaveLength(1);
    expect(state.ordersForCustomer(3).map((o) => o.id)).toEqual([1003, 1004, 1006]);
    expect(state.ordersForCustomer(4)).toEqual([]);
    expect(state.findCustomerByEmail('JANE.DOE@example.com')?.id).toBe(1);
  });

  it('exposes a dataset view whose inventory map is the live episode copy', () => {
    const data = fixture();
    const state = new ShopState(data, 'default');
    expect(state.data.products).toBe(data.products);
    expect(state.data.inventoryByVariantId).not.toBe(data.inventoryByVariantId);
    expect(state.data.inventoryByVariantId.get(SHOPLISEUM_ID)?.quantity_available).toBe(2);
  });

  it('allocates ids above every seeded record', () => {
    const state = new ShopState(fixture(), 'default');
    const customer = state.createCustomer({
      email: 'new@example.com',
      password: 'secret1',
      firstName: null,
      lastName: null,
      phone: null,
      acceptsMarketing: false,
    });
    expect(customer.id).toBe(5);
    const result = state.placeOrder(
      checkout(state, [{ merchandiseId: AISLEARENA_VARIANT, quantity: 1 }]),
    );
    expect(result.ok && result.order.id).toBe(1007);
    // Address ids continue after the seeded customer (1, 3-8) and order (2, 9-13) addresses.
    expect(result.ok && result.order.shippingAddress?.id).toBe(14);
  });
});

describe('ShopState - determinism', () => {
  it('replays the same action sequence to identical ids and timestamps', () => {
    const run = (): readonly unknown[] => {
      const state = new ShopState(fixture(), 'ep');
      const session = state.createSession(1);
      const result = state.placeOrder(
        checkout(state, [{ merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 }]),
      );
      return [
        session.accessToken,
        session.expiresAt,
        result.ok && result.order.processedAt,
        state.clock.now(),
      ];
    };
    const first = run();
    expect(first).toEqual(run());
    expect(first[0]).toBe('sandbox-token-1');
    expect(first[2]).toBe('2026-01-01T00:00:02.000Z');
  });

  it('honours a custom start time', () => {
    const state = new ShopState(fixture(), 'ep', { startTime: '2030-05-05T00:00:00.000Z' });
    expect(state.clock.now()).toBe('2030-05-05T00:00:00.000Z');
  });
});

describe('ShopState - fork isolation', () => {
  it('keeps carts, orders, and inventory separate between forks', () => {
    const base = new ShopState(fixture(), 'default');
    const a = base.fork('a');
    const b = base.fork('b');
    const result = a.placeOrder(checkout(a, [{ merchandiseId: SHOPLISEUM_VARIANT, quantity: 2 }]));
    expect(result.ok).toBe(true);

    expect(a.data.inventoryByVariantId.get(SHOPLISEUM_ID)?.quantity_available).toBe(0);
    expect(b.data.inventoryByVariantId.get(SHOPLISEUM_ID)?.quantity_available).toBe(2);
    expect(base.data.inventoryByVariantId.get(SHOPLISEUM_ID)?.quantity_available).toBe(2);
    expect(fixture().inventoryByVariantId.get(SHOPLISEUM_ID)?.quantity_available).toBe(2);
    expect(a.listOrders()).toHaveLength(7);
    expect(b.listOrders()).toHaveLength(6);
    expect(b.carts.list()).toHaveLength(0);
  });
});

describe('ShopState - placeOrder', () => {
  it('converts the cart into a PAID order, decrements stock, and drops the cart', () => {
    const state = new ShopState(fixture(), 'ep');
    const input = checkout(state, [
      { merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 },
      { merchandiseId: AISLEARENA_VARIANT, quantity: 1 },
    ]);
    const result = state.placeOrder(input);
    if (!result.ok) throw new Error('expected order');

    expect(result.order.financialStatus).toBe('PAID');
    expect(result.order.fulfillmentStatus).toBe('UNFULFILLED');
    expect(result.order.lineItems.map((l) => l.title)).toEqual([
      'Shopliseum Mushroom Dog Toys - Red Mushroom',
      'AisleArena Anti Tick Collar - Blue',
    ]);
    // 99.98 clears the 75.00 free-shipping threshold; fixture tax rate is 0.
    expect(result.order.subtotalPrice).toBe('99.98');
    expect(result.order.totalShippingPrice).toBe('0.00');
    expect(result.order.totalPrice).toBe('99.98');
    expect(state.data.inventoryByVariantId.get(SHOPLISEUM_ID)?.quantity_available).toBe(1);
    expect(state.carts.get(input.cart.id)).toBeUndefined();
    expect(state.inventoryDeltas()).toEqual([
      { variantId: SHOPLISEUM_ID, baseQuantityAvailable: 2, quantityAvailable: 1 },
    ]);
  });

  it('charges the chosen shipping method below the threshold', () => {
    const state = new ShopState(fixture(), 'ep');
    const result = state.placeOrder(
      checkout(state, [{ merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 }], 'express'),
    );
    if (!result.ok) throw new Error('expected order');
    expect(result.order.shippingMethod).toBe('express');
    expect(result.order.totalShippingPrice).toBe('19.99');
    expect(result.order.totalPrice).toBe('39.98');
  });

  it('rejects the whole order on a stock shortfall and leaves state untouched', () => {
    const state = new ShopState(fixture(), 'ep');
    const input = checkout(state, [
      { merchandiseId: SHOPLISEUM_VARIANT, quantity: 3 },
      { merchandiseId: AISLEARENA_VARIANT, quantity: 1 },
    ]);
    const result = state.placeOrder(input);
    expect(result).toEqual({
      ok: false,
      shortfalls: [{ merchandiseId: SHOPLISEUM_VARIANT, requested: 3, available: 2 }],
    });
    expect(state.data.inventoryByVariantId.get(SHOPLISEUM_ID)?.quantity_available).toBe(2);
    expect(state.carts.get(input.cart.id)).toBeDefined();
    expect(state.listOrders()).toHaveLength(6);
  });

  it('treats an untracked variant flagged unavailable as out of stock', () => {
    const state = new ShopState(fixture(), 'ep');
    const result = state.placeOrder(
      checkout(state, [{ merchandiseId: CARTANVIL_VARIANT, quantity: 1 }]),
    );
    expect(result).toEqual({
      ok: false,
      shortfalls: [{ merchandiseId: CARTANVIL_VARIANT, requested: 1, available: 0 }],
    });
  });

  it('records the cart customer on the order', () => {
    const state = new ShopState(fixture(), 'ep');
    const input = checkout(state, [{ merchandiseId: AISLEARENA_VARIANT, quantity: 1 }]);
    state.carts.setCustomer(input.cart, { id: 1, email: 'jane.doe@example.com' });
    const result = state.placeOrder(input);
    expect(result.ok && result.order.customerId).toBe(1);
    expect(state.ordersForCustomer(1)).toHaveLength(2);
  });
});

describe('ShopState - sessions', () => {
  it('mints, resolves, and revokes access tokens', () => {
    const state = new ShopState(fixture(), 'ep');
    const session = state.createSession(1);
    expect(state.resolveSession(session.accessToken)?.id).toBe(1);
    expect(state.deleteSession(session.accessToken)).toEqual(session);
    expect(state.resolveSession(session.accessToken)).toBeUndefined();
    expect(state.deleteSession(session.accessToken)).toBeUndefined();
  });
});
