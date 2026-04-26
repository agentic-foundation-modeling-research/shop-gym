/**
 * Resolvers for the Search area of the Storefront API.
 *
 * Covers `Query.search` per `docs/specs/shop_backend/storefront_api.md` §5.3:
 *
 *   - Substring, lowercased, AND-of-terms matching. An empty (or
 *     whitespace-only) query matches every item — same semantics as
 *     `matchesSearch` in `builders.ts`.
 *   - Products are searched against `title` + `description_html` + `vendor` +
 *     `product_type` + `tags`. Pages and articles are searched against `title`
 *     only.
 *   - `types` filters which of `PRODUCT` / `PAGE` / `ARTICLE` are surfaced.
 *     When omitted (or `null`), all three are returned.
 *   - Results are returned as a `SearchResultItem` union connection. The
 *     `__resolveType` resolver discriminates on the `gid://shopify/<Type>/...`
 *     prefix produced by the per-area builders.
 *   - Sort keys (per spec §5.3 / SDL `SearchSortKeys`):
 *       - `RELEVANCE` (default): descending match score. Score weights title
 *         hits 3× over body hits for products and counts term occurrences
 *         (case-insensitive). Empty query → all scores zero, so the stable
 *         sort preserves dataset order.
 *       - `PRICE`: ascending min variant price. Pages and articles have no
 *         price, so they sort to the end.
 *     `reverse` flips the final order (matches `Query.products` semantics).
 *   - `prefix` and `unavailableProducts` arguments are accepted by the SDL
 *     but ignored at this milestone.
 *
 * `Query.predictiveSearch` and `Query.productRecommendations` land in T3.2 and
 * T3.3; they are intentionally omitted from this map.
 */

import { type Connection, type PaginationArgs, paginate } from '../data/pagination.js';
import type { Blog, Product } from '../data/types.js';
import { type ProductNode, buildProductNode, matchesSearch } from './builders.js';
import { type ArticleNode, type PageNode, buildArticleNode, buildPageNode } from './content.js';
import type { ResolverContext } from './index.js';

// ── Argument shapes ───────────────────────────────────────────────────────
// Hand-typed until graphql-codegen lands in M7 (T7.1).

export type SearchType = 'PRODUCT' | 'PAGE' | 'ARTICLE';
export type SearchSortKey = 'PRICE' | 'RELEVANCE';

interface SearchArgs extends PaginationArgs {
  readonly query: string;
  readonly types?: readonly SearchType[] | null;
  readonly sortKey?: SearchSortKey | null;
  readonly reverse?: boolean | null;
}

// ── Node shapes ────────────────────────────────────────────────────────────

/** Tagged union of nodes that may appear under `SearchResultItem`. */
export type SearchResultItemNode = ProductNode | PageNode | ArticleNode;

/** Connection with the non-null `totalCount` exposed on `SearchResultItemConnection`. */
export interface SearchResultItemConnectionNode extends Connection<SearchResultItemNode> {
  readonly totalCount: number;
}

// ── Constants ─────────────────────────────────────────────────────────────

const DEFAULT_TYPES: readonly SearchType[] = ['PRODUCT', 'PAGE', 'ARTICLE'];

const PRODUCT_GID_PREFIX = 'gid://shopify/Product/';
const PAGE_GID_PREFIX = 'gid://shopify/Page/';

// ── Internal scored entry ─────────────────────────────────────────────────

/** Pre-pagination scored entry used while sorting. */
interface ScoredEntry {
  readonly node: SearchResultItemNode;
  readonly score: number;
  readonly price: number;
}

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for the Search area. `Query.search` only at this milestone;
 * `Query.predictiveSearch` (T3.2) and `Query.productRecommendations` (T3.3)
 * extend this map in subsequent tasks.
 */
export const searchResolvers = {
  Query: {
    search: (
      _parent: unknown,
      args: SearchArgs,
      ctx: ResolverContext,
    ): SearchResultItemConnectionNode => {
      const types = normalizeTypes(args.types);
      const query = args.query;

      const scored: ScoredEntry[] = [];
      if (types.has('PRODUCT')) collectProducts(scored, ctx, query);
      if (types.has('PAGE')) collectPages(scored, ctx, query);
      if (types.has('ARTICLE')) collectArticles(scored, ctx, query);

      const sorted = sortResults(scored, args.sortKey ?? 'RELEVANCE', args.reverse ?? false);
      const nodes = sorted.map((entry) => entry.node);
      const connection = paginate(nodes, args);
      return { ...connection, totalCount: nodes.length };
    },
  },

  SearchResultItem: {
    __resolveType: (obj: SearchResultItemNode): 'Product' | 'Page' | 'Article' => {
      if (obj.id.startsWith(PRODUCT_GID_PREFIX)) return 'Product';
      if (obj.id.startsWith(PAGE_GID_PREFIX)) return 'Page';
      return 'Article';
    },
  },
};

// ── Collection helpers ────────────────────────────────────────────────────

function collectProducts(out: ScoredEntry[], ctx: ResolverContext, query: string): void {
  for (const product of ctx.data.products) {
    if (!matchesSearch(query, productHaystack(product))) continue;
    out.push({
      node: buildProductNode(product, ctx.data.store, ctx.baseUrl),
      score: scoreProduct(query, product),
      price: minVariantPrice(product),
    });
  }
}

function collectPages(out: ScoredEntry[], ctx: ResolverContext, query: string): void {
  for (const page of ctx.data.pages) {
    if (!matchesSearch(query, page.title)) continue;
    out.push({
      node: buildPageNode(page),
      score: countMatches(query, page.title),
      price: Number.POSITIVE_INFINITY,
    });
  }
}

function collectArticles(out: ScoredEntry[], ctx: ResolverContext, query: string): void {
  for (const blog of ctx.data.blogs) {
    forEachArticleMatch(out, blog, query);
  }
}

function forEachArticleMatch(out: ScoredEntry[], blog: Blog, query: string): void {
  for (const article of blog.articles) {
    if (!matchesSearch(query, article.title)) continue;
    out.push({
      node: buildArticleNode(article, blog.handle),
      score: countMatches(query, article.title),
      price: Number.POSITIVE_INFINITY,
    });
  }
}

// ── Scoring ───────────────────────────────────────────────────────────────

function productHaystack(product: Product): string {
  return [
    product.title,
    product.description_html,
    product.vendor,
    product.product_type,
    ...product.tags,
  ].join(' ');
}

/**
 * Score a product against a query. Title hits weigh 3× heavier than other
 * matches so a product whose title literally contains the term ranks above
 * one that only mentions it in the description. Empty queries score 0 across
 * the board, leaving the stable sort to preserve dataset order.
 */
function scoreProduct(query: string, product: Product): number {
  if (query.trim() === '') return 0;
  const titleScore = countMatches(query, product.title) * 3;
  const bodyScore = countMatches(query, productHaystack(product));
  return titleScore + bodyScore;
}

function countMatches(query: string, haystack: string): number {
  const trimmed = query.trim();
  if (trimmed === '') return 0;
  const lowerHaystack = haystack.toLowerCase();
  let total = 0;
  for (const term of trimmed.toLowerCase().split(/\s+/)) {
    if (term === '') continue;
    let from = 0;
    for (;;) {
      const idx = lowerHaystack.indexOf(term, from);
      if (idx === -1) break;
      total += 1;
      from = idx + term.length;
    }
  }
  return total;
}

function minVariantPrice(product: Product): number {
  let min = Number.POSITIVE_INFINITY;
  for (const variant of product.variants) {
    const value = Number.parseFloat(variant.price);
    if (Number.isFinite(value) && value < min) min = value;
  }
  return min;
}

// ── Sort ──────────────────────────────────────────────────────────────────

function sortResults(
  entries: readonly ScoredEntry[],
  sortKey: SearchSortKey,
  reverse: boolean,
): readonly ScoredEntry[] {
  const copy = [...entries];
  if (sortKey === 'PRICE') {
    copy.sort((a, b) => a.price - b.price);
  } else {
    copy.sort((a, b) => b.score - a.score);
  }
  if (reverse) copy.reverse();
  return copy;
}

// ── Internal helpers ──────────────────────────────────────────────────────

function normalizeTypes(types: readonly SearchType[] | null | undefined): ReadonlySet<SearchType> {
  const list = types ?? DEFAULT_TYPES;
  return new Set(list);
}
