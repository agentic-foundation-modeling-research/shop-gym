/**
 * Pure builders that translate dataset entities into GraphQL node shapes.
 *
 * Every builder is a function from typed dataset values to typed plain objects
 * whose field names mirror the SDL in `packages/shop_backend/src/schema.ts`.
 * No I/O, no dataset mutation, no `any` casts. The resolver layer (T2.3+)
 * composes these builders to answer Storefront-API queries against
 * `SandboxShopData`.
 *
 * GIDs follow `docs/specs/shop_backend/storefront_api.md` §5.3: numeric ids
 * are pasted in as-is, string keys are hashed via 32-bit FNV-1a so the same
 * (type, key) pair always yields the same GID across server instances.
 *
 * Image URLs follow §5.3 too: an absolute http(s) `images[].src` passes
 * through unchanged; anything else is rewritten to `<baseUrl>/images/<src>`.
 *
 * Brand colors come from `store.brand.colors`, replacing the mock-api
 * `#000000`/`#ffffff` hardcode.
 */

import type {
  Collection,
  InventoryEntry,
  NavigationItem,
  Policy,
  Product,
  ProductImage,
  ProductOption,
  ProductVariant,
  Store,
} from '../data/types.js';

/**
 * Optional per-variant inventory lookup threaded into the product / variant
 * builders (since v0.2). Resolvers pass `ctx.data.inventoryByVariantId`; tests
 * and out-of-tree callers may pass `undefined` to fall back to the dataset's
 * binary `variants[].available` flag (spec §5.3 inventory rules).
 */
export type InventoryLookup = ReadonlyMap<number, InventoryEntry> | undefined;

// ── Node shapes ────────────────────────────────────────────────────────────
// Hand-typed until graphql-codegen lands in M7 (T7.1).

export interface MoneyV2Node {
  readonly amount: string;
  readonly currencyCode: string;
}

export interface ImageNode {
  readonly id: string;
  readonly url: string;
  readonly altText: string | null;
  readonly width: number;
  readonly height: number;
}

export interface SelectedOptionNode {
  readonly name: string;
  readonly value: string;
}

export interface ProductRefNode {
  readonly id: string;
  readonly title: string;
  readonly handle: string;
  readonly vendor: string;
}

export interface ProductVariantNode {
  readonly id: string;
  readonly title: string;
  readonly availableForSale: boolean;
  readonly sku: string;
  readonly price: MoneyV2Node;
  readonly compareAtPrice: MoneyV2Node | null;
  readonly unitPrice: MoneyV2Node | null;
  readonly selectedOptions: readonly SelectedOptionNode[];
  readonly image: ImageNode | null;
  readonly product: ProductRefNode;
  readonly requiresShipping: boolean;
  readonly quantityAvailable: number | null;
}

export interface ProductOptionValueNode {
  readonly name: string;
  readonly firstSelectableVariant: ProductVariantNode | null;
  readonly swatch: null;
}

export interface ProductOptionNode {
  readonly id: string;
  readonly name: string;
  readonly values: readonly string[];
  readonly optionValues: readonly ProductOptionValueNode[];
}

export interface ProductPriceRangeNode {
  readonly minVariantPrice: MoneyV2Node;
  readonly maxVariantPrice: MoneyV2Node;
}

export interface ProductNode {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly description: string;
  readonly descriptionHtml: string;
  readonly productType: string;
  readonly vendor: string;
  readonly tags: readonly string[];
  readonly availableForSale: boolean;
  readonly publishedAt: string | null;
  readonly createdAt: string | null;
  readonly updatedAt: string | null;
  readonly priceRange: ProductPriceRangeNode;
  readonly compareAtPriceRange: ProductPriceRangeNode;
  readonly featuredImage: ImageNode | null;
  readonly images: readonly ImageNode[];
  readonly variants: readonly ProductVariantNode[];
  readonly options: readonly ProductOptionNode[];
}

export interface CollectionNode {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly description: string;
  readonly descriptionHtml: string;
  readonly image: ImageNode | null;
  readonly updatedAt: string | null;
}

export interface MenuItemNode {
  readonly id: string;
  readonly resourceId: string | null;
  readonly tags: readonly string[];
  readonly title: string;
  readonly type: string;
  readonly url: string;
  readonly items: readonly MenuItemNode[];
}

export interface ShopPolicyNode {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly body: string;
  readonly url: string;
}

// ── GID ────────────────────────────────────────────────────────────────────

const GID_PREFIX = 'gid://shopify';

/**
 * Build a GID. Numeric ids are pasted in as-is; string keys are
 * hashed via 32-bit FNV-1a (rendered as 8-char hex) so the same `(type, key)`
 * pair always yields the same GID across server instances.
 */
export function gid(type: string, id: number | string): string {
  const suffix = typeof id === 'number' ? String(id) : fnv1a32Hex(id);
  return `${GID_PREFIX}/${type}/${suffix}`;
}

function fnv1a32Hex(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

// ── String helpers ─────────────────────────────────────────────────────────

const HTML_TAG = /<[^>]*>/g;
const COLLAPSE_WHITESPACE = /\s+/g;

/**
 * Strip HTML tags and collapse whitespace. Used to project `description_html`
 * into the plain-text `Product.description` / `Collection.description` fields.
 */
export function stripHtml(html: string): string {
  return html.replace(HTML_TAG, ' ').replace(COLLAPSE_WHITESPACE, ' ').trim();
}

/**
 * Substring, lowercased, AND-of-terms search. Returns true when every
 * whitespace-separated term in `query` appears in `haystack`. An empty (or
 * whitespace-only) query always matches. See spec §5.3.
 */
export function matchesSearch(query: string, haystack: string): boolean {
  const trimmed = query.trim();
  if (trimmed === '') {
    return true;
  }
  const lowerHaystack = haystack.toLowerCase();
  for (const term of trimmed.toLowerCase().split(/\s+/)) {
    if (term === '') continue;
    if (!lowerHaystack.includes(term)) {
      return false;
    }
  }
  return true;
}

// ── Money / image ──────────────────────────────────────────────────────────

/**
 * Build a `MoneyV2` node, normalizing the dataset's decimal-string `amount`
 * into a fixed two-decimal form so cart math doesn't have to renormalize.
 */
export function buildMoneyV2(amount: string, currencyCode: string): MoneyV2Node {
  return { amount: formatMoney(amount), currencyCode };
}

function formatMoney(amount: string): string {
  const value = Number.parseFloat(amount);
  if (!Number.isFinite(value)) return '0.00';
  return value.toFixed(2);
}

const ABSOLUTE_URL = /^https?:\/\//i;

/**
 * Build an `Image` node, rewriting relative `src` paths to the local
 * `/images/` route. Absolute http(s) URLs (e.g. CDN) pass through unchanged.
 */
export function buildImageNode(image: ProductImage, baseUrl: string): ImageNode {
  return {
    id: gid('ProductImage', image.id),
    url: rewriteImageUrl(image.src, baseUrl),
    altText: image.alt,
    width: image.width,
    height: image.height,
  };
}

function rewriteImageUrl(src: string, baseUrl: string): string {
  if (ABSOLUTE_URL.test(src)) return src;
  const trimmedBase = baseUrl.replace(/\/+$/, '');
  const trimmedSrc = src.replace(/^\/+/, '');
  return `${trimmedBase}/images/${trimmedSrc}`;
}

// ── Product / variant ──────────────────────────────────────────────────────

/**
 * Build a `ProductVariant` node from its parent product + the dataset variant.
 *
 * `inventory` (optional, since v0.2) supplies per-variant stock counts. When a
 * tracked entry exists for `variant.id`, `availableForSale` derives from
 * `quantity_available > 0` and `quantityAvailable` echoes the count. Otherwise
 * (no entry, or `quantity_available === null`) `quantityAvailable` is `null`
 * and `availableForSale` falls back to `variant.available` (spec §5.3).
 */
export function buildProductVariantNode(
  product: Product,
  variant: ProductVariant,
  store: Store,
  baseUrl: string,
  inventory?: InventoryLookup,
): ProductVariantNode {
  const featured = pickFeaturedImage(product);
  const entry = inventory?.get(variant.id);
  return {
    id: gid('ProductVariant', variant.id),
    title: variant.title,
    availableForSale: resolveAvailableForSale(variant, entry),
    sku: variant.sku ?? '',
    price: buildMoneyV2(variant.price, store.currency_code),
    compareAtPrice:
      variant.compare_at_price === null
        ? null
        : buildMoneyV2(variant.compare_at_price, store.currency_code),
    unitPrice: null,
    selectedOptions: buildSelectedOptions(product.options, variant),
    image: featured === null ? null : buildImageNode(featured, baseUrl),
    product: {
      id: gid('Product', product.id),
      title: product.title,
      handle: product.handle,
      vendor: product.vendor,
    },
    requiresShipping: variant.requires_shipping,
    quantityAvailable: entry?.quantity_available ?? null,
  };
}

function resolveAvailableForSale(
  variant: ProductVariant,
  entry: InventoryEntry | undefined,
): boolean {
  if (entry === undefined || entry.quantity_available === null) {
    return variant.available;
  }
  return entry.quantity_available > 0;
}

function buildSelectedOptions(
  options: readonly ProductOption[],
  variant: ProductVariant,
): readonly SelectedOptionNode[] {
  const variantOptionValues: readonly (string | null)[] = [
    variant.option1,
    variant.option2,
    variant.option3,
  ];
  const result: SelectedOptionNode[] = [];
  for (const option of options) {
    const value = variantOptionValues[option.position - 1];
    if (value === undefined || value === null) continue;
    result.push({ name: option.name, value });
  }
  return result;
}

function pickFeaturedImage(product: Product): ProductImage | null {
  if (product.images.length === 0) return null;
  let pick: ProductImage | null = null;
  for (const img of product.images) {
    if (pick === null || img.position < pick.position) pick = img;
  }
  return pick;
}

/**
 * Build a `Product` node with its variants, options, images, and price ranges.
 *
 * `inventory` (optional, since v0.2) is forwarded to every
 * `buildProductVariantNode` call; `Product.availableForSale` reflects the
 * resolved variant-level availability (spec §5.3).
 */
export function buildProductNode(
  product: Product,
  store: Store,
  baseUrl: string,
  inventory?: InventoryLookup,
): ProductNode {
  const variants = product.variants.map((v) =>
    buildProductVariantNode(product, v, store, baseUrl, inventory),
  );
  const images = product.images.map((img) => buildImageNode(img, baseUrl));
  const featured = pickFeaturedImage(product);
  return {
    id: gid('Product', product.id),
    handle: product.handle,
    title: product.title,
    description: stripHtml(product.description_html),
    descriptionHtml: product.description_html,
    productType: product.product_type,
    vendor: product.vendor,
    tags: product.tags,
    availableForSale: variants.some((v) => v.availableForSale),
    publishedAt: product.published_at,
    createdAt: product.created_at,
    updatedAt: product.updated_at,
    priceRange: computePriceRange(
      product.variants.map((v) => v.price),
      store.currency_code,
    ),
    compareAtPriceRange: computePriceRange(
      product.variants.map((v) => v.compare_at_price ?? '0'),
      store.currency_code,
    ),
    featuredImage: featured === null ? null : buildImageNode(featured, baseUrl),
    images,
    variants,
    options: product.options.map((option) => buildProductOptionNode(product, option, variants)),
  };
}

function buildProductOptionNode(
  product: Product,
  option: ProductOption,
  variants: readonly ProductVariantNode[],
): ProductOptionNode {
  return {
    id: gid('ProductOption', `${product.id}-${option.position}`),
    name: option.name,
    values: option.values,
    optionValues: option.values.map((value) => ({
      name: value,
      firstSelectableVariant:
        variants.find((v) =>
          v.selectedOptions.some((o) => o.name === option.name && o.value === value),
        ) ?? null,
      swatch: null,
    })),
  };
}

function computePriceRange(prices: readonly string[], currencyCode: string): ProductPriceRangeNode {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const p of prices) {
    const value = Number.parseFloat(p);
    if (!Number.isFinite(value)) continue;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  if (!Number.isFinite(min)) min = 0;
  if (!Number.isFinite(max)) max = 0;
  return {
    minVariantPrice: buildMoneyV2(min.toFixed(2), currencyCode),
    maxVariantPrice: buildMoneyV2(max.toFixed(2), currencyCode),
  };
}

// ── Collection / menu / policy ─────────────────────────────────────────────

/** Build a `Collection` node. Member products are resolved separately. */
export function buildCollectionNode(collection: Collection, baseUrl: string): CollectionNode {
  return {
    id: gid('Collection', collection.id),
    handle: collection.handle,
    title: collection.title,
    description: collection.description ?? '',
    descriptionHtml: collection.description_html ?? '',
    image: collection.image === null ? null : buildImageNode(collection.image, baseUrl),
    updatedAt: collection.updated_at,
  };
}

/** Build a `MenuItem` node, recursing over its children. */
export function buildMenuItemNode(item: NavigationItem): MenuItemNode {
  return {
    id: gid('MenuItem', `${item.title}|${item.url}`),
    resourceId: null,
    tags: [],
    title: item.title,
    type: item.type,
    url: item.url,
    items: item.children.map(buildMenuItemNode),
  };
}

/** Build a `ShopPolicy` node, deriving the public URL from the store domain. */
export function buildPolicyNode(policy: Policy, store: Store): ShopPolicyNode {
  return {
    id: gid('ShopPolicy', `${store.shop_id}-${policy.handle}`),
    handle: policy.handle,
    title: policy.title,
    body: policy.body_html,
    url: `https://${store.domain}/policies/${policy.handle}`,
  };
}
