/**
 * User-first seeded sampling of a Source bundle, over compact per-user and
 * per-product tallies that an adapter collects in one pass over its source.
 * Users and products are array indexes into the adapter's id lists.
 *
 * 1. Pick `users` modeled users at random among the users with at least
 *    `minEventsBefore` User events before the cutoff and at least one
 *    purchase after it.
 * 2. Keep every product in the histories of the modeled users, before and
 *    after the cutoff.
 * 3. Fill up to `products` with other products of the same category paths,
 *    the most reviewed before the cutoff first.
 * 4. Keep the reviews of the kept products. With `reviewsPerProduct`, keep
 *    every review of a modeled user and a seeded choice of the others, at
 *    most `reviewsPerProduct` in all when the modeled users have fewer.
 * 5. Drop the products first seen after the cutoff, unless a modeled user
 *    buys them after the cutoff (they are Task targets).
 */

import { seededRandom } from '../gen/data_synth/ids.js';

export interface UserTallies {
  readonly userIds: readonly string[];
  /** User events before the cutoff, by user index. */
  readonly eventsBefore: readonly number[];
  /** Purchase events at or after the cutoff, by user index. */
  readonly purchasesAfter: readonly number[];
}

export interface ProductStats {
  readonly id: string;
  /** Category path key; empty when the product has no category. */
  readonly category: string;
  /** Time of the first review or event in the source, ms since epoch. */
  readonly firstSeenMs: number;
  /** Reviews before the cutoff in the source. */
  readonly reviewsBefore: number;
}

export interface UserPick {
  /** Users that meet rule 1. */
  readonly candidates: number;
  /** User indexes of the modeled users, in id order. */
  readonly users: readonly number[];
}

export interface ProductPick {
  /** Product indexes of the kept products, in id order. */
  readonly products: readonly number[];
  /** Products in the histories of the modeled users that were kept. */
  readonly history: number;
  /** Products in the histories that rule 5 dropped. */
  readonly droppedAfterCutoff: number;
  /** Products added by rule 3. */
  readonly filler: number;
}

/** Rule 1: the seeded choice does not depend on the order of the source. */
export function pickUsers(
  tallies: UserTallies,
  options: { readonly users: number; readonly minEventsBefore: number; readonly seed: string },
): UserPick {
  const candidates: number[] = [];
  tallies.userIds.forEach((_, user) => {
    if (
      (tallies.eventsBefore[user] ?? 0) >= options.minEventsBefore &&
      (tallies.purchasesAfter[user] ?? 0) >= 1
    ) {
      candidates.push(user);
    }
  });
  const byId = (a: number, b: number): number =>
    compareStrings(tallies.userIds[a] ?? '', tallies.userIds[b] ?? '');
  candidates.sort(byId);
  const picked = seededSample(candidates, options.users, seededRandom(`${options.seed}\0users`));
  return { candidates: candidates.length, users: picked.sort(byId) };
}

/** Rules 2, 3 and 5. */
export function pickProducts(
  stats: readonly ProductStats[],
  histories: {
    /** Products in the events of the modeled users. */
    readonly history: ReadonlySet<number>;
    /** Products that the modeled users buy at or after the cutoff. */
    readonly targets: ReadonlySet<number>;
  },
  options: { readonly products: number; readonly cutoffMs: number },
): ProductPick {
  const seenBefore = (product: number): boolean =>
    (stats[product]?.firstSeenMs ?? Number.POSITIVE_INFINITY) < options.cutoffMs;
  const kept = [...histories.history].filter(
    (product) => seenBefore(product) || histories.targets.has(product),
  );
  const keptSet = new Set(kept);
  const categories = new Set(kept.map((product) => stats[product]?.category ?? ''));
  categories.delete('');
  const pool: number[] = [];
  stats.forEach((product, index) => {
    if (!keptSet.has(index) && seenBefore(index) && categories.has(product.category)) {
      pool.push(index);
    }
  });
  pool.sort(
    (a, b) =>
      (stats[b]?.reviewsBefore ?? 0) - (stats[a]?.reviewsBefore ?? 0) ||
      compareStrings(stats[a]?.id ?? '', stats[b]?.id ?? ''),
  );
  const filler = pool.slice(0, Math.max(0, options.products - kept.length));
  const products = [...kept, ...filler].sort((a, b) =>
    compareStrings(stats[a]?.id ?? '', stats[b]?.id ?? ''),
  );
  return {
    products,
    history: kept.length,
    droppedAfterCutoff: histories.history.size - kept.length,
    filler: filler.length,
  };
}

/**
 * Rule 4 with a cap: the reviews by other users of one product that are
 * kept beside `modeled` reviews by modeled users.
 *
 * @param others Review indexes by users that are not modeled, in source order.
 * @returns The kept review indexes, in source order.
 */
export function capReviews(
  productId: string,
  others: readonly number[],
  modeled: number,
  options: { readonly cap: number; readonly seed: string },
): readonly number[] {
  const quota = Math.max(0, options.cap - modeled);
  if (others.length <= quota) return others;
  const rng = seededRandom(`${options.seed}\0reviews\0${productId}`);
  return seededSample(others, quota, rng).sort((a, b) => a - b);
}

/** `n` items chosen at random with a partial Fisher-Yates shuffle of a copy. */
function seededSample<T>(items: readonly T[], n: number, rng: () => number): T[] {
  const copy = [...items];
  const count = Math.min(n, copy.length);
  for (let i = 0; i < count; i += 1) {
    // `i` and `j` are both below `copy.length`, so both name elements.
    const j = i + Math.floor(rng() * (copy.length - i));
    const a = copy[i] as T;
    copy[i] = copy[j] as T;
    copy[j] = a;
  }
  return copy.slice(0, count);
}

/** Code unit order, the same on every machine and locale. */
export function compareStrings(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}
