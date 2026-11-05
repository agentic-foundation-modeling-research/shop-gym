/**
 * Cart domain: cart query and the cart mutation family. `CartBuyerIdentity.customer`
 * resolves once `cartBuyerIdentityUpdate` is called with a valid access token.
 * `Cart.discountAllocations` holds one `CartCodeDiscountAllocation` while the
 * cart's Discount code applies.
 */

export const cartTypeDefs = /* GraphQL */ `
  type Query {
    cart(id: ID!): Cart
  }

  type Mutation {
    cartCreate(input: CartInput!): CartCreatePayload!
    cartLinesAdd(cartId: ID!, lines: [CartLineInput!]!): CartLinesAddPayload!
    cartLinesUpdate(cartId: ID!, lines: [CartLineUpdateInput!]!): CartLinesUpdatePayload!
    cartLinesRemove(cartId: ID!, lineIds: [ID!]!): CartLinesRemovePayload!
    cartDiscountCodesUpdate(cartId: ID!, discountCodes: [String!]): CartDiscountCodesUpdatePayload!
    cartBuyerIdentityUpdate(cartId: ID!, buyerIdentity: CartBuyerIdentityInput!): CartBuyerIdentityUpdatePayload!
    cartNoteUpdate(cartId: ID!, note: String!): CartNoteUpdatePayload!
    cartAttributesUpdate(cartId: ID!, attributes: [AttributeInput!]!): CartAttributesUpdatePayload!
    cartGiftCardCodesUpdate(cartId: ID!, giftCardCodes: [String!]!): CartGiftCardCodesUpdatePayload!
    cartGiftCardCodesAdd(cartId: ID!, giftCardCodes: [String!]!): CartGiftCardCodesAddPayload!
    cartGiftCardCodesRemove(cartId: ID!, appliedGiftCardIds: [ID!]!): CartGiftCardCodesRemovePayload!
  }

  type Cart {
    id: ID!
    checkoutUrl: String!
    totalQuantity: Int!
    updatedAt: String!
    cost: CartCost!
    lines(first: Int): CartLineConnection!
    attributes: [Attribute!]!
    discountCodes: [CartDiscountCode!]!
    discountAllocations: [CartDiscountAllocation!]!
    appliedGiftCards: [AppliedGiftCard!]!
    buyerIdentity: CartBuyerIdentity!
    note: String!
  }

  type CartCost {
    subtotalAmount: MoneyV2!
    totalAmount: MoneyV2!
    totalTaxAmount: MoneyV2
    totalDutyAmount: MoneyV2
  }

  union BaseCartLine = CartLine | ComponentizableCartLine

  type CartLineConnection {
    nodes: [BaseCartLine!]!
    edges: [CartLineEdge!]!
  }

  type CartLineEdge {
    node: BaseCartLine!
  }

  union Merchandise = ProductVariant

  type CartLine {
    id: ID!
    quantity: Int!
    attributes: [Attribute!]!
    cost: CartLineCost!
    merchandise: Merchandise!
    parentRelationship: CartLineParentRelationship
  }

  type CartLineParentRelationship {
    parent: CartLineParent
  }

  type CartLineParent {
    id: ID!
  }

  type ComponentizableCartLine {
    id: ID!
    quantity: Int!
    attributes: [Attribute!]!
    cost: CartLineCost!
    merchandise: Merchandise!
    lineComponents: [CartLine!]!
  }

  type CartLineCost {
    amountPerQuantity: MoneyV2!
    compareAtAmountPerQuantity: MoneyV2
    totalAmount: MoneyV2!
    subtotalAmount: MoneyV2!
  }

  type CartDiscountCode {
    code: String!
    applicable: Boolean!
  }

  interface CartDiscountAllocation {
    discountedAmount: MoneyV2!
    targetType: DiscountApplicationTargetType!
  }

  type CartCodeDiscountAllocation implements CartDiscountAllocation {
    code: String!
    discountedAmount: MoneyV2!
    targetType: DiscountApplicationTargetType!
  }

  enum DiscountApplicationTargetType {
    LINE_ITEM
    SHIPPING_LINE
  }

  type AppliedGiftCard {
    id: ID!
    lastCharacters: String
    amountUsed: MoneyV2
  }

  type CartBuyerIdentity {
    countryCode: String
    customer: Customer
    email: String
    phone: String
  }


  type Attribute {
    key: String!
    value: String!
  }

  input CartInput {
    lines: [CartLineInput!]
    discountCodes: [String!]
    giftCardCodes: [String!]
    attributes: [AttributeInput!]
    note: String
    buyerIdentity: CartBuyerIdentityInput
  }

  input CartLineInput {
    merchandiseId: ID!
    quantity: Int
    attributes: [AttributeInput!]
    sellingPlanId: ID
  }

  input CartLineUpdateInput {
    id: ID!
    quantity: Int
    merchandiseId: ID
    attributes: [AttributeInput!]
    sellingPlanId: ID
  }

  input AttributeInput {
    key: String!
    value: String!
  }

  input CartBuyerIdentityInput {
    countryCode: CountryCode
    email: String
    phone: String
    customerAccessToken: String
  }

  type CartCreatePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartLinesAddPayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartLinesUpdatePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartLinesRemovePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartDiscountCodesUpdatePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartBuyerIdentityUpdatePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartNoteUpdatePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartAttributesUpdatePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartGiftCardCodesUpdatePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartGiftCardCodesAddPayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartGiftCardCodesRemovePayload {
    cart: Cart
    userErrors: [CartUserError!]!
    warnings: [CartWarning!]!
  }

  type CartUserError {
    code: String
    field: [String!]
    message: String!
  }

  type CartWarning {
    code: String!
    message: String!
    target: String
  }
`;
