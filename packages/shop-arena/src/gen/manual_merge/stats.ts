/** Merges seed `stats.json` documents; structural counts come from the merged capabilities. */

import { z } from 'zod';

import type { Capabilities } from '../../explore/capabilities.js';
import { STATS_SOURCES, type Stats, capabilityCounts } from '../../explore/stats.js';

/**
 * A seed `stats.json`. A `null` number is unknown. A file from before
 * `source` and `sample_size` has neither field; it came from the Shopify
 * catalog endpoints and read `products_total` products.
 */
export const statsSchema = z.object({
  source: z.enum(STATS_SOURCES).optional(),
  sample_size: z.number().int().nonnegative().optional(),
  products_total: z.number().nullable(),
  collections_total: z.number().nullable(),
  products_per_collection: z
    .object({ avg: z.number(), median: z.number(), max: z.number() })
    .nullable(),
  price: z
    .object({
      min: z.number(),
      max: z.number(),
      median: z.number(),
      currency: z.string().nullable(),
    })
    .nullable(),
  products_with_variants_pct: z.number().nullable(),
  variant_axes_observed: z.array(z.string()),
  navigation_depth_max: z.number().nullable(),
  homepage_section_count: z.number().nullable(),
  info_pages_count: z.number().nullable(),
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

/** The values that are not `null`. */
function known<T>(values: readonly (T | null)[]): T[] {
  return values.filter((value): value is T => value !== null);
}

/** The rounded median of the known values, or `null` when no value is known. */
function knownMedian(values: readonly (number | null)[]): number | null {
  const numbers = known(values);
  return numbers.length === 0 ? null : Math.round(median(numbers));
}

/**
 * Merges the seed stats into one `Stats`.
 *
 * Each number comes from the seeds that know it, and it stays `null` when
 * no seed knows it, so an unknown number never becomes 0. The totals and
 * the products per collection come only from the seeds that read a
 * catalog endpoint, because an older observed-sample seed shows 0 for the
 * counts its site does not show. The merged `source` is `observed_sample`
 * when any seed is, and `sample_size` adds up the seeds.
 *
 * @throws Error when `seeds` is empty.
 */
export function mergeStats(seeds: readonly SeedStats[], capabilities: Capabilities): Stats {
  if (seeds.length === 0) {
    throw new Error('mergeStats requires at least one seed');
  }
  const catalog = seeds.filter((s) => s.source !== 'observed_sample');
  const perCollection = known(catalog.map((s) => s.products_per_collection));
  // An older seed with no price wrote 0 for each price number.
  const priced = known(seeds.map((s) => s.price)).filter((price) => price.max > 0);
  const variantShares = known(seeds.map((s) => s.products_with_variants_pct));
  const currency =
    capabilities.shop.currency ?? priced.find((price) => price.currency)?.currency ?? null;
  return {
    source: catalog.length === seeds.length ? 'catalog_endpoint' : 'observed_sample',
    // A seed with no `sample_size` is an older catalog seed, which knows its total.
    sample_size: seeds.reduce((sum, s) => sum + (s.sample_size ?? s.products_total ?? 0), 0),
    products_total: knownMedian(catalog.map((s) => s.products_total)),
    collections_total: knownMedian(catalog.map((s) => s.collections_total)),
    products_per_collection:
      perCollection.length === 0
        ? null
        : {
            avg: mean(perCollection.map((p) => p.avg)),
            median: median(perCollection.map((p) => p.median)),
            max: Math.max(...perCollection.map((p) => p.max)),
          },
    price:
      priced.length === 0
        ? null
        : {
            min: Math.min(...priced.map((price) => price.min)),
            max: Math.max(...priced.map((price) => price.max)),
            median: median(priced.map((price) => price.median)),
            currency,
          },
    products_with_variants_pct: variantShares.length === 0 ? null : mean(variantShares),
    variant_axes_observed: [...new Set(seeds.flatMap((s) => s.variant_axes_observed))],
    ...capabilityCounts(capabilities),
  };
}
