/**
 * Catalog domain: products, variants, options, collections, and the
 * read-only product Reviews (`@sandbox`) from `reviews.json`.
 */

export const catalogTypeDefs = /* GraphQL */ `
  type Query {
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
    productRecommendations(productId: ID!): [Product!]
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
    """
    The product's Reviews. The Storefront API has no Review type; shops show
    Reviews through a review app.
    """
    reviews(
      first: Int
      after: String
      sortKey: ReviewSortKeys = MOST_RECENT
    ): ReviewConnection! @sandbox
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

  # ── Review ────────────────────────────────────────────────────────────────

  """One read-only product Review from reviews.json."""
  type Review @sandbox {
    id: ID!
    """1 to 5."""
    rating: Int!
    title: String!
    body: String!
    """First name and last initial, e.g. "Maya R."."""
    reviewerName: String!
    """ISO 8601 date and time in UTC."""
    createdAt: String!
    verifiedBuyer: Boolean!
    helpfulCount: Int!
    """The variant the reviewer bought; null when the product no longer has it."""
    variant: ProductVariant
  }

  type ReviewConnection @sandbox {
    nodes: [Review!]!
    edges: [ReviewEdge!]!
    pageInfo: PageInfo!
  }

  type ReviewEdge @sandbox {
    node: Review!
    cursor: String!
  }

  """
  Review orders. Ties put the more recent Review first, then keep the
  reviews.json order.
  """
  enum ReviewSortKeys @sandbox {
    MOST_RECENT
    HIGHEST_RATING
    LOWEST_RATING
    MOST_HELPFUL
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
`;
