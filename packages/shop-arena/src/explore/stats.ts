/**
 * Deterministic catalog and feature statistics for `stats.json`.
 *
 * On a Shopify shop the catalog numbers come from the prefetched Shopify
 * JSON endpoints (`source: catalog_endpoint`). On a generic site they come
 * from the product observation fragments of the executors
 * (`source: observed_sample`), and the totals that such a site does not
 * show stay 0. `sample_size` is the number of products that the numbers
 * come from. The feature counts come from the merged capabilities on both
 * paths.
 */

import { existsSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import type { Capabilities } from './capabilities.js';
import { type ProductObservation, readObservations } from './observations.js';

/** Where the catalog numbers of a `stats.json` come from. */
export const STATS_SOURCES = ['catalog_endpoint', 'observed_sample'] as const;
export type StatsSource = (typeof STATS_SOURCES)[number];

export interface Stats {
  readonly source: StatsSource;
  /** The number of products that the catalog numbers come from. */
  readonly sample_size: number;
  readonly products_total: number;
  readonly collections_total: number;
  readonly products_per_collection: { avg: number; median: number; max: number };
  readonly price: { min: number; max: number; median: number; currency: string };
  readonly products_with_variants_pct: number;
  readonly variant_axes_observed: readonly string[];
  readonly navigation_depth_max: number;
  readonly homepage_section_count: number;
  readonly info_pages_count: number;
  readonly feature_count: number;
}

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Loads `{"<key>": [...]}` from `<dir>/<name>`, keeping only object items. */
function loadArray(dir: string, name: string, key: string): JsonObject[] {
  const path = join(dir, name);
  if (!existsSync(path)) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    throw new Error(`${name} is not valid JSON`);
  }
  if (!isObject(parsed) || !Array.isArray(parsed[key])) return [];
  return parsed[key].filter(isObject);
}

function median(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  // Both indices are in range for a non-empty array.
  return sorted.length % 2 === 1
    ? (sorted[mid] as number)
    : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

function toPrice(value: unknown): number | null {
  if (typeof value === 'boolean') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string') {
    const parsed = Number(value.trim());
    return value.trim() !== '' && Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function variantAxes(products: readonly JsonObject[]): string[] {
  const names: string[] = [];
  for (const product of products) {
    if (!Array.isArray(product.options)) continue;
    for (const option of product.options) {
      const raw = typeof option === 'string' ? option : isObject(option) ? option.name : null;
      if (typeof raw === 'string') names.push(raw);
    }
  }
  return normalizeAxes(names);
}

/** The axis names trimmed and lowercased, without empty names or repeats, in first-seen order. */
function normalizeAxes(names: readonly string[]): string[] {
  return [...new Set(names.map((name) => name.trim().toLowerCase()).filter((name) => name !== ''))];
}

/** Counts truthy booleans plus list lengths, recursively. */
function featureCount(value: unknown): number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (Array.isArray(value)) return value.length;
  if (isObject(value)) return Object.values(value).reduce<number>((n, v) => n + featureCount(v), 0);
  return 0;
}

function cartCurrency(prefetchDir: string): string {
  const path = join(prefetchDir, 'cart.js');
  if (!existsSync(path)) return '';
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'));
    return isObject(parsed) && typeof parsed.currency === 'string' ? parsed.currency : '';
  } catch {
    return '';
  }
}

/**
 * Computes `Stats` from the Shopify catalog files under `prefetchDir` and
 * `capabilities`. `sample_size` is the number of products read.
 *
 * @throws Error when `prefetchDir` is missing or a JSON file is malformed.
 */
export function computeStats(prefetchDir: string, capabilities: Capabilities): Stats {
  if (!existsSync(prefetchDir) || !statSync(prefetchDir).isDirectory()) {
    throw new Error(`prefetch directory not found: ${prefetchDir}`);
  }
  const products = loadArray(prefetchDir, 'products.json', 'products');
  const collections = loadArray(prefetchDir, 'collections.json', 'collections');

  const perCollection = collections
    .map((collection) => collection.products_count)
    .filter(
      (count): count is number =>
        typeof count === 'number' && Number.isInteger(count) && count >= 0,
    );
  const prices: number[] = [];
  let withVariants = 0;
  for (const product of products) {
    const variants = Array.isArray(product.variants) ? product.variants : [];
    if (variants.length > 1) withVariants += 1;
    for (const variant of variants) {
      const price = isObject(variant) ? toPrice(variant.price) : null;
      if (price !== null) prices.push(price);
    }
  }
  const sum = (values: readonly number[]) => values.reduce((a, b) => a + b, 0);

  return {
    source: 'catalog_endpoint',
    sample_size: products.length,
    products_total: products.length,
    collections_total: collections.length,
    products_per_collection: {
      avg: perCollection.length === 0 ? 0 : sum(perCollection) / perCollection.length,
      median: median(perCollection),
      max: perCollection.length === 0 ? 0 : Math.max(...perCollection),
    },
    price: priceStats(prices, capabilities.shop.currency ?? cartCurrency(prefetchDir)),
    products_with_variants_pct: products.length === 0 ? 0 : withVariants / products.length,
    variant_axes_observed: variantAxes(products),
    ...capabilityCounts(capabilities),
  };
}

/**
 * The currency that most observations use; on a tie, the one seen first.
 * Undefined when there are no observations.
 */
function mainCurrency(observations: readonly ProductObservation[]): string | undefined {
  const counts = new Map<string, number>();
  for (const { currency } of observations) counts.set(currency, (counts.get(currency) ?? 0) + 1);
  let main: string | undefined;
  let mainCount = 0;
  for (const [currency, count] of counts) {
    if (count > mainCount) [main, mainCount] = [currency, count];
  }
  return main;
}

/**
 * Computes `Stats` from the product observation fragments under `partsDir`
 * and `capabilities`, for a site with no catalog endpoint.
 *
 * The sample has one observation for each product page, so a page that
 * more than one task recorded counts once. Every observation counts in
 * `sample_size`, the variant share and the variant axes. The axes are
 * sorted, because the sample has no page order. The price numbers use only
 * the observations in the main currency, so that one currency labels them.
 * Products total, collections total and products per collection stay 0,
 * because the site does not show them.
 *
 * @throws Error when a fragment is not valid JSON or does not match the schema.
 */
export function computeObservedStats(partsDir: string, capabilities: Capabilities): Stats {
  const observations = readObservations(partsDir);
  const currency = mainCurrency(observations);
  const prices = observations
    .filter((observation) => observation.currency === currency)
    .map((observation) => observation.price);
  const withVariants = observations.filter((observation) => observation.has_variants).length;
  return {
    source: 'observed_sample',
    sample_size: observations.length,
    products_total: 0,
    collections_total: 0,
    products_per_collection: { avg: 0, median: 0, max: 0 },
    price: priceStats(prices, currency ?? capabilities.shop.currency ?? ''),
    products_with_variants_pct: observations.length === 0 ? 0 : withVariants / observations.length,
    variant_axes_observed: normalizeAxes(observations.flatMap((o) => o.variant_axes)).sort(),
    ...capabilityCounts(capabilities),
  };
}

function priceStats(prices: readonly number[], currency: string): Stats['price'] {
  return {
    min: prices.length === 0 ? 0 : Math.min(...prices),
    max: prices.length === 0 ? 0 : Math.max(...prices),
    median: median(prices),
    currency,
  };
}

/** The structural counts that both paths take from the merged capabilities. */
function capabilityCounts(
  capabilities: Capabilities,
): Pick<
  Stats,
  'navigation_depth_max' | 'homepage_section_count' | 'info_pages_count' | 'feature_count'
> {
  return {
    navigation_depth_max: capabilities.site_shell.nav_depth ?? 0,
    homepage_section_count: capabilities.homepage.section_count ?? 0,
    info_pages_count: capabilities.info_pages_present.length,
    feature_count: featureCount(capabilities),
  };
}
