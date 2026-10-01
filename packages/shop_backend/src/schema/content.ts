/**
 * Content domain: pages, blogs, and articles.
 */

export const contentTypeDefs = /* GraphQL */ `
  type Query {
    page(handle: String!): Page
    blog(handle: String!): Blog
    blogs(
      first: Int
      last: Int
      before: String
      after: String
    ): BlogConnection!
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
    id: ID!
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
`;
