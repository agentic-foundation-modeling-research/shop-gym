import { describe, expect, it } from 'vitest';

import type { Commerce } from '../data/types.js';
import { computeOrderTotals, shippingCents, taxCents } from './pricing.js';

const STANDARD = { handle: 'standard', title: 'Standard', price: '9.99' };

const COMMERCE: Commerce = {
  tax_rate: 0.13,
  free_shipping_threshold: '75.00',
  shipping_methods: [STANDARD],
  payment_methods: [{ handle: 'card', title: 'Card' }],
  discount_codes: [
    { code: 'TENOFF', kind: 'percentage', amount: '10', minimum_subtotal: null, hint: '' },
    { code: 'BIG50', kind: 'fixed_amount', amount: '50.00', minimum_subtotal: null, hint: '' },
    { code: 'SHIPFREE', kind: 'free_shipping', amount: '0', minimum_subtotal: null, hint: '' },
  ],
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
      null,
    );
    // subtotal 42.47, shipping 9.99, tax round(4247 * 0.13) = 5.52
    expect(totals).toEqual({
      subtotalPrice: '42.47',
      totalShippingPrice: '9.99',
      totalTax: '5.52',
      totalPrice: '57.98',
      discountCode: null,
      discountAmount: '0.00',
    });
  });

  it('taxes the subtotal after a percent discount', () => {
    const totals = computeOrderTotals(
      [{ price: '20.00', quantity: 1 }],
      STANDARD,
      COMMERCE,
      'tenoff',
    );
    // 20.00 - 2.00 = 18.00, tax round(1800 * 0.13) = 2.34, shipping 9.99
    expect(totals).toEqual({
      subtotalPrice: '20.00',
      totalShippingPrice: '9.99',
      totalTax: '2.34',
      totalPrice: '30.33',
      discountCode: 'TENOFF',
      discountAmount: '2.00',
    });
  });

  it('never takes a fixed discount below a zero subtotal', () => {
    const totals = computeOrderTotals(
      [{ price: '20.00', quantity: 1 }],
      STANDARD,
      COMMERCE,
      'BIG50',
    );
    expect(totals).toMatchObject({
      totalTax: '0.00',
      totalPrice: '9.99',
      discountCode: 'BIG50',
      discountAmount: '20.00',
    });
  });

  it('checks the free-shipping threshold against the subtotal before the discount', () => {
    // 80.00 reaches the 75.00 threshold even though 72.00 after TENOFF does not.
    const totals = computeOrderTotals(
      [{ price: '80.00', quantity: 1 }],
      STANDARD,
      COMMERCE,
      'TENOFF',
    );
    expect(totals.totalShippingPrice).toBe('0.00');
  });

  it('applies a free-shipping code with amount 0 when shipping is already free', () => {
    const totals = computeOrderTotals(
      [{ price: '80.00', quantity: 1 }],
      STANDARD,
      COMMERCE,
      'SHIPFREE',
    );
    expect(totals).toMatchObject({
      totalShippingPrice: '0.00',
      discountCode: 'SHIPFREE',
      discountAmount: '0.00',
    });
  });
});
