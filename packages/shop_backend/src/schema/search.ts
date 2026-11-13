/**
 * Search domain: full-text search and predictive search. `search` takes
 * `productFilters` and returns the facets of its product results.
 */

export const searchTypeDefs = /* GraphQL */ `
  type Query {
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
      productFilters: [ProductFilter!]
    ): SearchResultItemConnection!
    predictiveSearch(
      query: String!
      limit: Int
      limitScope: PredictiveSearchLimitScope
      types: [PredictiveSearchType]
    ): PredictiveSearchResult
  }

  union SearchResultItem = Product | Page | Article

  type SearchResultItemConnection {
    nodes: [SearchResultItem!]!
    edges: [SearchResultItemEdge!]!
    totalCount: Int!
    pageInfo: PageInfo!
    """The facets of the product results; empty when the shop has no marketplace data."""
    productFilters: [Filter!]!
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
`;
