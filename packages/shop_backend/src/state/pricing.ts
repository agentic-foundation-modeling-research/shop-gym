/**
 * Checkout pricing rules driven by `commerce.json`.
 *
 * Tax is a flat fraction of the merchandise subtotal. Shipping is the chosen
 * method's flat rate, waived when `free_shipping_threshold` is set and the
 * subtotal reaches it. Totals are computed in integer cents.
 */

import type { Commerce, ShippingMethod } from '../data/types.js';
import { fromCents, toCents } from './money.js';

/** Priced line: unit price as a decimal string times quantity. */
export interface PricedLine {
  readonly price: string;
  readonly quantity: number;
}

/** Money breakdown of an order, every amount a two-decimal string. */
export interface OrderTotals {
  readonly subtotalPrice: string;
  readonly totalShippingPrice: string;
  readonly totalTax: string;
  readonly totalPrice: string;
}

/** Sum `price * quantity` over `lines`, in cents. */
export function subtotalCents(lines: readonly PricedLine[]): number {
  return lines.reduce((sum, line) => sum + toCents(line.price) * line.quantity, 0);
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

/** Full order breakdown for `lines` shipped with `method` under `commerce`. */
export function computeOrderTotals(
  lines: readonly PricedLine[],
  method: ShippingMethod,
  commerce: Commerce,
): OrderTotals {
  const subtotal = subtotalCents(lines);
  const shipping = shippingCents(subtotal, method, commerce);
  const tax = taxCents(subtotal, commerce);
  return {
    subtotalPrice: fromCents(subtotal),
    totalShippingPrice: fromCents(shipping),
    totalTax: fromCents(tax),
    totalPrice: fromCents(subtotal + shipping + tax),
  };
}
