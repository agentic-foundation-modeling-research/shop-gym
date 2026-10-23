import { describe, expect, it } from 'vitest';

import type { Commerce } from '../data/types.js';
import { computeOrderTotals, shippingCents, taxCents } from './pricing.js';

const STANDARD = { handle: 'standard', title: 'Standard', price: '9.99' };

const COMMERCE: Commerce = {
  tax_rate: 0.13,
  free_shipping_threshold: '75.00',
  shipping_methods: [STANDARD],
  payment_methods: [{ handle: 'card', title: 'Card' }],
};

describe('taxCents', () => {
  it('rounds the flat-rate tax to the nearest cent', () => {
    // 19.99 * 0.13 = 2.5987 -> 2.60
    expect(taxCents(1999, COMMERCE)).toBe(260);
  });

  it('is zero when the dataset has no tax rate', () => {
    expect(taxCents(1999, { ...COMMERCE, tax_rate: 0 })).toBe(0);
  });
});

describe('shippingCents', () => {
  it('charges the method rate below the free-shipping threshold', () => {
    expect(shippingCents(7499, STANDARD, COMMERCE)).toBe(999);
  });

  it('waives shipping at or above the threshold', () => {
    expect(shippingCents(7500, STANDARD, COMMERCE)).toBe(0);
  });

  it('always charges when no threshold is configured', () => {
    expect(shippingCents(100_000, STANDARD, { ...COMMERCE, free_shipping_threshold: null })).toBe(
      999,
    );
  });
});

describe('computeOrderTotals', () => {
  it('breaks an order down into subtotal, shipping, tax, and total', () => {
    const totals = computeOrderTotals(
      [
        { price: '19.99', quantity: 2 },
        { price: '2.49', quantity: 1 },
      ],
      STANDARD,
      COMMERCE,
    );
    // subtotal 42.47, shipping 9.99, tax round(4247 * 0.13) = 5.52
    expect(totals).toEqual({
      subtotalPrice: '42.47',
      totalShippingPrice: '9.99',
      totalTax: '5.52',
      totalPrice: '57.98',
    });
  });
});
