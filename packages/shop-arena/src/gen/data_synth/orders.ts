/**
 * `synth_orders`: fifteen past orders for the Personas, drawn from the
 * catalog with a fixed seed so no LLM call is needed. The last Persona has
 * no orders and every other Persona has one to six. Orders fall in the
 * twelve months before the Episode clock starts, ship to one of the
 * Persona's saved addresses with a random shipping and payment method,
 * and cost what the backend charges at checkout. Four orders use a
 * Discount code that lowers their total, or fewer when no code lowers
 * that many orders.
 */

import type { z } from 'zod';

import {
  DEFAULT_EPISODE_START,
  computeOrderTotals,
  type datasetSchema,
} from '@shop-gym/shop-backend';

import { seededRandom } from './ids.js';

type Customer = z.infer<typeof datasetSchema.customerSchema>;
type Product = z.infer<typeof datasetSchema.productSchema>;
type Commerce = z.infer<typeof datasetSchema.commerceSchema>;
export type Order = z.infer<typeof datasetSchema.orderSchema>;
type Status = Pick<Order, 'financial_status' | 'fulfillment_status'>;

const SEED = 'orders';
const ORDER_COUNT = 15;
const MAX_ORDERS_PER_CUSTOMER = 6;
const MAX_LINES_PER_ORDER = 3;
const MAX_QUANTITY = 2;
const FIRST_ORDER_ID = 1001;
const DISCOUNTED_ORDER_COUNT = 4;
const MINUTE_MS = 60_000;
const HISTORY_MINUTES = 365 * 24 * 60;

const SHIPPED: Status = { financial_status: 'PAID', fulfillment_status: 'FULFILLED' };
const NOT_SHIPPED: Status = { financial_status: 'PAID', fulfillment_status: 'UNFULFILLED' };
const REFUNDED: Status = { financial_status: 'REFUNDED', fulfillment_status: 'FULFILLED' };
const PARTLY_REFUNDED: Status = {
  financial_status: 'PARTIALLY_REFUNDED',
  fulfillment_status: 'FULFILLED',
};
const PARTLY_SHIPPED: Status = {
  financial_status: 'PAID',
  fulfillment_status: 'PARTIALLY_FULFILLED',
};

interface Sellable {
  readonly variantId: number;
  readonly title: string;
  readonly price: string;
}

/** An order before it is numbered, given a status and priced. */
interface UnpricedOrder {
  readonly customer: Customer;
  readonly lineItems: Order['line_items'];
  readonly method: Commerce['shipping_methods'][number];
  readonly payment: Commerce['payment_methods'][number] | null;
  readonly address: Customer['addresses'][number] | null;
  readonly processedAt: string;
}

function sellables(products: readonly Product[]): Sellable[] {
  return products.flatMap((p) =>
    p.variants
      .filter((v) => v.available)
      .map((v) => ({ variantId: v.id, title: `${p.title} - ${v.title}`, price: v.price })),
  );
}

/** A uniformly random element of `items`, which must not be empty. */
function pick<T>(rng: () => number, items: readonly T[]): T {
  // The index is below `items.length`, so it names an element of a non-empty array.
  return items[Math.floor(rng() * items.length)] as T;
}

/** Removes a uniformly random element from `items` and returns it; `undefined` when empty. */
function takeRandom<T>(rng: () => number, items: T[]): T | undefined {
  return items.splice(Math.floor(rng() * items.length), 1)[0];
}

/** How many orders each customer but the last gets: one each, then the rest at random. */
function orderCounts(rng: () => number, buyers: number): number[] {
  const counts = Array.from({ length: buyers }, () => 1);
  const total = Math.min(ORDER_COUNT, buyers * MAX_ORDERS_PER_CUSTOMER);
  for (let placed = buyers; placed < total; placed += 1) {
    const open = counts.flatMap((count, i) => (count < MAX_ORDERS_PER_CUSTOMER ? [i] : []));
    const i = pick(rng, open);
    counts[i] = (counts[i] ?? 0) + 1;
  }
  return counts;
}

/**
 * Discount codes, by order index, for up to `DISCOUNTED_ORDER_COUNT`
 * random orders. Each picked order gets a random code that lowers its
 * total; an order that no code lowers is never picked.
 */
function pickDiscountCodes(
  rng: () => number,
  orders: readonly UnpricedOrder[],
  commerce: Commerce,
): Map<number, string> {
  const open = orders.flatMap((order, index) => {
    const lowers = (code: string): boolean =>
      Number(computeOrderTotals(order.lineItems, order.method, commerce, code).discountAmount) > 0;
    const codes = commerce.discount_codes.map((c) => c.code).filter(lowers);
    return codes.length > 0 ? [{ index, codes }] : [];
  });
  const picked = new Map<number, string>();
  while (picked.size < DISCOUNTED_ORDER_COUNT && open.length > 0) {
    const candidate = takeRandom(rng, open);
    if (candidate !== undefined) picked.set(candidate.index, pick(rng, candidate.codes));
  }
  return picked;
}

export function synthOrders(
  customers: readonly Customer[],
  products: readonly Product[],
  commerce: Commerce,
  currencyCode: string,
): Order[] {
  const pool = sellables(products);
  if (pool.length === 0 || commerce.shipping_methods.length === 0) return [];
  const rng = seededRandom(SEED);
  const buyers = customers.slice(0, -1);
  const counts = orderCounts(rng, buyers.length);
  const historyStart = Date.parse(DEFAULT_EPISODE_START) - HISTORY_MINUTES * MINUTE_MS;
  const drafts: UnpricedOrder[] = buyers.flatMap((customer, c) =>
    Array.from({ length: counts[c] ?? 0 }, () => {
      const lineCount = 1 + Math.floor(rng() * MAX_LINES_PER_ORDER);
      const picked = new Map<number, Sellable>();
      while (picked.size < Math.min(lineCount, pool.length)) {
        const s = pick(rng, pool);
        picked.set(s.variantId, s);
      }
      const lineItems = [...picked.values()].map((s) => ({
        variant_id: s.variantId,
        title: s.title,
        quantity: 1 + Math.floor(rng() * MAX_QUANTITY),
        price: s.price,
      }));
      const method = pick(rng, commerce.shipping_methods);
      const payment =
        commerce.payment_methods.length === 0 ? null : pick(rng, commerce.payment_methods);
      const address = customer.addresses.length === 0 ? null : pick(rng, customer.addresses);
      const minute = Math.floor(rng() * HISTORY_MINUTES);
      return {
        customer,
        lineItems,
        method,
        payment,
        address,
        processedAt: new Date(historyStart + minute * MINUTE_MS).toISOString(),
      };
    }),
  );
  drafts.sort((a, b) => a.processedAt.localeCompare(b.processedAt));
  // The newest order is not shipped yet. Three random older orders are
  // refunded, partly refunded and partly shipped; the rest are shipped.
  const statuses = new Map<number, Status>([[drafts.length - 1, NOT_SHIPPED]]);
  const older = drafts.slice(0, -1).map((_, i) => i);
  for (const status of [REFUNDED, PARTLY_REFUNDED, PARTLY_SHIPPED]) {
    const i = takeRandom(rng, older);
    if (i !== undefined) statuses.set(i, status);
  }
  const codes = pickDiscountCodes(rng, drafts, commerce);
  return drafts.map((draft, i) => {
    const totals = computeOrderTotals(
      draft.lineItems,
      draft.method,
      commerce,
      codes.get(i) ?? null,
    );
    return {
      id: FIRST_ORDER_ID + i,
      ...(statuses.get(i) ?? SHIPPED),
      customer_id: draft.customer.id,
      email: draft.customer.email,
      processed_at: draft.processedAt,
      currency_code: currencyCode,
      line_items: draft.lineItems,
      shipping_address: draft.address,
      shipping_method: draft.method.handle,
      payment_method: draft.payment?.handle ?? null,
      subtotal_price: totals.subtotalPrice,
      total_shipping_price: totals.totalShippingPrice,
      total_tax: totals.totalTax,
      total_price: totals.totalPrice,
      discount_code: totals.discountCode,
      discount_amount: totals.discountAmount,
    };
  });
}
