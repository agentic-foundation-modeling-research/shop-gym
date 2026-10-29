/**
 * Checkout pricing rules driven by `commerce.json`.
 *
 * A Discount code applies when it matches a `discount_codes` entry in any
 * case and the merchandise subtotal reaches its minimum. A percent or fixed
 * code lowers the subtotal, never below zero; a free-shipping code waives
 * the shipping charge. Tax is a flat fraction of the subtotal after the
 * discount. Shipping is the chosen method's flat rate, waived when
 * `free_shipping_threshold` is set and the subtotal before the discount
 * reaches it. Totals are computed in integer cents.
 */

import type { Commerce, DiscountCode, ShippingMethod } from '../data/types.js';
import { fromCents, toCents } from './money.js';

/** Priced line: unit price as a decimal string times quantity. */
export interface PricedLine {
  readonly price: string;
  readonly quantity: number;
}

/** Money breakdown of an order, every amount a two-decimal string. */
export interface OrderTotals {
  /** Merchandise subtotal before the discount. */
  readonly subtotalPrice: string;
  readonly totalShippingPrice: string;
  readonly totalTax: string;
  readonly totalPrice: string;
  /** Applied Discount code in its `commerce.json` spelling, or `null`. */
  readonly discountCode: string | null;
  /** Merchandise discount, or the shipping charge waived by a free-shipping code. */
  readonly discountAmount: string;
}

/** A Discount code that applies to a cart. */
export interface AppliedDiscount {
  readonly discountCode: DiscountCode;
  /** Cents taken off the merchandise subtotal; 0 for a free-shipping code. */
  readonly subtotalDiscount: number;
}

/** Sum `price * quantity` over `lines`, in cents. */
export function subtotalCents(lines: readonly PricedLine[]): number {
  return lines.reduce((sum, line) => sum + toCents(line.price) * line.quantity, 0);
}

/** The `commerce.json` Discount code equal to `code` when case is ignored. */
export function findDiscountCode(code: string, commerce: Commerce): DiscountCode | undefined {
  const wanted = code.toUpperCase();
  return commerce.discount_codes.find((entry) => entry.code.toUpperCase() === wanted);
}

/**
 * What `code` does to a cart whose merchandise subtotal is `subtotal` cents,
 * or `null` when the code is unknown or the subtotal is below its minimum.
 */
export function applyDiscountCode(
  code: string,
  subtotal: number,
  commerce: Commerce,
): AppliedDiscount | null {
  const discountCode = findDiscountCode(code, commerce);
  if (discountCode === undefined) return null;
  const minimum = discountCode.minimum_subtotal;
  if (minimum !== null && subtotal < toCents(minimum)) return null;
  return { discountCode, subtotalDiscount: subtotalDiscountCents(discountCode, subtotal) };
}

function subtotalDiscountCents(discountCode: DiscountCode, subtotal: number): number {
  switch (discountCode.kind) {
    case 'percentage':
      return Math.min(
        subtotal,
        Math.round((subtotal * Number.parseFloat(discountCode.amount)) / 100),
      );
    case 'fixed_amount':
      return Math.min(subtotal, toCents(discountCode.amount));
    case 'free_shipping':
      return 0;
  }
}

/** Tax owed on `subtotal` cents at `commerce.tax_rate`, rounded to the cent. */
export function taxCents(subtotal: number, commerce: Commerce): number {
  return Math.round(subtotal * commerce.tax_rate);
}

/** Shipping charge for `subtotal` cents with `method`, honoring the free-shipping threshold. */
export function shippingCents(
  subtotal: number,
  method: ShippingMethod,
  commerce: Commerce,
): number {
  const threshold = commerce.free_shipping_threshold;
  if (threshold !== null && subtotal >= toCents(threshold)) return 0;
  return toCents(method.price);
}

/**
 * Full order breakdown for `lines` shipped with `method` under `commerce`,
 * with `discountCode` applied when it applies.
 */
export function computeOrderTotals(
  lines: readonly PricedLine[],
  method: ShippingMethod,
  commerce: Commerce,
  discountCode: string | null,
): OrderTotals {
  const subtotal = subtotalCents(lines);
  const discount =
    discountCode === null ? null : applyDiscountCode(discountCode, subtotal, commerce);
  const subtotalDiscount = discount?.subtotalDiscount ?? 0;
  const methodShipping = shippingCents(subtotal, method, commerce);
  const freeShipping = discount?.discountCode.kind === 'free_shipping';
  const shipping = freeShipping ? 0 : methodShipping;
  const tax = taxCents(subtotal - subtotalDiscount, commerce);
  return {
    subtotalPrice: fromCents(subtotal),
    totalShippingPrice: fromCents(shipping),
    totalTax: fromCents(tax),
    totalPrice: fromCents(subtotal - subtotalDiscount + shipping + tax),
    discountCode: discount?.discountCode.code ?? null,
    discountAmount: fromCents(freeShipping ? methodShipping : subtotalDiscount),
  };
}
