/**
 * Customer domain: accounts, access tokens, and addresses. Shapes follow the
 * Storefront API (`customerCreate`, `customerAccessTokenCreate`,
 * `customerAccessTokenDelete`, `customer(customerAccessToken)`).
 */

export const customerTypeDefs = /* GraphQL */ `
  type Query {
    customer(customerAccessToken: String!): Customer
  }

  type Mutation {
    customerCreate(input: CustomerCreateInput!): CustomerCreatePayload!
    customerAccessTokenCreate(input: CustomerAccessTokenCreateInput!): CustomerAccessTokenCreatePayload!
    customerAccessTokenDelete(customerAccessToken: String!): CustomerAccessTokenDeletePayload!
  }

  type Customer {
    id: ID!
    email: String
    firstName: String
    lastName: String
    displayName: String!
    phone: String
    acceptsMarketing: Boolean!
    createdAt: String!
    updatedAt: String!
    defaultAddress: MailingAddress
    addresses(first: Int): MailingAddressConnection!
    numberOfOrders: Int!
    orders(first: Int, reverse: Boolean, sortKey: OrderSortKeys): OrderConnection!
  }

  type MailingAddress {
    id: ID!
    firstName: String
    lastName: String
    name: String
    company: String
    address1: String
    address2: String
    city: String
    province: String
    provinceCode: String
    country: String
    countryCodeV2: String
    zip: String
    phone: String
    formatted: [String!]!
  }

  type MailingAddressConnection {
    nodes: [MailingAddress!]!
    edges: [MailingAddressEdge!]!
  }

  type MailingAddressEdge {
    node: MailingAddress!
  }

  input MailingAddressInput {
    firstName: String
    lastName: String
    company: String
    address1: String
    address2: String
    city: String
    province: String
    country: String
    zip: String
    phone: String
  }

  input CustomerCreateInput {
    email: String!
    password: String!
    firstName: String
    lastName: String
    phone: String
    acceptsMarketing: Boolean
  }

  input CustomerAccessTokenCreateInput {
    email: String!
    password: String!
  }

  type CustomerAccessToken {
    accessToken: String!
    expiresAt: String!
  }

  type CustomerCreatePayload {
    customer: Customer
    customerUserErrors: [CustomerUserError!]!
  }

  type CustomerAccessTokenCreatePayload {
    customerAccessToken: CustomerAccessToken
    customerUserErrors: [CustomerUserError!]!
  }

  type CustomerAccessTokenDeletePayload {
    deletedAccessToken: String
    deletedCustomerAccessTokenId: String
    userErrors: [UserError!]!
  }

  type CustomerUserError {
    code: CustomerErrorCode
    field: [String!]
    message: String!
  }

  type UserError {
    field: [String!]
    message: String!
  }

  enum CustomerErrorCode {
    BLANK
    INVALID
    TAKEN
    TOO_SHORT
    UNIDENTIFIED_CUSTOMER
  }
`;
