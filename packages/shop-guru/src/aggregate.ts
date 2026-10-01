/**
 * Rolls a set of episode results up into `aggregate.json`.
 */

import { addUsage } from '@shop-gym/agent';
import {
  type Aggregate,
  type AggregateBucket,
  type EpisodeResult,
  aggregateSchema,
} from '@shop-gym/core';

import { ZERO_USAGE } from './usage.js';

function bucket(results: readonly EpisodeResult[]): AggregateBucket {
  const passed = results.filter((r) => r.passed).length;
  return {
    total: results.length,
    passed,
    passRate: results.length === 0 ? 0 : passed / results.length,
  };
}

function groupBy(
  results: readonly EpisodeResult[],
  key: (r: EpisodeResult) => string,
): Record<string, AggregateBucket> {
  const groups = new Map<string, EpisodeResult[]>();
  for (const result of results) {
    groups.set(key(result), [...(groups.get(key(result)) ?? []), result]);
  }
  return Object.fromEntries(
    [...groups].sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, bucket(v)]),
  );
}

/** Counts, pass rates by skill and by shop, and summed usage. */
export function aggregate(results: readonly EpisodeResult[]): Aggregate {
  const overall = bucket(results);
  return aggregateSchema.parse({
    total: overall.total,
    passed: overall.passed,
    failed: overall.total - overall.passed,
    errors: results.filter((r) => r.status === 'error').length,
    passRate: overall.passRate,
    by_skill: groupBy(results, (r) => r.skill),
    by_shop: groupBy(results, (r) => r.shop),
    usage: results.reduce((sum, r) => addUsage(sum, r.usage), ZERO_USAGE),
  });
}
