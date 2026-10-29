/**
 * Checkout domain resolvers (sandbox-only): `Query.commerceSettings` exposes
 * the `commerce.json` rules; `Mutation.checkoutComplete` converts a cart into
 * an order through `ShopState.placeOrder`.
 *
 * Validation order: cart exists and is non-empty, shipping / payment handles
 * resolve, the address has the required lines, an email is known; then the
 * state checks stock atomically. The cart is untouched on any error.
 */

import type { MutationCheckoutCompleteArgs } from '../__generated__/resolvers-types.js';
import type { Commerce, PaymentMethod, ShippingMethod } from '../data/types.js';
import type { NewAddress } from '../state/shop_state.js';
import { type MoneyV2Node, buildMoneyV2 } from './builders.js';
import { REQUIRED_ADDRESS_FIELDS } from './customer.js';
import type { ResolverContext } from './index.js';
import { type OrderNode, buildOrderNode } from './order.js';

// ── Node shapes ───────────────────────────────────────────────────────────

export interface CommerceSettingsNode {
  readonly currencyCode: string;
  readonly taxRate: number;
  readonly freeShippingThreshold: MoneyV2Node | null;
  readonly shippingMethods: readonly {
    readonly handle: string;
    readonly title: string;
    readonly price: MoneyV2Node;
  }[];
  readonly paymentMethods: readonly PaymentMethod[];
}

export interface CheckoutUserErrorNode {
  readonly code: string | null;
  readonly field: readonly string[] | null;
  readonly message: string;
}

export interface CheckoutCompletePayloadNode {
  readonly order: OrderNode | null;
  readonly userErrors: readonly CheckoutUserErrorNode[];
}

// ── Resolvers ─────────────────────────────────────────────────────────────

export const checkoutResolvers = {
  Query: {
    commerceSettings: (
      _parent: unknown,
      _args: unknown,
      ctx: ResolverContext,
    ): CommerceSettingsNode =>
      buildCommerceSettings(ctx.data.commerce, ctx.data.store.currency_code),
  },

  Mutation: {
    checkoutComplete: (
      _parent: unknown,
      args: MutationCheckoutCompleteArgs,
      ctx: ResolverContext,
    ): CheckoutCompletePayloadNode => {
      const cart = ctx.carts.get(args.cartId);
      if (cart === undefined) return failure('INVALID', ['cartId'], 'Cart not found');
      if (cart.lines.length === 0) return failure('EMPTY', ['cartId'], 'Cart is empty');

      const { commerce } = ctx.data;
      const { input } = args;
      const shippingMethod = pickMethod(commerce.shipping_methods, input.shippingMethodHandle);
      if (shippingMethod === undefined) {
        return failure('INVALID', ['input', 'shippingMethodHandle'], 'Unknown shipping method');
      }
      const paymentMethod = pickMethod(commerce.payment_methods, input.paymentMethodHandle);
      if (paymentMethod === undefined) {
        return failure('INVALID', ['input', 'paymentMethodHandle'], 'Unknown payment method');
      }

      const addressErrors = REQUIRED_ADDRESS_FIELDS.filter(
        (field) => (input.shippingAddress[field] ?? '').trim() === '',
      ).map(
        (field): CheckoutUserErrorNode => ({
          code: 'BLANK',
          field: ['input', 'shippingAddress', field],
          message: `Shipping address ${field} can't be blank`,
        }),
      );
      if (addressErrors.length > 0) return { order: null, userErrors: addressErrors };

      const customer =
        cart.buyerIdentity.customerId === null
          ? undefined
          : ctx.state.getCustomer(cart.buyerIdentity.customerId);
      const email = input.email ?? cart.buyerIdentity.email ?? customer?.email ?? null;
      if (email === null)
        return failure('BLANK', ['input', 'email'], 'An email address is required');

      const result = ctx.state.placeOrder({
        cart,
        email,
        shippingAddress: toNewAddress(input.shippingAddress, ctx.data.store.country_code),
        shippingMethod,
        paymentMethod,
      });
      if (!result.ok) {
        return {
          order: null,
          userErrors: result.shortfalls.map((s) => ({
            code: 'INSUFFICIENT_STOCK',
            field: ['cartId'],
            message: `Only ${s.available} of ${s.requested} available for ${s.merchandiseId}`,
          })),
        };
      }
      return { order: buildOrderNode(result.order, ctx), userErrors: [] };
    },
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────

function buildCommerceSettings(commerce: Commerce, currency: string): CommerceSettingsNode {
  return {
    currencyCode: currency,
    taxRate: commerce.tax_rate,
    freeShippingThreshold:
      commerce.free_shipping_threshold === null
        ? null
        : buildMoneyV2(commerce.free_shipping_threshold, currency),
    shippingMethods: commerce.shipping_methods.map((m) => ({
      handle: m.handle,
      title: m.title,
      price: buildMoneyV2(m.price, currency),
    })),
    paymentMethods: commerce.payment_methods,
  };
}

/** Method matching `handle`, or the first one when `handle` is omitted. */
function pickMethod<T extends ShippingMethod | PaymentMethod>(
  methods: readonly T[],
  handle: string | null | undefined,
): T | undefined {
  if (handle === null || handle === undefined) return methods[0];
  return methods.find((m) => m.handle === handle);
}

function toNewAddress(
  input: MutationCheckoutCompleteArgs['input']['shippingAddress'],
  defaultCountryCode: string,
): NewAddress {
  return {
    firstName: input.firstName ?? null,
    lastName: input.lastName ?? null,
    company: input.company ?? null,
    address1: input.address1 ?? '',
    address2: input.address2 ?? null,
    city: input.city ?? '',
    province: input.province ?? null,
    provinceCode: null,
    country: input.country ?? '',
    countryCode: defaultCountryCode,
    zip: input.zip ?? '',
    phone: input.phone ?? null,
  };
}

function failure(
  code: string,
  field: readonly string[],
  message: string,
): CheckoutCompletePayloadNode {
  return { order: null, userErrors: [{ code, field, message }] };
}
