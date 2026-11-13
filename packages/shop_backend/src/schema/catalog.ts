/**
 * Catalog domain: products, variants, options, collections, product filters
 * and facets, and the read-only product Reviews (`@sandbox`) from
 * `reviews.json`.
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
    """The facets of the list; empty when the shop has no marketplace data."""
    filters: [Filter!]!
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

  # ── Product filters ───────────────────────────────────────────────────────

  """
  One filter on a product list; set one field per entry. Entries with the same
  field match when any of them matches. Entries with different fields must all
  match. variantOption entries group by option name.
  """
  input ProductFilter {
    available: Boolean
    price: PriceRangeFilter
    productType: String
    productVendor: String
    variantOption: VariantOptionFilter
    """The maker's name as the catalog gives it."""
    brand: String @sandbox
    """A category from the department down; matches the products in it or below it."""
    categoryPath: [String!] @sandbox
    """The mean Review rating, rounded to one decimal. Products with no Reviews never match."""
    rating: RatingRangeFilter @sandbox
  }

  """Matches a product when the price of one of its variants is in the range."""
  input PriceRangeFilter {
    min: Float
    max: Float
  }

  input VariantOptionFilter {
    name: String!
    value: String!
  }

  input RatingRangeFilter @sandbox {
    min: Float
    max: Float
  }

  """One facet of a product list: the values a shopper can filter by, with counts."""
  type Filter {
    id: String!
    label: String!
    type: FilterType!
    values: [FilterValue!]!
  }

  type FilterValue {
    id: String!
    label: String!
    """The products the list would have with this value, with the other facets' filters kept."""
    count: Int!
    """The ProductFilter that selects this value."""
    input: JSON!
  }

  enum FilterType {
    BOOLEAN
    LIST
    PRICE_RANGE
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
      filters: [ProductFilter!]
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
