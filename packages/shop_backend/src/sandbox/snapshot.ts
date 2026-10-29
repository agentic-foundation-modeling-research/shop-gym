/**
 * `StateSnapshot`: the normalized, grader-facing view of one episode.
 *
 * Graders read only this shape (served by `GET /__shopgym/episodes/<id>/state`),
 * never `ShopState` internals, so backend edits that add collections or
 * rename fields cannot break grading as long as `exportSnapshot` still
 * produces a value accepted by `stateSnapshotSchema`.
 */

import { z } from 'zod';
import type { ShopState } from '../state/shop_state.js';

const money = z.string().regex(/^-?\d+\.\d{2}$/, 'expected a two-decimal money string');

export const snapshotAddressSchema = z.object({
  id: z.string(),
  firstName: z.string().nullable(),
  lastName: z.string().nullable(),
  company: z.string().nullable(),
  address1: z.string(),
  address2: z.string().nullable(),
  city: z.string(),
  province: z.string().nullable(),
  provinceCode: z.string().nullable(),
  country: z.string(),
  countryCode: z.string(),
  zip: z.string(),
  phone: z.string().nullable(),
});

export const snapshotCustomerSchema = z.object({
  id: z.string(),
  email: z.string(),
  firstName: z.string().nullable(),
  lastName: z.string().nullable(),
  phone: z.string().nullable(),
  acceptsMarketing: z.boolean(),
  createdAt: z.string(),
  defaultAddressId: z.string().nullable(),
  addresses: z.array(snapshotAddressSchema),
});

export const snapshotSessionSchema = z.object({
  accessToken: z.string(),
  customerId: z.string(),
  expiresAt: z.string(),
});

export const snapshotCartLineSchema = z.object({
  id: z.string(),
  merchandiseId: z.string(),
  quantity: z.number().int(),
});

export const snapshotCartSchema = z.object({
  id: z.string(),
  customerId: z.string().nullable(),
  email: z.string().nullable(),
  lines: z.array(snapshotCartLineSchema),
  /** Codes as stored; a cart holds at most one. */
  discountCodes: z.array(z.string()),
  /** The stored code when it applies to the cart now, else `null`. */
  appliedDiscountCode: z.string().nullable(),
  note: z.string(),
});

export const snapshotOrderLineItemSchema = z.object({
  variantId: z.string(),
  title: z.string(),
  quantity: z.number().int(),
  price: money,
});

export const snapshotOrderSchema = z.object({
  id: z.string(),
  name: z.string(),
  customerId: z.string().nullable(),
  email: z.string().nullable(),
  processedAt: z.string(),
  financialStatus: z.string(),
  fulfillmentStatus: z.string(),
  currencyCode: z.string(),
  lineItems: z.array(snapshotOrderLineItemSchema),
  shippingAddress: snapshotAddressSchema.nullable(),
  shippingMethod: z.string().nullable(),
  paymentMethod: z.string().nullable(),
  subtotalPrice: money,
  totalShippingPrice: money,
  totalTax: money,
  totalPrice: money,
  /** Discount code applied at checkout, or `null`. */
  discountCode: z.string().nullable(),
  /** Merchandise discount, or the shipping charge waived by a free-shipping code. */
  discountAmount: money,
});

export const snapshotInventoryDeltaSchema = z.object({
  variantId: z.string(),
  baseQuantityAvailable: z.number().int().nullable(),
  quantityAvailable: z.number().int().nullable(),
});

/** Full grader-facing view of one episode. */
export const stateSnapshotSchema = z.object({
  episodeId: z.string(),
  /** Episode clock reading at export time. */
  now: z.string(),
  customers: z.array(snapshotCustomerSchema),
  sessions: z.array(snapshotSessionSchema),
  carts: z.array(snapshotCartSchema),
  orders: z.array(snapshotOrderSchema),
  /** Only variants whose quantity differs from the loaded dataset. */
  inventory: z.array(snapshotInventoryDeltaSchema),
});

export type StateSnapshot = z.infer<typeof stateSnapshotSchema>;

const GID = 'gid://shopify';

/** Build the `StateSnapshot` for `state`. Output is validated before return. */
export function exportSnapshot(state: ShopState): StateSnapshot {
  const snapshot: StateSnapshot = {
    episodeId: state.episodeId,
    now: state.clock.now(),
    customers: state.listCustomers().map((customer) => ({
      id: `${GID}/Customer/${customer.id}`,
      email: customer.email,
      firstName: customer.firstName,
      lastName: customer.lastName,
      phone: customer.phone,
      acceptsMarketing: customer.acceptsMarketing,
      createdAt: customer.createdAt,
      defaultAddressId:
        customer.defaultAddressId === null
          ? null
          : `${GID}/MailingAddress/${customer.defaultAddressId}`,
      addresses: customer.addresses.map((address) => ({
        ...address,
        id: `${GID}/MailingAddress/${address.id}`,
      })),
    })),
    sessions: state.listSessions().map((session) => ({
      accessToken: session.accessToken,
      customerId: `${GID}/Customer/${session.customerId}`,
      expiresAt: session.expiresAt,
    })),
    carts: state.carts.list().map((cart) => ({
      id: cart.id,
      customerId:
        cart.buyerIdentity.customerId === null
          ? null
          : `${GID}/Customer/${cart.buyerIdentity.customerId}`,
      email: cart.buyerIdentity.email,
      lines: cart.lines.map((line) => ({
        id: line.id,
        merchandiseId: line.merchandiseId,
        quantity: line.quantity,
      })),
      discountCodes: [...cart.discountCodes],
      appliedDiscountCode: state.appliedDiscountCode(cart),
      note: cart.note,
    })),
    orders: state.listOrders().map((order) => ({
      id: `${GID}/Order/${order.id}`,
      name: `#${order.id}`,
      customerId: order.customerId === null ? null : `${GID}/Customer/${order.customerId}`,
      email: order.email,
      processedAt: order.processedAt,
      financialStatus: order.financialStatus,
      fulfillmentStatus: order.fulfillmentStatus,
      currencyCode: order.currencyCode,
      lineItems: order.lineItems.map((line) => ({
        variantId: `${GID}/ProductVariant/${line.variantId}`,
        title: line.title,
        quantity: line.quantity,
        price: line.price,
      })),
      shippingAddress:
        order.shippingAddress === null
          ? null
          : { ...order.shippingAddress, id: `${GID}/MailingAddress/${order.shippingAddress.id}` },
      shippingMethod: order.shippingMethod,
      paymentMethod: order.paymentMethod,
      subtotalPrice: order.subtotalPrice,
      totalShippingPrice: order.totalShippingPrice,
      totalTax: order.totalTax,
      totalPrice: order.totalPrice,
      discountCode: order.discountCode,
      discountAmount: order.discountAmount,
    })),
    inventory: state.inventoryDeltas().map((delta) => ({
      variantId: `${GID}/ProductVariant/${delta.variantId}`,
      baseQuantityAvailable: delta.baseQuantityAvailable,
      quantityAvailable: delta.quantityAvailable,
    })),
  };
  return stateSnapshotSchema.parse(snapshot);
}
