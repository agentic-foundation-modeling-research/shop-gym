/**
 * Shop domain: shop metadata, policies, menus, and localization.
 */

export const shopTypeDefs = /* GraphQL */ `
  type Query {
    shop: Shop!
    menu(handle: String!): Menu
    localization: Localization!
  }

  # ── Shop ──────────────────────────────────────────────────────────────────

  type Shop {
    id: ID!
    name: String!
    description: String!
    primaryDomain: ShopDomain!
    brand: Brand
    paymentSettings: PaymentSettings!
    privacyPolicy: ShopPolicy
    shippingPolicy: ShopPolicy
    termsOfService: ShopPolicy
    refundPolicy: ShopPolicy
    subscriptionPolicy: ShopPolicy
    metafield(namespace: String!, key: String!): Metafield
    metafields(identifiers: [HasMetafieldsIdentifier!]!): [Metafield]!
  }

  type ShopDomain {
    url: String!
    host: String!
  }

  type Brand {
    logo: MediaImage
    colors: BrandColors
    coverImage: MediaImage
    shortDescription: String
  }

  type BrandColors {
    primary: [BrandColorGroup!]
  }

  type BrandColorGroup {
    background: String
    foreground: String
  }

  type MediaImage {
    image: Image
    previewImage: Image
  }

  type PaymentSettings {
    currencyCode: String!
    acceptedCardBrands: [String!]!
    countryCode: String!
  }

  type ShopPolicy {
    id: ID!
    handle: String!
    title: String!
    body: String!
    url: String!
  }

  # ── Menu ──────────────────────────────────────────────────────────────────

  type Menu {
    id: ID!
    handle: String!
    title: String!
    items: [MenuItem!]!
  }

  type MenuItem {
    id: ID!
    resourceId: ID
    tags: [String!]!
    title: String!
    type: String!
    url: String!
    items: [MenuItem!]!
  }

  # ── Localization ──────────────────────────────────────────────────────────

  type Localization {
    country: LocalizationCountry!
    language: Language!
    availableCountries: [Country!]!
    availableLanguages: [Language!]!
  }

  type LocalizationCountry {
    isoCode: String!
    name: String!
    currency: Currency!
  }

  type Country {
    isoCode: String!
    name: String!
    currency: CountryCurrency!
    availableLanguages: [Language!]!
  }

  type CountryCurrency {
    isoCode: String!
  }

  type Currency {
    isoCode: String!
    name: String!
    symbol: String!
  }

  type Language {
    isoCode: String!
    name: String!
  }
`;
