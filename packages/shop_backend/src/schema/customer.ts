/**
 * Customer domain: accounts, access tokens, and addresses. Shapes follow the
 * Storefront API (`customerCreate`, `customerAccessTokenCreate`,
 * `customerAccessTokenDelete`, `customer(customerAccessToken)`, and the
 * address book: `customerAddressCreate`, `customerAddressUpdate`,
 * `customerAddressDelete`, `customerDefaultAddressUpdate`).
 */

export const customerTypeDefs = /* GraphQL */ `
  type Query {
    customer(customerAccessToken: String!): Customer
  }

  type Mutation {
    customerCreate(input: CustomerCreateInput!): CustomerCreatePayload!
    customerAccessTokenCreate(input: CustomerAccessTokenCreateInput!): CustomerAccessTokenCreatePayload!
    customerAccessTokenDelete(customerAccessToken: String!): CustomerAccessTokenDeletePayload!
    customerAddressCreate(address: MailingAddressInput!, customerAccessToken: String!): CustomerAddressCreatePayload!
    customerAddressUpdate(address: MailingAddressInput!, customerAccessToken: String!, id: ID!): CustomerAddressUpdatePayload!
    customerAddressDelete(customerAccessToken: String!, id: ID!): CustomerAddressDeletePayload!
    customerDefaultAddressUpdate(addressId: ID!, customerAccessToken: String!): CustomerDefaultAddressUpdatePayload!
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

  type CustomerAddressCreatePayload {
    customerAddress: MailingAddress
    customerUserErrors: [CustomerUserError!]!
  }

  type CustomerAddressUpdatePayload {
    customerAddress: MailingAddress
    customerUserErrors: [CustomerUserError!]!
  }

  type CustomerAddressDeletePayload {
    deletedCustomerAddressId: String
    customerUserErrors: [CustomerUserError!]!
  }

  type CustomerDefaultAddressUpdatePayload {
    customer: Customer
    customerUserErrors: [CustomerUserError!]!
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
    NOT_FOUND
    TAKEN
    TOO_SHORT
    UNIDENTIFIED_CUSTOMER
  }
`;
