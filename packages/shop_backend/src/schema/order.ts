/**
 * Order domain. `Order` and `Customer.orders` follow the Storefront API;
 * `Query.order(id)` is sandbox-only because Shopify exposes orders only
 * through the authenticated customer.
 */

export const orderTypeDefs = /* GraphQL */ `
  type Query {
    """Look up any order by id, regardless of customer."""
    order(id: ID!): Order @sandbox(reason: "Shopify exposes orders only via Customer.orders")
  }

  type Order {
    id: ID!
    """Human-readable order name, e.g. "#1001"."""
    name: String!
    orderNumber: Int!
    email: String
    processedAt: String!
    financialStatus: OrderFinancialStatus
    fulfillmentStatus: OrderFulfillmentStatus!
    currencyCode: String!
    subtotalPrice: MoneyV2
    totalShippingPrice: MoneyV2!
    totalTax: MoneyV2
    totalPrice: MoneyV2!
    shippingAddress: MailingAddress
    lineItems(first: Int): OrderLineItemConnection!
    """Handle of the commerce.json shipping method chosen at checkout."""
    shippingMethod: String @sandbox
    """Handle of the commerce.json payment method chosen at checkout."""
    paymentMethod: String @sandbox
  }

  type OrderLineItem {
    title: String!
    quantity: Int!
    variant: ProductVariant
    originalTotalPrice: MoneyV2!
  }

  type OrderLineItemConnection {
    nodes: [OrderLineItem!]!
    edges: [OrderLineItemEdge!]!
  }

  type OrderLineItemEdge {
    node: OrderLineItem!
  }

  type OrderConnection {
    nodes: [Order!]!
    edges: [OrderEdge!]!
    totalCount: Int!
  }

  type OrderEdge {
    node: Order!
  }

  enum OrderSortKeys {
    ID
    PROCESSED_AT
    TOTAL_PRICE
  }

  enum OrderFinancialStatus {
    AUTHORIZED
    PAID
    PARTIALLY_PAID
    PARTIALLY_REFUNDED
    PENDING
    REFUNDED
    VOIDED
  }

  enum OrderFulfillmentStatus {
    FULFILLED
    IN_PROGRESS
    ON_HOLD
    OPEN
    PARTIALLY_FULFILLED
    PENDING_FULFILLMENT
    RESTOCKED
    SCHEDULED
    UNFULFILLED
  }
`;
