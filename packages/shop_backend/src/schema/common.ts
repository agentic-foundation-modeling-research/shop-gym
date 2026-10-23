/**
 * Shared scalar-ish types: images, money, SEO, pagination, metafields, and the
 * ISO code enums used across domains.
 */

export const commonTypeDefs = /* GraphQL */ `
  type Image {
    id: ID
    url: String!
    altText: String
    width: Int
    height: Int
  }

  type ImageConnection {
    nodes: [Image]!
    edges: [ImageEdge!]!
  }

  type ImageEdge {
    node: Image
  }

  type MoneyV2 {
    amount: String!
    currencyCode: String!
  }

  # ── Metafields ───────────────────────────────────────────────────────────

  type Metafield {
    id: ID!
    namespace: String!
    key: String!
    value: String!
    type: String!
    parentResource: MetafieldParentResource
    reference: MetafieldReference
  }

  union MetafieldParentResource = Product | Collection | ProductVariant
  union MetafieldReference = Product | Collection | Page

  input HasMetafieldsIdentifier {
    namespace: String!
    key: String!
  }

  type SEO {
    title: String
    description: String
  }

  type PageInfo {
    hasNextPage: Boolean!
    hasPreviousPage: Boolean!
    startCursor: String
    endCursor: String
  }


  enum CurrencyCode {
    USD
    CAD
    EUR
    GBP
    AUD
  }

  enum CountryCode {
    US
    CA
    GB
    AU
    DE
    FR
    ZZ
  }

  enum LanguageCode {
    EN
    FR
    DE
    ES
  }
`;
