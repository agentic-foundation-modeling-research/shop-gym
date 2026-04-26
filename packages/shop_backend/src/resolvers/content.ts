/**
 * Resolvers for the Page / Blog / Article area of the Storefront API.
 *
 * Covers the surface enumerated in
 * `docs/specs/shop_backend/storefront_api.md` §5.2:
 *
 *   - `Query.page(handle)` — direct dataset lookup, `null` on miss.
 *   - `Query.blog(handle)` — direct lookup over `data.blogs`; `null` when
 *     absent. With no `blogs.json` the dataset's `blogs` is `[]`, so this
 *     naturally returns `null` for every handle.
 *   - `Query.blogs(first/last/before/after)` — Relay-paginated connection
 *     over `data.blogs` in dataset order. Empty connection when the file
 *     is absent.
 *   - `Blog.articles(first/last/before/after)` — Relay-paginated connection
 *     over the parent blog's articles. `totalCount` reflects the full
 *     pre-pagination size.
 *   - `Blog.articleByHandle(handle)` — direct lookup over the parent blog's
 *     articles, `null` on miss.
 *
 * Page / Article builders are exported so the search resolver (T3.1) can reuse
 * them when assembling the `SearchResultItem` union; the blog builder stays
 * private since search does not surface blog nodes directly.
 */

import { type Connection, type PaginationArgs, paginate } from '../data/pagination.js';
import type { Article, Blog, Page } from '../data/types.js';
import { gid } from './builders.js';
import type { ResolverContext } from './index.js';

// ── Node shapes ────────────────────────────────────────────────────────────
// Hand-typed until graphql-codegen lands in M7 (T7.1).

export interface PageNode {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly body: string;
  readonly seo: SeoNode;
  readonly trackingParameters: string | null;
}

export interface ArticleAuthorNode {
  readonly name: string;
}

export interface BlogRefNode {
  readonly handle: string;
}

export interface ArticleNode {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly contentHtml: string;
  readonly publishedAt: string | null;
  readonly author: ArticleAuthorNode | null;
  readonly image: null;
  readonly blog: BlogRefNode;
  readonly seo: SeoNode | null;
  readonly trackingParameters: string | null;
}

export interface BlogNode {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly seo: SeoNode;
  /** The full article list; `Blog.articles` paginates over it. */
  readonly articles: readonly ArticleNode[];
}

export interface SeoNode {
  readonly title: string | null;
  readonly description: string | null;
}

// ── Connection shapes ──────────────────────────────────────────────────────

/** Connection with the optional `totalCount` extension on `ArticleConnection`. */
export interface ArticleConnectionNode extends Connection<ArticleNode> {
  readonly totalCount: number;
}

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for the Page / Blog / Article area. Wired into
 * `createSandboxSchema` once T2.6 combines the per-area maps.
 */
export const contentResolvers = {
  Query: {
    page: (
      _parent: unknown,
      args: { readonly handle: string },
      ctx: ResolverContext,
    ): PageNode | null => {
      const page = findPage(ctx.data.pages, args.handle);
      return page === null ? null : buildPageNode(page);
    },

    blog: (
      _parent: unknown,
      args: { readonly handle: string },
      ctx: ResolverContext,
    ): BlogNode | null => {
      const blog = findBlog(ctx.data.blogs, args.handle);
      return blog === null ? null : buildBlogNode(blog);
    },

    blogs: (_parent: unknown, args: PaginationArgs, ctx: ResolverContext): Connection<BlogNode> => {
      const nodes = ctx.data.blogs.map(buildBlogNode);
      return paginate(nodes, args);
    },
  },

  Blog: {
    articles: (parent: BlogNode, args: PaginationArgs): ArticleConnectionNode => {
      const connection = paginate(parent.articles, args);
      return { ...connection, totalCount: parent.articles.length };
    },

    articleByHandle: (parent: BlogNode, args: { readonly handle: string }): ArticleNode | null => {
      for (const article of parent.articles) {
        if (article.handle === args.handle) return article;
      }
      return null;
    },
  },
};

// ── Builders ──────────────────────────────────────────────────────────────

/** Build a `Page` node from a dataset `Page`. Exported for the search resolver. */
export function buildPageNode(page: Page): PageNode {
  return {
    id: gid('Page', page.handle),
    handle: page.handle,
    title: page.title,
    body: page.body_html,
    seo: emptySeo(),
    trackingParameters: null,
  };
}

function buildBlogNode(blog: Blog): BlogNode {
  return {
    id: gid('Blog', blog.handle),
    handle: blog.handle,
    title: blog.title,
    seo: emptySeo(),
    articles: blog.articles.map((article) => buildArticleNode(article, blog.handle)),
  };
}

/**
 * Build an `Article` node nested under the supplied `blogHandle`. Exported for
 * the search resolver, which surfaces articles in the `SearchResultItem` union.
 */
export function buildArticleNode(article: Article, blogHandle: string): ArticleNode {
  return {
    id: gid('Article', `${blogHandle}/${article.handle}`),
    handle: article.handle,
    title: article.title,
    contentHtml: article.content_html,
    publishedAt: article.published_at,
    author: article.author === null ? null : { name: article.author },
    image: null,
    blog: { handle: blogHandle },
    seo: null,
    trackingParameters: null,
  };
}

function emptySeo(): SeoNode {
  return { title: null, description: null };
}

// ── Lookup helpers ────────────────────────────────────────────────────────

function findPage(pages: readonly Page[], handle: string): Page | null {
  for (const page of pages) {
    if (page.handle === handle) return page;
  }
  return null;
}

function findBlog(blogs: readonly Blog[], handle: string): Blog | null {
  for (const blog of blogs) {
    if (blog.handle === handle) return blog;
  }
  return null;
}
