/** Merges seed `stats.json` documents; structural counts come from the merged capabilities. */

import { z } from 'zod';

import type { Capabilities } from '../../explore/capabilities.js';
import { STATS_SOURCES, type Stats } from '../../explore/stats.js';

/**
 * A seed `stats.json`. A file from before `source` and `sample_size` has
 * neither field; it came from the Shopify catalog endpoints and read
 * `products_total` products.
 */
export const statsSchema = z.object({
  source: z.enum(STATS_SOURCES).optional(),
  sample_size: z.number().int().nonnegative().optional(),
  products_total: z.number(),
  collections_total: z.number(),
  products_per_collection: z.object({ avg: z.number(), median: z.number(), max: z.number() }),
  price: z.object({ min: z.number(), max: z.number(), median: z.number(), currency: z.string() }),
  products_with_variants_pct: z.number(),
  variant_axes_observed: z.array(z.string()),
  navigation_depth_max: z.number(),
  homepage_section_count: z.number(),
  info_pages_count: z.number(),
  feature_count: z.number(),
});

export type SeedStats = z.infer<typeof statsSchema>;

function median(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? (sorted[mid] as number)
    : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

function mean(values: readonly number[]): number {
  return values.length === 0 ? 0 : values.reduce((a, b) => a + b, 0) / values.length;
}

/** Counts true booleans and list lengths anywhere in the document. */
function countFeatures(value: unknown): number {
  if (value === true) return 1;
  if (Array.isArray(value)) return value.length;
  if (typeof value === 'object' && value !== null) {
    return Object.values(value).reduce<number>((sum, v) => sum + countFeatures(v), 0);
  }
  return 0;
}

/**
 * Merges the seed stats into one `Stats`.
 *
 * The totals and the products per collection come only from the seeds
 * that read a catalog endpoint, because an observed-sample seed shows 0
 * for the counts its site does not show. The merged `source` is
 * `observed_sample` when any seed is, and `sample_size` adds up the seeds.
 *
 * @throws Error when `seeds` is empty.
 */
export function mergeStats(seeds: readonly SeedStats[], capabilities: Capabilities): Stats {
  if (seeds.length === 0) {
    throw new Error('mergeStats requires at least one seed');
  }
  const catalog = seeds.filter((s) => s.source !== 'observed_sample');
  const priced = seeds.filter((s) => s.price.max > 0);
  const currency =
    capabilities.shop.currency ?? seeds.find((s) => s.price.currency !== '')?.price.currency ?? '';
  return {
    source: catalog.length === seeds.length ? 'catalog_endpoint' : 'observed_sample',
    sample_size: seeds.reduce((sum, s) => sum + (s.sample_size ?? s.products_total), 0),
    products_total: Math.round(median(catalog.map((s) => s.products_total))),
    collections_total: Math.round(median(catalog.map((s) => s.collections_total))),
    products_per_collection: {
      avg: mean(catalog.map((s) => s.products_per_collection.avg)),
      median: median(catalog.map((s) => s.products_per_collection.median)),
      max: Math.max(0, ...catalog.map((s) => s.products_per_collection.max)),
    },
    price:
      priced.length === 0
        ? { min: 0, max: 0, median: 0, currency }
        : {
            min: Math.min(...priced.map((s) => s.price.min)),
            max: Math.max(...priced.map((s) => s.price.max)),
            median: median(priced.map((s) => s.price.median)),
            currency,
          },
    products_with_variants_pct: mean(seeds.map((s) => s.products_with_variants_pct)),
    variant_axes_observed: [...new Set(seeds.flatMap((s) => s.variant_axes_observed))],
    navigation_depth_max: capabilities.site_shell.nav_depth ?? 0,
    homepage_section_count: capabilities.homepage.section_count ?? 0,
    info_pages_count: capabilities.info_pages_present.length,
    feature_count: countFeatures(capabilities),
  };
}
