import type { GraphQLSchema } from 'graphql';
import { createSchema as createYogaSchema } from 'graphql-yoga';
import { sandboxResolvers } from './resolvers/index.js';

/**
 * Resolvers parameter accepted by `createSandboxSchema`. Inferred from
 * graphql-yoga's `createSchema` signature so tests and future callers can
 * pass per-area resolver maps without depending on `@graphql-tools/schema`
 * directly.
 */
export type SandboxSchemaResolvers = NonNullable<
  Parameters<typeof createYogaSchema>[0]['resolvers']
>;

/**
 * Storefront API SDL (v0.1).
 *
 * Mirrors the subset enumerated in `docs/specs/shop_backend/storefront_api.md`
 *
 *   1. `enum CurrencyCode` / `enum CountryCode` cover the ISO codes appearing
 *      in the v0.1 fixtures (CAD/USD/CA/US). The mock-api set already covers
 *      this surface; new fixture values should be appended here.
 *   2. `ProductVariant.requiresShipping` resolves from the dataset's
 *      `requires_shipping` field (not hardcoded). The resolver lands in T2.2;
 *      the field doc-comment captures the contract.
 */
const typeDefs = /* GraphQL */ `
  directive @inContext(language: LanguageCode, country: CountryCode, visitorConsent: VisitorConsent) on QUERY | MUTATION

  input VisitorConsent {
    marketing: Boolean
    analytics: Boolean
    preferences: Boolean
    saleOfData: Boolean
  }

  type Query {
    shop: Shop!
    menu(handle: String!): Menu
    product(handle: String!): Product
    products(
      first: Int
      last: Int
      before: String
      after: String
      sortKey: ProductSortKeys
      reverse: Boolean
      query: String
    ): ProductConnection!
    collection(handle: String!): Collection
    collections(
      first: Int
      last: Int
      before: String
      after: String
      sortKey: CollectionSortKeys
      reverse: Boolean
    ): CollectionConnection!
    page(handle: String!): Page
    blog(handle: String!): Blog
    blogs(
      first: Int
      last: Int
      before: String
      after: String
    ): BlogConnection!
    search(
      query: String!
      types: [SearchType!]
      first: Int
      last: Int
      before: String
      after: String
      sortKey: SearchSortKeys
      reverse: Boolean
      unavailableProducts: SearchUnavailableProductsType
      prefix: SearchPrefixQueryType
    ): SearchResultItemConnection!
    predictiveSearch(
      query: String!
      limit: Int
      limitScope: PredictiveSearchLimitScope
      types: [PredictiveSearchType]
    ): PredictiveSearchResult
    productRecommendations(productId: ID!): [Product!]
    localization: Localization!
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

  # ── Product ───────────────────────────────────────────────────────────────

  type Product {
    id: ID!
    handle: String!
    title: String!
    description: String!
    descriptionHtml: String!
    productType: String!
    vendor: String!
    tags: [String!]!
    availableForSale: Boolean!
    publishedAt: String
    priceRange: ProductPriceRange!
    compareAtPriceRange: ProductPriceRange!
    featuredImage: Image
    images(first: Int, after: String): ImageConnection!
    variants(first: Int, after: String): ProductVariantConnection!
    selectedOrFirstAvailableVariant(
      selectedOptions: [SelectedOptionInput!]
      ignoreUnknownOptions: Boolean
      caseInsensitiveMatch: Boolean
    ): ProductVariant
    adjacentVariants(
      selectedOptions: [SelectedOptionInput!]
    ): [ProductVariant!]!
    options: [ProductOption!]!
    encodedVariantExistence: String!
    encodedVariantAvailability: String!
    seo: SEO!
    trackingParameters: String
    createdAt: String
    updatedAt: String
    metafield(namespace: String!, key: String!): Metafield
    metafields(identifiers: [HasMetafieldsIdentifier!]!): [Metafield]!
  }

  type ProductPriceRange {
    minVariantPrice: MoneyV2!
    maxVariantPrice: MoneyV2!
  }

  type ProductOption {
    id: ID!
    name: String!
    values: [String!]!
    optionValues: [ProductOptionValue!]!
  }

  type ProductOptionValue {
    name: String!
    firstSelectableVariant: ProductVariant
    swatch: Swatch
  }

  type Swatch {
    color: String
    image: SwatchMedia
  }

  type SwatchMedia {
    previewImage: Image
  }

  type ProductVariant {
    id: ID!
    title: String!
    availableForSale: Boolean!
    sku: String!
    price: MoneyV2!
    compareAtPrice: MoneyV2
    unitPrice: MoneyV2
    selectedOptions: [SelectedOption!]!
    image: Image
    product: ProductRef!
    """Resolves from the dataset's \`variants[].requires_shipping\` field; not hardcoded."""
    requiresShipping: Boolean!
    quantityAvailable: Int
    metafield(namespace: String!, key: String!): Metafield
    metafields(identifiers: [HasMetafieldsIdentifier!]!): [Metafield]!
  }

  type ProductRef {
    id: ID!
    title: String!
    handle: String!
    vendor: String
  }

  type SelectedOption {
    name: String!
    value: String!
  }

  input SelectedOptionInput {
    name: String!
    value: String!
  }

  type ProductVariantConnection {
    nodes: [ProductVariant!]!
    edges: [ProductVariantEdge!]!
  }

  type ProductVariantEdge {
    node: ProductVariant!
  }

  type ProductConnection {
    nodes: [Product!]!
    edges: [ProductEdge!]!
    pageInfo: PageInfo!
    totalCount: Int
  }

  type ProductEdge {
    node: Product!
    cursor: String!
  }

  # ── Collection ────────────────────────────────────────────────────────────

  type Collection {
    id: ID!
    handle: String!
    title: String!
    description: String!
    descriptionHtml: String!
    image: Image
    trackingParameters: String
    products(
      first: Int
      last: Int
      before: String
      after: String
    ): ProductConnection!
    seo: SEO!
    updatedAt: String
    metafield(namespace: String!, key: String!): Metafield
    metafields(identifiers: [HasMetafieldsIdentifier!]!): [Metafield]!
  }

  type CollectionConnection {
    nodes: [Collection!]!
    edges: [CollectionEdge!]!
    pageInfo: PageInfo!
  }

  type CollectionEdge {
    node: Collection!
    cursor: String!
  }

  # ── Cart ──────────────────────────────────────────────────────────────────

  type Cart {
    id: ID!
    checkoutUrl: String!
    totalQuantity: Int!
    updatedAt: String!
    cost: CartCost!
    lines(first: Int): CartLineConnection!
    attributes: [Attribute!]!
    discountCodes: [CartDiscountCode!]!
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

  type Customer {
    id: ID!
    email: String
    firstName: String
    lastName: String
    displayName: String
  }

  type Attribute {
    key: String!
    value: String!
  }

  input CartInput {
    lines: [CartLineInput!]
    discountCodes: [String!]
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

  # ── Page ──────────────────────────────────────────────────────────────────

  type Page {
    id: ID!
    handle: String!
    title: String!
    body: String!
    seo: SEO!
    trackingParameters: String
  }

  # ── Blog / Article ────────────────────────────────────────────────────────

  type Blog {
    handle: String!
    title: String!
    seo: SEO!
    articles(
      first: Int
      last: Int
      before: String
      after: String
    ): ArticleConnection!
    articleByHandle(handle: String!): Article
  }

  type Article {
    id: ID!
    handle: String!
    title: String!
    contentHtml: String!
    publishedAt: String
    author: ArticleAuthor
    image: Image
    blog: BlogRef!
    seo: SEO
    trackingParameters: String
  }

  type ArticleAuthor {
    name: String!
  }

  type BlogRef {
    handle: String!
  }

  type ArticleConnection {
    nodes: [Article!]!
    edges: [ArticleEdge!]!
    pageInfo: PageInfo!
    totalCount: Int
  }

  type ArticleEdge {
    node: Article!
    cursor: String!
  }

  type BlogConnection {
    nodes: [Blog!]!
    edges: [BlogEdge!]!
    pageInfo: PageInfo!
  }

  type BlogEdge {
    node: Blog!
    cursor: String!
  }

  # ── Search ────────────────────────────────────────────────────────────────

  union SearchResultItem = Product | Page | Article

  type SearchResultItemConnection {
    nodes: [SearchResultItem!]!
    edges: [SearchResultItemEdge!]!
    totalCount: Int!
    pageInfo: PageInfo!
  }

  type SearchResultItemEdge {
    node: SearchResultItem!
    cursor: String!
  }

  type PredictiveSearchResult {
    products: [Product!]!
    collections: [Collection!]!
    pages: [Page!]!
    articles: [Article!]!
    queries: [SearchQuerySuggestion!]!
  }

  type SearchQuerySuggestion {
    text: String!
    styledText: String!
    trackingParameters: String
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

  # ── Common ────────────────────────────────────────────────────────────────

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

  enum SearchType {
    PRODUCT
    PAGE
    ARTICLE
  }

  enum SearchSortKeys {
    PRICE
    RELEVANCE
  }

  enum SearchUnavailableProductsType {
    SHOW
    HIDE
    LAST
  }

  enum SearchPrefixQueryType {
    LAST
    NONE
  }

  enum PredictiveSearchType {
    PRODUCT
    COLLECTION
    PAGE
    ARTICLE
    QUERY
  }

  enum PredictiveSearchLimitScope {
    ALL
    EACH
  }

  enum CollectionSortKeys {
    TITLE
    UPDATED_AT
    ID
    RELEVANCE
  }

  enum ProductSortKeys {
    TITLE
    PRODUCT_TYPE
    VENDOR
    UPDATED_AT
    CREATED_AT
    BEST_SELLING
    PRICE
    ID
    RELEVANCE
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

/**
 * Builds the SandboxShop GraphQL schema.
 *
 * Defaults to the combined `sandboxResolvers` map exported from
 * `resolvers/index.ts`, so callers get a runnable schema with no extra wiring.
 * Per-area tests still pass narrower resolver maps (e.g. `shopResolvers`) to
 * isolate the surface under test.
 */
export function createSandboxSchema(
  resolvers: SandboxSchemaResolvers = sandboxResolvers,
): GraphQLSchema {
  return createYogaSchema({ typeDefs, resolvers });
}
