/**
 * Product filters and facets for `Query.search` and `Collection.products`.
 *
 * `applyProductFilters` narrows a product list by `ProductFilter` entries and
 * builds the facets (Storefront `Filter`s) that a shopper can narrow the
 * list by next.
 *
 * Matching. Each set field of an entry is one filter. Filters with the same
 * key match when any of them matches; filters with different keys must all
 * match. `variantOption` filters group by option name.
 *   - `available`: some variant is for sale (`true`) or none is (`false`).
 *   - `price`: some variant price is in [min, max].
 *   - `productType`, `productVendor`, `brand`: equal to the product value.
 *   - `variantOption`: some variant has the option value.
 *   - `categoryPath`: the product's category path starts with the path.
 *   - `rating`: the product's mean Review rating, rounded to one decimal,
 *     is in [min, max]. A product with no Reviews never matches.
 *
 * Facets, in this order: category, brand, price and rating. A value counts
 * the products that pass every filter except the filters of its own facet,
 * so it tells what choosing that value would give. A facet lists only
 * values with products, plus the values that are already selected, and a
 * facet with no values is left out. The facets are empty when no product
 * of the shop has a brand or a category path, so a shop without
 * marketplace data shows no facet panel.
 */

import type {
  FilterType,
  ProductFilter,
  VariantOptionFilter,
} from '../__generated__/resolvers-types.js';
import type { Product, ProductVariant, SandboxShopData } from '../data/types.js';
import { resolveAvailableForSale } from './builders.js';
import { averageRating } from './review.js';

/** A `FilterValue` as the resolvers return it. */
export interface FilterValueNode {
  readonly id: string;
  readonly label: string;
  readonly count: number;
  /** The `ProductFilter` that selects this value, JSON-encoded. */
  readonly input: string;
}

/** A `Filter` (one facet) as the resolvers return it. */
export interface FilterNode {
  readonly id: string;
  readonly label: string;
  readonly type: FilterType;
  readonly values: readonly FilterValueNode[];
}

/** Output of `applyProductFilters`. */
export interface FilteredProducts {
  /** The products that pass every filter, in input order. */
  readonly products: readonly Product[];
  /** The facets of the list; empty when the shop has no marketplace data. */
  readonly filters: readonly FilterNode[];
}

/** The filter keys that have a facet, in facet order. */
const FACET_KEYS = ['categoryPath', 'brand', 'price', 'rating'] as const;
type FacetKey = (typeof FACET_KEYS)[number];

/** Rating thresholds of the rating facet, highest first. */
const RATING_THRESHOLDS = [4, 3, 2, 1] as const;

/** A product with the values that the filters and facets read more than once. */
interface Candidate {
  readonly product: Product;
  readonly rating: number | null;
}

type Matcher = (candidate: Candidate) => boolean;

interface FilterGroup {
  readonly key: string;
  readonly matchers: readonly Matcher[];
}

/** The values that the filters select, so facets can keep them listed. */
interface Selection {
  readonly brands: readonly string[];
  readonly categoryPaths: readonly (readonly string[])[];
  readonly ratingMins: readonly number[];
}

interface Range {
  readonly min?: number | null;
  readonly max?: number | null;
}

/**
 * The products of `products` that pass every filter in `filters`, and the
 * facets of `products` under those filters.
 */
export function applyProductFilters(
  products: readonly Product[],
  filters: readonly ProductFilter[] | null | undefined,
  data: SandboxShopData,
): FilteredProducts {
  const entries = filters ?? [];
  const groups = groupFilters(entries, data);
  const withFacets = data.products.some(
    (product) => product.brand !== undefined || product.category_path !== undefined,
  );
  if (groups.length === 0 && !withFacets) return { products, filters: [] };

  const passed: Product[] = [];
  const facetCandidates = new Map<FacetKey, Candidate[]>(FACET_KEYS.map((key) => [key, []]));
  for (const product of products) {
    const candidate: Candidate = {
      product,
      rating: averageRating(data.reviewsByProductHandle.get(product.handle) ?? []),
    };
    const failed = failedGroupKeys(groups, candidate);
    if (failed.length === 0) passed.push(product);
    if (!withFacets || failed.length > 1) continue;
    for (const key of FACET_KEYS) {
      if (failed.length === 0 || failed[0] === key) facetCandidates.get(key)?.push(candidate);
    }
  }

  if (!withFacets) return { products: passed, filters: [] };
  const selection = selectedValues(entries);
  const facets = [
    categoryFacet(facetCandidates.get('categoryPath') ?? [], selection.categoryPaths),
    brandFacet(facetCandidates.get('brand') ?? [], selection.brands),
    priceFacet(facetCandidates.get('price') ?? []),
    ratingFacet(facetCandidates.get('rating') ?? [], selection.ratingMins),
  ];
  return {
    products: passed,
    filters: facets.filter((facet): facet is FilterNode => facet !== null),
  };
}

// ── Matching ──────────────────────────────────────────────────────────────

function groupFilters(
  filters: readonly ProductFilter[],
  data: SandboxShopData,
): readonly FilterGroup[] {
  const groups = new Map<string, Matcher[]>();
  const add = (key: string, matcher: Matcher): void => {
    const matchers = groups.get(key);
    if (matchers === undefined) groups.set(key, [matcher]);
    else matchers.push(matcher);
  };
  for (const filter of filters) {
    const { available, price, productType, productVendor, variantOption } = filter;
    const { brand, categoryPath, rating } = filter;
    if (isSet(available)) {
      add('available', ({ product }) => isAvailable(product, data) === available);
    }
    if (isSet(price)) {
      add('price', ({ product }) =>
        product.variants.some((variant) => inRange(variantPrice(variant), price)),
      );
    }
    if (isSet(productType))
      add('productType', ({ product }) => product.product_type === productType);
    if (isSet(productVendor))
      add('productVendor', ({ product }) => product.vendor === productVendor);
    if (isSet(variantOption)) {
      add(`variantOption:${variantOption.name}`, ({ product }) =>
        hasOptionValue(product, variantOption),
      );
    }
    if (isSet(brand)) add('brand', ({ product }) => product.brand === brand);
    if (isSet(categoryPath)) {
      add('categoryPath', ({ product }) => startsWith(product.category_path, categoryPath));
    }
    if (isSet(rating)) {
      add('rating', (candidate) => candidate.rating !== null && inRange(candidate.rating, rating));
    }
  }
  return [...groups].map(([key, matchers]) => ({ key, matchers }));
}

/** Keys of the groups that `candidate` fails; stops after the second one. */
function failedGroupKeys(groups: readonly FilterGroup[], candidate: Candidate): readonly string[] {
  const failed: string[] = [];
  for (const group of groups) {
    if (group.matchers.some((matches) => matches(candidate))) continue;
    failed.push(group.key);
    if (failed.length > 1) break;
  }
  return failed;
}

function isSet<T>(value: T | null | undefined): value is T {
  return value !== null && value !== undefined;
}

function isAvailable(product: Product, data: SandboxShopData): boolean {
  return product.variants.some((variant) =>
    resolveAvailableForSale(variant, data.inventoryByVariantId.get(variant.id)),
  );
}

function variantPrice(variant: ProductVariant): number {
  return Number.parseFloat(variant.price);
}

function inRange(value: number, range: Range): boolean {
  if (isSet(range.min) && value < range.min) return false;
  if (isSet(range.max) && value > range.max) return false;
  return true;
}

function hasOptionValue(product: Product, option: VariantOptionFilter): boolean {
  const position = product.options.find((o) => o.name === option.name)?.position;
  if (position === undefined) return false;
  return product.variants.some(
    (variant) => [variant.option1, variant.option2, variant.option3][position - 1] === option.value,
  );
}

function startsWith(path: readonly string[] | undefined, prefix: readonly string[]): boolean {
  if (path === undefined || path.length < prefix.length) return false;
  return prefix.every((segment, i) => path[i] === segment);
}

function selectedValues(filters: readonly ProductFilter[]): Selection {
  const brands: string[] = [];
  const categoryPaths: (readonly string[])[] = [];
  const ratingMins: number[] = [];
  for (const filter of filters) {
    if (isSet(filter.brand)) brands.push(filter.brand);
    if (isSet(filter.categoryPath)) categoryPaths.push(filter.categoryPath);
    if (isSet(filter.rating?.min) && !isSet(filter.rating.max)) ratingMins.push(filter.rating.min);
  }
  return { brands, categoryPaths, ratingMins };
}

// ── Facets ────────────────────────────────────────────────────────────────

/**
 * The category facet: the prefixes of each selected path and the children
 * of each selected path, or the departments when no path is selected.
 */
function categoryFacet(
  candidates: readonly Candidate[],
  selected: readonly (readonly string[])[],
): FilterNode | null {
  const counts = new Map<string, { readonly path: readonly string[]; count: number }>();
  for (const { product } of candidates) {
    const path = product.category_path ?? [];
    for (let depth = 1; depth <= path.length; depth++) {
      const prefix = path.slice(0, depth);
      const key = pathKey(prefix);
      const entry = counts.get(key);
      if (entry === undefined) counts.set(key, { path: prefix, count: 1 });
      else entry.count += 1;
    }
  }

  const values: FilterValueNode[] = [];
  const listed = new Set<string>();
  const push = (path: readonly string[], count: number): void => {
    const key = pathKey(path);
    if (listed.has(key)) return;
    listed.add(key);
    values.push({
      id: `filter.p.category_path.${key}`,
      label: path[path.length - 1] ?? '',
      count,
      input: JSON.stringify({ categoryPath: path }),
    });
  };
  for (const path of selected) {
    for (let depth = 1; depth <= path.length; depth++) {
      const prefix = path.slice(0, depth);
      push(prefix, counts.get(pathKey(prefix))?.count ?? 0);
    }
  }
  const parents = selected.length > 0 ? selected : [[]];
  for (const parent of parents) {
    const children = [...counts.values()].filter(
      (entry) => entry.path.length === parent.length + 1 && startsWith(entry.path, parent),
    );
    for (const child of sortByCount(children, (entry) => entry.path[parent.length] ?? '')) {
      push(child.path, child.count);
    }
  }
  return facet('filter.p.category_path', 'Category', 'LIST', values);
}

function brandFacet(
  candidates: readonly Candidate[],
  selected: readonly string[],
): FilterNode | null {
  const counts = new Map<string, number>(selected.map((brand) => [brand, 0]));
  for (const { product } of candidates) {
    if (product.brand !== undefined)
      counts.set(product.brand, (counts.get(product.brand) ?? 0) + 1);
  }
  const entries = sortByCount(
    [...counts].map(([brand, count]) => ({ brand, count })),
    (entry) => entry.brand,
  );
  return facet(
    'filter.p.brand',
    'Brand',
    'LIST',
    entries.map(({ brand, count }) => ({
      id: `filter.p.brand.${brand}`,
      label: brand,
      count,
      input: JSON.stringify({ brand }),
    })),
  );
}

/** The price facet: one value whose input spans every candidate price. */
function priceFacet(candidates: readonly Candidate[]): FilterNode | null {
  if (candidates.length === 0) return null;
  let max = 0;
  for (const { product } of candidates) {
    for (const variant of product.variants) max = Math.max(max, variantPrice(variant));
  }
  return facet('filter.v.price', 'Price', 'PRICE_RANGE', [
    {
      id: 'filter.v.price',
      label: 'Price',
      count: candidates.length,
      input: JSON.stringify({ price: { min: 0, max } }),
    },
  ]);
}

function ratingFacet(
  candidates: readonly Candidate[],
  selected: readonly number[],
): FilterNode | null {
  const values: FilterValueNode[] = [];
  for (const threshold of RATING_THRESHOLDS) {
    const count = candidates.filter(
      (candidate) => candidate.rating !== null && candidate.rating >= threshold,
    ).length;
    if (count === 0 && !selected.includes(threshold)) continue;
    values.push({
      id: `filter.p.rating.${threshold}`,
      label: threshold === 1 ? '1 star & up' : `${threshold} stars & up`,
      count,
      input: JSON.stringify({ rating: { min: threshold } }),
    });
  }
  return facet('filter.p.rating', 'Rating', 'LIST', values);
}

function facet(
  id: string,
  label: string,
  type: FilterType,
  values: readonly FilterValueNode[],
): FilterNode | null {
  return values.length === 0 ? null : { id, label, type, values };
}

/** `entries` with a count, most products first, then by label. */
function sortByCount<T extends { readonly count: number }>(
  entries: readonly T[],
  label: (entry: T) => string,
): readonly T[] {
  return [...entries].sort((a, b) => b.count - a.count || label(a).localeCompare(label(b)));
}

function pathKey(path: readonly string[]): string {
  return path.join(' > ');
}
