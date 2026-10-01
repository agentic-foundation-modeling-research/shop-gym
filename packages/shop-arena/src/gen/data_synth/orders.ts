/**
 * `synth_orders`: one to three historical orders per seeded customer, drawn
 * deterministically from the catalog so no LLM call is needed. Totals
 * follow the `commerce.json` rules the backend applies at checkout.
 */

import type { z } from 'zod';

import type { datasetSchema } from '@shop-gym/shop-backend';

import { fromCents, seededRandom, toCents } from './ids.js';

type Customer = z.infer<typeof datasetSchema.customerSchema>;
type Product = z.infer<typeof datasetSchema.productSchema>;
type Commerce = z.infer<typeof datasetSchema.commerceSchema>;
export type Order = z.infer<typeof datasetSchema.orderSchema>;

const FIRST_ORDER_ID = 1001;
const MAX_ORDERS_PER_CUSTOMER = 3;
const MAX_LINES_PER_ORDER = 3;

interface Sellable {
  readonly variantId: number;
  readonly title: string;
  readonly price: string;
}

function sellables(products: readonly Product[]): Sellable[] {
  return products.flatMap((p) =>
    p.variants
      .filter((v) => v.available)
      .map((v) => ({ variantId: v.id, title: `${p.title} - ${v.title}`, price: v.price })),
  );
}

export function synthOrders(
  customers: readonly Customer[],
  products: readonly Product[],
  commerce: Commerce,
  currencyCode: string,
): Order[] {
  const pool = sellables(products);
  if (pool.length === 0) return [];
  const shipping = commerce.shipping_methods[0];
  const payment = commerce.payment_methods[0];
  const threshold =
    commerce.free_shipping_threshold === null ? null : toCents(commerce.free_shipping_threshold);
  const orders: Order[] = [];
  for (const customer of customers) {
    const rng = seededRandom(`orders\0${customer.email}`);
    const count = 1 + Math.floor(rng() * MAX_ORDERS_PER_CUSTOMER);
    for (let k = 0; k < count; k += 1) {
      const lineCount = 1 + Math.floor(rng() * MAX_LINES_PER_ORDER);
      const picked = new Map<number, Sellable>();
      while (picked.size < Math.min(lineCount, pool.length)) {
        const s = pool[Math.floor(rng() * pool.length)] as Sellable;
        picked.set(s.variantId, s);
      }
      const lineItems = [...picked.values()].map((s) => ({
        variant_id: s.variantId,
        title: s.title,
        quantity: 1 + Math.floor(rng() * 2),
        price: s.price,
      }));
      const subtotal = lineItems.reduce((sum, li) => sum + toCents(li.price) * li.quantity, 0);
      const shippingCents =
        shipping === undefined || (threshold !== null && subtotal >= threshold)
          ? 0
          : toCents(shipping.price);
      const tax = Math.round(subtotal * commerce.tax_rate);
      const month = String(1 + Math.floor(rng() * 12)).padStart(2, '0');
      const day = String(1 + Math.floor(rng() * 28)).padStart(2, '0');
      orders.push({
        id: FIRST_ORDER_ID + orders.length,
        customer_id: customer.id,
        email: customer.email,
        processed_at: `2024-${month}-${day}T10:00:00Z`,
        financial_status: 'PAID',
        fulfillment_status: 'FULFILLED',
        currency_code: currencyCode,
        line_items: lineItems,
        shipping_address: customer.addresses[0] ?? null,
        shipping_method: shipping?.handle ?? null,
        payment_method: payment?.handle ?? null,
        subtotal_price: fromCents(subtotal),
        total_shipping_price: fromCents(shippingCents),
        total_tax: fromCents(tax),
        total_price: fromCents(subtotal + shippingCents + tax),
      });
    }
  }
  return orders.sort((a, b) => a.processed_at.localeCompare(b.processed_at) || a.id - b.id);
}
