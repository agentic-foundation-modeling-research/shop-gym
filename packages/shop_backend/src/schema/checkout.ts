/**
 * Checkout domain (sandbox-only). Shopify completes checkout outside the
 * Storefront API, so `checkoutComplete` and `commerceSettings` carry
 * `@sandbox`. `checkoutComplete` turns a cart into an `Order` in one step:
 * it validates stock, prices the order from `commerce.json`, decrements
 * episode inventory, and removes the cart.
 */

export const checkoutTypeDefs = /* GraphQL */ `
  type Query {
    """Shipping and payment options plus tax rules from commerce.json."""
    commerceSettings: CommerceSettings! @sandbox
  }

  type Mutation {
    """Convert a cart into a paid, unfulfilled order."""
    checkoutComplete(cartId: ID!, input: CheckoutCompleteInput!): CheckoutCompletePayload! @sandbox
  }

  type CommerceSettings @sandbox {
    currencyCode: String!
    """Fraction of the merchandise subtotal charged as tax, e.g. 0.13."""
    taxRate: Float!
    freeShippingThreshold: MoneyV2
    shippingMethods: [ShippingMethod!]!
    paymentMethods: [PaymentMethod!]!
  }

  type ShippingMethod @sandbox {
    handle: String!
    title: String!
    price: MoneyV2!
  }

  type PaymentMethod @sandbox {
    handle: String!
    title: String!
  }

  input CheckoutCompleteInput @sandbox {
    """Contact email; defaults to the cart's buyer identity email."""
    email: String
    shippingAddress: MailingAddressInput!
    """Handle of a commerce.json shipping method; defaults to the first one."""
    shippingMethodHandle: String
    """Handle of a commerce.json payment method; defaults to the first one."""
    paymentMethodHandle: String
  }

  type CheckoutCompletePayload @sandbox {
    order: Order
    userErrors: [CheckoutUserError!]!
  }

  type CheckoutUserError @sandbox {
    code: String
    field: [String!]
    message: String!
  }
`;
