/**
 * Deterministic catalog and feature statistics derived from the prefetched
 * Shopify JSON endpoints and the merged capabilities.
 */

import { existsSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import type { Capabilities } from './capabilities.js';

export interface Stats {
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
  const axes: string[] = [];
  for (const product of products) {
    if (!Array.isArray(product.options)) continue;
    for (const option of product.options) {
      const raw = typeof option === 'string' ? option : isObject(option) ? option.name : null;
      if (typeof raw !== 'string') continue;
      const name = raw.trim().toLowerCase();
      if (name !== '' && !axes.includes(name)) axes.push(name);
    }
  }
  return axes;
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
 * Computes `Stats` from `prefetchDir` and `capabilities`.
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
    products_total: products.length,
    collections_total: collections.length,
    products_per_collection: {
      avg: perCollection.length === 0 ? 0 : sum(perCollection) / perCollection.length,
      median: median(perCollection),
      max: perCollection.length === 0 ? 0 : Math.max(...perCollection),
    },
    price: {
      min: prices.length === 0 ? 0 : Math.min(...prices),
      max: prices.length === 0 ? 0 : Math.max(...prices),
      median: median(prices),
      currency: capabilities.shop.currency ?? cartCurrency(prefetchDir),
    },
    products_with_variants_pct: products.length === 0 ? 0 : withVariants / products.length,
    variant_axes_observed: variantAxes(products),
    navigation_depth_max: capabilities.site_shell.nav_depth ?? 0,
    homepage_section_count: capabilities.homepage.section_count ?? 0,
    info_pages_count: capabilities.info_pages_present.length,
    feature_count: featureCount(capabilities),
  };
}
