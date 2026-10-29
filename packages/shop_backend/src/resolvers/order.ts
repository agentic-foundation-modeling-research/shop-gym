/**
 * Order domain resolvers: `Query.order(id)` (sandbox-only) and the shared
 * order materialization used by `Customer.orders` and `checkoutComplete`.
 *
 * Orders live in the episode `ShopState`; line items are re-joined to the
 * catalog through `variantsByGid` so clients can navigate back to products.
 * Lines whose variant has left the catalog keep their stored title and price
 * and resolve `variant` to null.
 */

import type {
  CustomerOrdersArgs,
  DiscountApplicationTargetType,
  OrderLineItemsArgs,
  QueryOrderArgs,
} from '../__generated__/resolvers-types.js';
import { fromCents, toCents } from '../state/money.js';
import { findDiscountCode } from '../state/pricing.js';
import type { OrderLineItemRecord, OrderRecord } from '../state/shop_state.js';
import {
  type MoneyV2Node,
  type ProductVariantNode,
  buildMoneyV2,
  buildProductVariantNode,
  gid,
} from './builders.js';
import { type MailingAddressNode, buildMailingAddressNode, sliceFirst } from './customer.js';
import type { ResolverContext } from './index.js';

// ── Node shapes ───────────────────────────────────────────────────────────

export interface OrderLineItemNode {
  readonly title: string;
  readonly quantity: number;
  readonly variant: ProductVariantNode | null;
  readonly originalTotalPrice: MoneyV2Node;
}

export interface OrderLineItemConnectionNode {
  readonly nodes: readonly OrderLineItemNode[];
  readonly edges: readonly { readonly node: OrderLineItemNode }[];
}

export interface OrderDiscountCodeNode {
  readonly code: string;
  readonly targetType: DiscountApplicationTargetType;
  readonly amount: MoneyV2Node;
}

export interface OrderNode {
  readonly id: string;
  readonly name: string;
  readonly orderNumber: number;
  readonly email: string | null;
  readonly processedAt: string;
  readonly financialStatus: OrderRecord['financialStatus'];
  readonly fulfillmentStatus: OrderRecord['fulfillmentStatus'];
  readonly currencyCode: string;
  readonly subtotalPrice: MoneyV2Node;
  readonly totalShippingPrice: MoneyV2Node;
  readonly totalTax: MoneyV2Node;
  readonly totalPrice: MoneyV2Node;
  readonly shippingAddress: MailingAddressNode | null;
  readonly shippingMethod: string | null;
  readonly paymentMethod: string | null;
  readonly discountCode: OrderDiscountCodeNode | null;
  /** Internal: all line items, sliced by `Order.lineItems(first)`. */
  readonly lineItemNodes: readonly OrderLineItemNode[];
}

export interface OrderConnectionNode {
  readonly nodes: readonly OrderNode[];
  readonly edges: readonly { readonly node: OrderNode }[];
  readonly totalCount: number;
}

// ── Builders ──────────────────────────────────────────────────────────────

export function buildOrderNode(order: OrderRecord, ctx: ResolverContext): OrderNode {
  const currency = order.currencyCode;
  return {
    id: gid('Order', order.id),
    name: `#${order.id}`,
    orderNumber: order.id,
    email: order.email,
    processedAt: order.processedAt,
    financialStatus: order.financialStatus,
    fulfillmentStatus: order.fulfillmentStatus,
    currencyCode: currency,
    subtotalPrice: buildMoneyV2(order.subtotalPrice, currency),
    totalShippingPrice: buildMoneyV2(order.totalShippingPrice, currency),
    totalTax: buildMoneyV2(order.totalTax, currency),
    totalPrice: buildMoneyV2(order.totalPrice, currency),
    shippingAddress:
      order.shippingAddress === null ? null : buildMailingAddressNode(order.shippingAddress),
    shippingMethod: order.shippingMethod,
    paymentMethod: order.paymentMethod,
    discountCode:
      order.discountCode === null
        ? null
        : {
            code: order.discountCode,
            // A seeded order may name a code that `commerce.json` no longer lists.
            targetType:
              findDiscountCode(order.discountCode, ctx.data.commerce)?.kind === 'free_shipping'
                ? 'SHIPPING_LINE'
                : 'LINE_ITEM',
            amount: buildMoneyV2(order.discountAmount, currency),
          },
    lineItemNodes: order.lineItems.map((line) => buildOrderLineItemNode(line, currency, ctx)),
  };
}

function buildOrderLineItemNode(
  line: OrderLineItemRecord,
  currency: string,
  ctx: ResolverContext,
): OrderLineItemNode {
  const lookup = ctx.data.variantsByGid.get(gid('ProductVariant', line.variantId));
  return {
    title: line.title,
    quantity: line.quantity,
    variant:
      lookup === undefined
        ? null
        : buildProductVariantNode(
            lookup.product,
            lookup.variant,
            ctx.data.store,
            ctx.baseUrl,
            ctx.data.inventoryByVariantId,
            ctx.imageUrlMode,
          ),
    originalTotalPrice: buildMoneyV2(fromCents(toCents(line.price) * line.quantity), currency),
  };
}

/** Sort, slice, and materialize `orders` per the `Customer.orders` arguments. */
export function buildOrderConnection(
  orders: readonly OrderRecord[],
  args: CustomerOrdersArgs,
  ctx: ResolverContext,
): OrderConnectionNode {
  const sorted = [...orders].sort(comparatorFor(args.sortKey ?? 'ID'));
  if (args.reverse === true) sorted.reverse();
  const nodes = sliceFirst(sorted, args.first).map((order) => buildOrderNode(order, ctx));
  return { nodes, edges: nodes.map((node) => ({ node })), totalCount: orders.length };
}

function comparatorFor(sortKey: NonNullable<CustomerOrdersArgs['sortKey']>) {
  return (a: OrderRecord, b: OrderRecord): number => {
    switch (sortKey) {
      case 'PROCESSED_AT':
        return a.processedAt.localeCompare(b.processedAt) || a.id - b.id;
      case 'TOTAL_PRICE':
        return toCents(a.totalPrice) - toCents(b.totalPrice) || a.id - b.id;
      case 'ID':
        return a.id - b.id;
    }
  };
}

/** Numeric order id from `gid://shopify/Order/<n>`, or null when malformed. */
export function parseOrderGid(id: string): number | null {
  const match = /^gid:\/\/shopify\/Order\/(\d+)$/.exec(id);
  return match === null ? null : Number.parseInt(match[1] ?? '', 10);
}

// ── Resolvers ─────────────────────────────────────────────────────────────

export const orderResolvers = {
  Query: {
    order: (_parent: unknown, args: QueryOrderArgs, ctx: ResolverContext): OrderNode | null => {
      const id = parseOrderGid(args.id);
      if (id === null) return null;
      const order = ctx.state.getOrder(id);
      return order === undefined ? null : buildOrderNode(order, ctx);
    },
  },

  Order: {
    lineItems: (parent: OrderNode, args: OrderLineItemsArgs): OrderLineItemConnectionNode => {
      const slice = sliceFirst(parent.lineItemNodes, args.first);
      return { nodes: slice, edges: slice.map((node) => ({ node })) };
    },
  },
};
