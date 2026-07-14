/**
 * Resolvers for the Product / Collection area of the Storefront API.
 *
 * Covers the surface enumerated in
 * `docs/specs/shop_backend/storefront_api.md` §5.2:
 *
 *   - `Query.product(handle)` — direct dataset lookup, `null` on miss.
 *   - `Query.products(first/last/before/after/sortKey/reverse/query)` —
 *     filtered + sorted + Relay-paginated. Filter semantics per spec §5.3
 *     (`title`, `description_html`, `vendor`, `product_type`, `tags`).
 *     `totalCount` reflects the post-filter, pre-pagination size.
 *   - `Query.collection(handle)` — dataset lookup; the synthetic handle
 *     `"all"` is materialized in-memory and contains every dataset product
 *     (spec §5.3).
 *   - `Query.collections(first/last/before/after/sortKey/reverse)` — sorted
 *     + paginated.
 *   - `Product.selectedOrFirstAvailableVariant(selectedOptions)` — pick the
 *     variant matching `selectedOptions`, otherwise the first available
 *     variant, otherwise the first variant, otherwise `null`.
 *   - `Collection.products` — nested products connection. Resolves member
 *     handles against `data.productsByHandle`; for the synthetic `"all"`
 *     handle, returns the full dataset.
 *
 * Sort keys per spec §5.3:
 *   - `products`: TITLE / PRICE (min variant price) / CREATED_AT /
 *     UPDATED_AT / VENDOR / PRODUCT_TYPE / ID / BEST_SELLING and RELEVANCE
 *     fall back to dataset order. `reverse` honored.
 *   - `collections`: TITLE / UPDATED_AT / ID; RELEVANCE falls back to dataset
 *     order.
 */

import type {
  CollectionProductsArgs,
  CollectionSortKeys,
  ProductImagesArgs,
  ProductSelectedOrFirstAvailableVariantArgs,
  ProductSortKeys,
  ProductVariantsArgs,
  QueryCollectionArgs,
  QueryCollectionsArgs,
  QueryProductArgs,
  QueryProductsArgs,
  SelectedOptionInput,
} from '../__generated__/resolvers-types.js';
import { type Connection, paginate } from '../data/pagination.js';
import type { Collection, Product, SandboxShopData } from '../data/types.js';
import { encodeVariantAvailability, encodeVariantExistence } from '../encoded_variants.js';
import {
  type CollectionNode,
  type ImageNode,
  type ProductNode,
  type ProductVariantNode,
  buildCollectionNode,
  buildProductNode,
  gid,
  matchesSearch,
} from './builders.js';
import type { ResolverContext } from './index.js';

// ── Connection shapes ─────────────────────────────────────────────────────

/** Connection with the `totalCount` extension exposed on `ProductConnection`. */
export interface ProductConnectionNode extends Connection<ProductNode> {
  readonly totalCount: number;
}

/**
 * Re-export the SDL-derived sort key unions so test helpers and tooling can
 * import them without reaching into the generated module directly. Codegen
 * keeps these in sync with the SDL definitions in §5.3 / §8.2.
 */
export type ProductSortKey = ProductSortKeys;
export type CollectionSortKey = CollectionSortKeys;

// ── Constants ─────────────────────────────────────────────────────────────

/** Synthetic collection handle that exposes every product in the dataset. */
const ALL_HANDLE = 'all';

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for the Product / Collection area. Wired into
 * `createSandboxSchema` once T2.6 combines the per-area maps.
 */
export const productResolvers = {
  Query: {
    product: (
      _parent: unknown,
      args: QueryProductArgs,
      ctx: ResolverContext,
    ): ProductNode | null => {
      const product = ctx.data.productsByHandle.get(args.handle);
      if (product === undefined) return null;
      return buildProductNode(
        product,
        ctx.data.store,
        ctx.baseUrl,
        ctx.data.inventoryByVariantId,
        ctx.imageUrlMode,
      );
    },

    products: (
      _parent: unknown,
      args: QueryProductsArgs,
      ctx: ResolverContext,
    ): ProductConnectionNode => {
      const filtered = filterProducts(ctx.data.products, args.query ?? null);
      const sorted = sortProducts(filtered, args.sortKey ?? null, args.reverse ?? false);
      const nodes = sorted.map((p) =>
        buildProductNode(
          p,
          ctx.data.store,
          ctx.baseUrl,
          ctx.data.inventoryByVariantId,
          ctx.imageUrlMode,
        ),
      );
      const connection = paginate(nodes, args);
      return { ...connection, totalCount: filtered.length };
    },

    collection: (
      _parent: unknown,
      args: QueryCollectionArgs,
      ctx: ResolverContext,
    ): CollectionNode | null => {
      if (args.handle === ALL_HANDLE) return buildAllCollectionNode();
      const collection = findCollection(ctx.data, args.handle);
      if (collection === null) return null;
      return buildCollectionNode(collection, ctx.baseUrl, ctx.imageUrlMode);
    },

    collections: (
      _parent: unknown,
      args: QueryCollectionsArgs,
      ctx: ResolverContext,
    ): Connection<CollectionNode> => {
      const sorted = sortCollections(
        ctx.data.collections,
        args.sortKey ?? null,
        args.reverse ?? false,
      );
      const nodes = sorted.map((c) => buildCollectionNode(c, ctx.baseUrl, ctx.imageUrlMode));
      return paginate(nodes, args);
    },
  },

  Product: {
    images: (parent: ProductNode, args: Partial<ProductImagesArgs>): Connection<ImageNode> =>
      paginate(parent.images, args),

    encodedVariantExistence: (parent: ProductNode): string =>
      encodeVariantExistence(parent.options, parent.variants),

    encodedVariantAvailability: (parent: ProductNode): string =>
      encodeVariantAvailability(parent.options, parent.variants),

    variants: (
      parent: ProductNode,
      args: Partial<ProductVariantsArgs>,
    ): Connection<ProductVariantNode> => paginate(parent.variants, args),

    selectedOrFirstAvailableVariant: (
      parent: ProductNode,
      args: ProductSelectedOrFirstAvailableVariantArgs,
    ): ProductVariantNode | null => {
      const selected = args.selectedOptions ?? null;
      if (selected !== null && selected.length > 0) {
        const caseInsensitive = args.caseInsensitiveMatch ?? false;
        const ignoreUnknown = args.ignoreUnknownOptions ?? false;
        const found = parent.variants.find((variant) =>
          matchesSelectedOptions(variant, selected, caseInsensitive, ignoreUnknown),
        );
        if (found !== undefined) return found;
      }
      const firstAvailable = parent.variants.find((variant) => variant.availableForSale);
      if (firstAvailable !== undefined) return firstAvailable;
      return parent.variants[0] ?? null;
    },
  },

  Collection: {
    products: (
      parent: CollectionNode,
      args: CollectionProductsArgs,
      ctx: ResolverContext,
    ): ProductConnectionNode => {
      const products = collectionProducts(ctx.data, parent.handle);
      const nodes = products.map((p) =>
        buildProductNode(
          p,
          ctx.data.store,
          ctx.baseUrl,
          ctx.data.inventoryByVariantId,
          ctx.imageUrlMode,
        ),
      );
      const connection = paginate(nodes, args);
      return { ...connection, totalCount: nodes.length };
    },
  },
};

// ── Filter / sort helpers ─────────────────────────────────────────────────

function filterProducts(products: readonly Product[], query: string | null): readonly Product[] {
  if (query === null || query.trim() === '') return products;
  return products.filter((product) => matchesSearch(query, productHaystack(product)));
}

function productHaystack(product: Product): string {
  return [
    product.title,
    product.description_html,
    product.vendor,
    product.product_type,
    ...product.tags,
  ].join(' ');
}

function sortProducts(
  products: readonly Product[],
  sortKey: ProductSortKeys | null,
  reverse: boolean,
): readonly Product[] {
  let result: readonly Product[] = products;
  if (sortKey !== null && sortKey !== 'BEST_SELLING' && sortKey !== 'RELEVANCE') {
    const copy = [...products];
    copy.sort((a, b) => compareProducts(a, b, sortKey));
    result = copy;
  }
  if (reverse) result = [...result].reverse();
  return result;
}

function compareProducts(a: Product, b: Product, key: ProductSortKeys): number {
  switch (key) {
    case 'TITLE':
      return a.title.localeCompare(b.title);
    case 'VENDOR':
      return a.vendor.localeCompare(b.vendor);
    case 'PRODUCT_TYPE':
      return a.product_type.localeCompare(b.product_type);
    case 'CREATED_AT':
      return a.created_at.localeCompare(b.created_at);
    case 'UPDATED_AT':
      return a.updated_at.localeCompare(b.updated_at);
    case 'ID':
      return a.id - b.id;
    case 'PRICE':
      return minVariantPrice(a) - minVariantPrice(b);
    case 'BEST_SELLING':
    case 'RELEVANCE':
      return 0;
  }
}

function minVariantPrice(product: Product): number {
  let min = Number.POSITIVE_INFINITY;
  for (const variant of product.variants) {
    const value = Number.parseFloat(variant.price);
    if (Number.isFinite(value) && value < min) min = value;
  }
  return Number.isFinite(min) ? min : 0;
}

function sortCollections(
  collections: readonly Collection[],
  sortKey: CollectionSortKeys | null,
  reverse: boolean,
): readonly Collection[] {
  let result: readonly Collection[] = collections;
  if (sortKey !== null && sortKey !== 'RELEVANCE') {
    const copy = [...collections];
    copy.sort((a, b) => compareCollections(a, b, sortKey));
    result = copy;
  }
  if (reverse) result = [...result].reverse();
  return result;
}

function compareCollections(a: Collection, b: Collection, key: CollectionSortKeys): number {
  switch (key) {
    case 'TITLE':
      return a.title.localeCompare(b.title);
    case 'UPDATED_AT':
      return (a.updated_at ?? '').localeCompare(b.updated_at ?? '');
    case 'ID':
      return a.id - b.id;
    case 'RELEVANCE':
      return 0;
  }
}

// ── Collection helpers ────────────────────────────────────────────────────

function findCollection(data: SandboxShopData, handle: string): Collection | null {
  for (const collection of data.collections) {
    if (collection.handle === handle) return collection;
  }
  return null;
}

function buildAllCollectionNode(): CollectionNode {
  return {
    id: gid('Collection', ALL_HANDLE),
    handle: ALL_HANDLE,
    title: 'All Products',
    description: '',
    descriptionHtml: '',
    image: null,
    updatedAt: null,
  };
}

function collectionProducts(data: SandboxShopData, handle: string): readonly Product[] {
  if (handle === ALL_HANDLE) return data.products;
  const collection = findCollection(data, handle);
  if (collection === null) return [];
  const result: Product[] = [];
  for (const productHandle of collection.product_handles) {
    const product = data.productsByHandle.get(productHandle);
    if (product !== undefined) result.push(product);
  }
  return result;
}

// ── Variant matching ──────────────────────────────────────────────────────

function matchesSelectedOptions(
  variant: ProductVariantNode,
  selected: readonly SelectedOptionInput[],
  caseInsensitive: boolean,
  ignoreUnknown: boolean,
): boolean {
  for (const input of selected) {
    const variantOption = variant.selectedOptions.find((option) =>
      caseInsensitive
        ? option.name.toLowerCase() === input.name.toLowerCase()
        : option.name === input.name,
    );
    if (variantOption === undefined) {
      if (ignoreUnknown) continue;
      return false;
    }
    const matches = caseInsensitive
      ? variantOption.value.toLowerCase() === input.value.toLowerCase()
      : variantOption.value === input.value;
    if (!matches) return false;
  }
  return true;
}
