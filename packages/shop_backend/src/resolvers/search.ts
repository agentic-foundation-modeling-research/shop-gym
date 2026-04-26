/**
 * Resolvers for the Search area of the Storefront API.
 *
 * Covers `Query.search` and `Query.predictiveSearch` per
 * `docs/specs/shop_backend/storefront_api.md` §5.3:
 *
 *   - Substring, lowercased, AND-of-terms matching. An empty (or
 *     whitespace-only) query matches every item for `Query.search` — same
 *     semantics as `matchesSearch` in `builders.ts`. `Query.predictiveSearch`
 *     short-circuits to empty results on a blank query.
 *   - Products are searched against `title` + `description_html` + `vendor` +
 *     `product_type` + `tags`. Collections use `title` + `description` +
 *     `description_html`. Pages and articles use `title` only.
 *   - For `Query.search`, `types` filters which of `PRODUCT` / `PAGE` /
 *     `ARTICLE` are surfaced. When omitted (or `null`), all three are
 *     returned. Results are a `SearchResultItem` union connection; the
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
 *   - `Query.predictiveSearch` returns up to `limit` matches per type
 *     (`limitScope: EACH`, default) or across all types (`limitScope: ALL`),
 *     plus a single `SearchQuerySuggestion` echoing the trimmed query. The
 *     `types` argument may also include `QUERY`, which gates whether the
 *     suggestion is emitted; omitting `types` defaults to all five types.
 *     Articles are empty when `blogs.json` is absent.
 *   - `Query.productRecommendations(productId)` returns up to 4 other products,
 *     prioritised by the spec §5.3 / plan T3.3 cascade: shared
 *     (non-empty) `product_type` first, then descending tag-overlap count,
 *     then dataset insertion order. The requesting product is excluded;
 *     unknown product GIDs resolve to `null`.
 */

import type {
  PredictiveSearchLimitScope,
  PredictiveSearchType,
  QueryPredictiveSearchArgs,
  QueryProductRecommendationsArgs,
  QuerySearchArgs,
  SearchSortKeys,
  SearchType,
} from '../__generated__/resolvers-types.js';
import { type Connection, paginate } from '../data/pagination.js';
import type { Blog, Collection, Product } from '../data/types.js';
import {
  type CollectionNode,
  type ProductNode,
  buildCollectionNode,
  buildProductNode,
  matchesSearch,
} from './builders.js';
import { type ArticleNode, type PageNode, buildArticleNode, buildPageNode } from './content.js';
import type { ResolverContext } from './index.js';

/**
 * Re-export the SDL-derived sort key union under the codebase's historic
 * `SearchSortKey` alias so internal helpers and tests don't need to learn the
 * generated name. Codegen keeps this in sync with the SDL.
 */
export type SearchSortKey = SearchSortKeys;
export type { PredictiveSearchLimitScope, PredictiveSearchType, SearchType };

// ── Node shapes ────────────────────────────────────────────────────────────

/** Tagged union of nodes that may appear under `SearchResultItem`. */
export type SearchResultItemNode = ProductNode | PageNode | ArticleNode;

/** Connection with the non-null `totalCount` exposed on `SearchResultItemConnection`. */
export interface SearchResultItemConnectionNode extends Connection<SearchResultItemNode> {
  readonly totalCount: number;
}

/** Single query suggestion emitted under `PredictiveSearchResult.queries`. */
export interface SearchQuerySuggestionNode {
  readonly text: string;
  readonly styledText: string;
  readonly trackingParameters: string | null;
}

/** Shape returned by `Query.predictiveSearch`. */
export interface PredictiveSearchResultNode {
  readonly products: readonly ProductNode[];
  readonly collections: readonly CollectionNode[];
  readonly pages: readonly PageNode[];
  readonly articles: readonly ArticleNode[];
  readonly queries: readonly SearchQuerySuggestionNode[];
}

// ── Constants ─────────────────────────────────────────────────────────────

const DEFAULT_TYPES: readonly SearchType[] = ['PRODUCT', 'PAGE', 'ARTICLE'];

const DEFAULT_PREDICTIVE_TYPES: readonly PredictiveSearchType[] = [
  'PRODUCT',
  'COLLECTION',
  'PAGE',
  'ARTICLE',
  'QUERY',
];

/**
 * Default `limit` per type when the caller does not supply one. Matches the
 * Storefront API default of 10 results per type.
 */
const DEFAULT_PREDICTIVE_LIMIT = 10;

const PRODUCT_GID_PREFIX = 'gid://shopify/Product/';
const PAGE_GID_PREFIX = 'gid://shopify/Page/';

/** Maximum number of recommendations returned by `Query.productRecommendations`. */
const MAX_RECOMMENDATIONS = 4;

/**
 * Score awarded for a shared, non-empty `product_type`. Set high enough to
 * dominate any plausible tag-overlap count so same-type candidates always
 * sort ahead of products that only share tags.
 */
const SAME_TYPE_BONUS = 1000;

// ── Internal scored entry ─────────────────────────────────────────────────

/** Pre-pagination scored entry used while sorting. */
interface ScoredEntry {
  readonly node: SearchResultItemNode;
  readonly score: number;
  readonly price: number;
}

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for the Search area. Covers `Query.search` (T3.1),
 * `Query.predictiveSearch` (T3.2), and `Query.productRecommendations` (T3.3),
 * plus the `SearchResultItem` union discriminator.
 */
export const searchResolvers = {
  Query: {
    search: (
      _parent: unknown,
      args: QuerySearchArgs,
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

    productRecommendations: (
      _parent: unknown,
      args: QueryProductRecommendationsArgs,
      ctx: ResolverContext,
    ): readonly ProductNode[] | null => {
      const target = findProductByGid(ctx.data.products, args.productId);
      if (target === null) return null;
      const ranked = rankRecommendations(ctx.data.products, target);
      return ranked
        .slice(0, MAX_RECOMMENDATIONS)
        .map((p) =>
          buildProductNode(p, ctx.data.store, ctx.baseUrl, ctx.data.inventoryByVariantId),
        );
    },

    predictiveSearch: (
      _parent: unknown,
      args: QueryPredictiveSearchArgs,
      ctx: ResolverContext,
    ): PredictiveSearchResultNode => {
      const trimmed = args.query.trim();
      if (trimmed === '') return emptyPredictiveResult();

      const types = normalizePredictiveTypes(args.types);
      const limit = clampPredictiveLimit(args.limit);
      const scope = args.limitScope ?? 'EACH';

      const products = types.has('PRODUCT') ? matchProducts(ctx, trimmed) : [];
      const collections = types.has('COLLECTION') ? matchCollections(ctx, trimmed) : [];
      const pages = types.has('PAGE') ? matchPages(ctx, trimmed) : [];
      const articles = types.has('ARTICLE') ? matchArticles(ctx, trimmed) : [];
      const queries = types.has('QUERY') ? [buildQuerySuggestion(trimmed)] : [];

      return capPredictiveResult({ products, collections, pages, articles, queries }, scope, limit);
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
      node: buildProductNode(product, ctx.data.store, ctx.baseUrl, ctx.data.inventoryByVariantId),
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
  sortKey: SearchSortKeys,
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

function normalizeTypes(types: QuerySearchArgs['types']): ReadonlySet<SearchType> {
  const list = types ?? DEFAULT_TYPES;
  return new Set(list);
}

// ── Product recommendation helpers ────────────────────────────────────────

/**
 * Look up a product by its Storefront-API GID (`gid://shopify/Product/<id>`).
 * Returns `null` when the prefix does not match, the suffix is not a positive
 * integer, or no product in the dataset has that id.
 */
function findProductByGid(products: readonly Product[], productId: string): Product | null {
  if (!productId.startsWith(PRODUCT_GID_PREFIX)) return null;
  const suffix = productId.slice(PRODUCT_GID_PREFIX.length);
  const numericId = Number.parseInt(suffix, 10);
  if (!Number.isFinite(numericId) || String(numericId) !== suffix) return null;
  for (const product of products) {
    if (product.id === numericId) return product;
  }
  return null;
}

/**
 * Rank candidate products against `target` for `productRecommendations`.
 * The requesting product is excluded; remaining products sort by descending
 * similarity score with a stable secondary key on dataset position so ties
 * preserve insertion order. Score = `SAME_TYPE_BONUS` when both products
 * share a non-empty `product_type`, plus one point per overlapping tag
 * (case-insensitive). Empty `product_type` is treated as "unspecified" — two
 * unspecified products do not earn the bonus.
 */
function rankRecommendations(products: readonly Product[], target: Product): readonly Product[] {
  const targetTags = new Set(target.tags.map((t) => t.toLowerCase()));
  const ranked = products
    .filter((p) => p.id !== target.id)
    .map((product, index) => ({
      product,
      index,
      score: similarityScore(target, product, targetTags),
    }));
  ranked.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.index - b.index;
  });
  return ranked.map((entry) => entry.product);
}

function similarityScore(
  target: Product,
  candidate: Product,
  targetTags: ReadonlySet<string>,
): number {
  let score = 0;
  if (target.product_type !== '' && target.product_type === candidate.product_type) {
    score += SAME_TYPE_BONUS;
  }
  for (const tag of candidate.tags) {
    if (targetTags.has(tag.toLowerCase())) score += 1;
  }
  return score;
}

// ── Predictive search helpers ─────────────────────────────────────────────

function normalizePredictiveTypes(
  types: QueryPredictiveSearchArgs['types'],
): ReadonlySet<PredictiveSearchType> {
  if (types === null || types === undefined) return new Set(DEFAULT_PREDICTIVE_TYPES);
  const out = new Set<PredictiveSearchType>();
  for (const t of types) {
    if (t !== null && t !== undefined) out.add(t);
  }
  return out;
}

/**
 * Coerce the caller-supplied limit into a positive integer, falling back to
 * the documented default. Non-positive or non-finite inputs collapse to the
 * default rather than producing empty results — matches Shopify's tolerant
 * handling of bad `limit` values.
 */
function clampPredictiveLimit(limit: number | null | undefined): number {
  if (limit === null || limit === undefined) return DEFAULT_PREDICTIVE_LIMIT;
  if (!Number.isFinite(limit) || limit <= 0) return DEFAULT_PREDICTIVE_LIMIT;
  return Math.floor(limit);
}

function matchProducts(ctx: ResolverContext, query: string): readonly ProductNode[] {
  const out: ProductNode[] = [];
  for (const product of ctx.data.products) {
    if (matchesSearch(query, productHaystack(product))) {
      out.push(
        buildProductNode(product, ctx.data.store, ctx.baseUrl, ctx.data.inventoryByVariantId),
      );
    }
  }
  return out;
}

function matchCollections(ctx: ResolverContext, query: string): readonly CollectionNode[] {
  const out: CollectionNode[] = [];
  for (const collection of ctx.data.collections) {
    if (matchesSearch(query, collectionHaystack(collection))) {
      out.push(buildCollectionNode(collection, ctx.baseUrl));
    }
  }
  return out;
}

function matchPages(ctx: ResolverContext, query: string): readonly PageNode[] {
  const out: PageNode[] = [];
  for (const page of ctx.data.pages) {
    if (matchesSearch(query, page.title)) out.push(buildPageNode(page));
  }
  return out;
}

function matchArticles(ctx: ResolverContext, query: string): readonly ArticleNode[] {
  const out: ArticleNode[] = [];
  for (const blog of ctx.data.blogs) {
    appendArticleMatches(out, blog, query);
  }
  return out;
}

function appendArticleMatches(out: ArticleNode[], blog: Blog, query: string): void {
  for (const article of blog.articles) {
    if (matchesSearch(query, article.title)) {
      out.push(buildArticleNode(article, blog.handle));
    }
  }
}

function collectionHaystack(collection: Collection): string {
  return [collection.title, collection.description ?? '', collection.description_html ?? ''].join(
    ' ',
  );
}

function buildQuerySuggestion(text: string): SearchQuerySuggestionNode {
  return { text, styledText: text, trackingParameters: null };
}

function emptyPredictiveResult(): PredictiveSearchResultNode {
  return { products: [], collections: [], pages: [], articles: [], queries: [] };
}

/**
 * Apply `limitScope` to a predictive result. `EACH` (the SDL default) caps
 * each per-type list at `limit`; `ALL` caps the combined total of the four
 * entity lists at `limit` while always preserving the (single) query
 * suggestion. Per-type traversal order matches the Storefront API surface:
 * products, then collections, pages, articles. The query suggestion list is
 * not subject to `limit` since it always contains at most one entry.
 */
function capPredictiveResult(
  result: PredictiveSearchResultNode,
  scope: PredictiveSearchLimitScope,
  limit: number,
): PredictiveSearchResultNode {
  if (scope === 'EACH') {
    return {
      products: result.products.slice(0, limit),
      collections: result.collections.slice(0, limit),
      pages: result.pages.slice(0, limit),
      articles: result.articles.slice(0, limit),
      queries: result.queries,
    };
  }

  let remaining = limit;
  const products = result.products.slice(0, remaining);
  remaining -= products.length;
  const collections = result.collections.slice(0, Math.max(0, remaining));
  remaining -= collections.length;
  const pages = result.pages.slice(0, Math.max(0, remaining));
  remaining -= pages.length;
  const articles = result.articles.slice(0, Math.max(0, remaining));
  return { products, collections, pages, articles, queries: result.queries };
}
