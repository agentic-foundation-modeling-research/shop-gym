import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { ShopState } from '../state/shop_state.js';
import { exportSnapshot, stateSnapshotSchema } from './snapshot.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const SHOPLISEUM_VARIANT = 'gid://shopify/ProductVariant/47242666836142';

const data = loadShopData(FIXTURE_DIR);

describe('exportSnapshot', () => {
  it('describes a fresh episode with GID ids and no inventory deltas', () => {
    const snapshot = exportSnapshot(new ShopState(data, 'ep'));
    expect(stateSnapshotSchema.safeParse(snapshot).success).toBe(true);
    expect(snapshot.episodeId).toBe('ep');
    expect(snapshot.now).toBe('2026-01-01T00:00:00.000Z');
    expect(snapshot.customers.map((c) => c.id)).toEqual(['gid://shopify/Customer/1']);
    expect(snapshot.customers[0]?.defaultAddressId).toBe('gid://shopify/MailingAddress/1');
    expect(snapshot.orders.map((o) => [o.id, o.name])).toEqual([
      ['gid://shopify/Order/1001', '#1001'],
    ]);
    expect(snapshot.sessions).toEqual([]);
    expect(snapshot.carts).toEqual([]);
    expect(snapshot.inventory).toEqual([]);
  });

  it('reflects carts, sessions, orders, and inventory deltas after activity', () => {
    const state = new ShopState(data, 'ep');
    const session = state.createSession(1);
    const open = state.carts.create({
      lines: [{ merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 }],
    });
    state.carts.setCustomer(open, { id: 1, email: 'jane.doe@example.com' });
    const toBuy = state.carts.create({
      lines: [{ merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 }],
    });
    const method = state.data.commerce.shipping_methods[0];
    const payment = state.data.commerce.payment_methods[0];
    if (method === undefined || payment === undefined) throw new Error('fixture missing methods');
    state.placeOrder({
      cart: toBuy,
      email: 'guest@example.com',
      shippingAddress: {
        firstName: null,
        lastName: null,
        company: null,
        address1: '1 Main St',
        address2: null,
        city: 'Toronto',
        province: null,
        provinceCode: null,
        country: 'Canada',
        countryCode: 'CA',
        zip: 'M5V 1A1',
        phone: null,
      },
      shippingMethod: method,
      paymentMethod: payment,
    });

    const snapshot = exportSnapshot(state);
    expect(snapshot.sessions).toEqual([
      {
        accessToken: session.accessToken,
        customerId: 'gid://shopify/Customer/1',
        expiresAt: session.expiresAt,
      },
    ]);
    expect(snapshot.carts).toEqual([
      {
        id: open.id,
        customerId: 'gid://shopify/Customer/1',
        email: 'jane.doe@example.com',
        lines: [{ id: open.lines[0]?.id, merchandiseId: SHOPLISEUM_VARIANT, quantity: 1 }],
        discountCodes: [],
        appliedDiscountCode: null,
        note: '',
      },
    ]);
    expect(snapshot.orders.map((o) => o.id)).toEqual([
      'gid://shopify/Order/1001',
      'gid://shopify/Order/1002',
    ]);
    expect(snapshot.orders[1]?.customerId).toBeNull();
    expect(snapshot.inventory).toEqual([
      { variantId: SHOPLISEUM_VARIANT, baseQuantityAvailable: 2, quantityAvailable: 1 },
    ]);
  });
});
