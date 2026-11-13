/**
 * "Also bought" lists from co-purchases: two products are related when at
 * least `minBuyers` users bought both. Products and users are array
 * indexes, as in the sampling tallies.
 */

import { compareStrings } from './sample.js';

/** Purchases as parallel arrays: entry `i` is one purchase of `products[i]` by `users[i]`. */
export interface Purchases {
  readonly users: readonly number[];
  readonly products: readonly number[];
}

export interface AlsoBoughtOptions {
  /** A related product shares at least this many buyers. */
  readonly minBuyers: number;
  /** At most this many related products per product. */
  readonly max: number;
}

/**
 * For each product, the other products that share the most buyers. A user
 * who buys one product twice counts once.
 *
 * @param productIds Product ids by index; ties go to the smaller id.
 * @returns Related product indexes by product index, the most shared
 *   buyers first. A product without related products has no entry.
 */
export function alsoBought(
  purchases: Purchases,
  productIds: readonly string[],
  options: AlsoBoughtOptions,
): Map<number, number[]> {
  const shared = countSharedBuyers(purchases, productIds.length);
  const neighbors = new Map<number, { product: number; buyers: number }[]>();
  const add = (product: number, other: number, buyers: number): void => {
    const list = neighbors.get(product);
    if (list === undefined) neighbors.set(product, [{ product: other, buyers }]);
    else list.push({ product: other, buyers });
  };
  const count = productIds.length;
  for (const [pair, buyers] of shared) {
    if (buyers < options.minBuyers) continue;
    const a = Math.floor(pair / count);
    const b = pair % count;
    add(a, b, buyers);
    add(b, a, buyers);
  }
  const related = new Map<number, number[]>();
  for (const [product, list] of neighbors) {
    list.sort(
      (x, y) =>
        y.buyers - x.buyers ||
        compareStrings(productIds[x.product] ?? '', productIds[y.product] ?? ''),
    );
    related.set(
      product,
      list.slice(0, options.max).map((entry) => entry.product),
    );
  }
  return related;
}

/**
 * The number of distinct buyers of each pair of products, keyed by
 * `a * productCount + b` with `a < b`. The purchases are sorted by user in
 * one typed array, so no per-user set is kept.
 */
function countSharedBuyers(purchases: Purchases, productCount: number): Map<number, number> {
  const keys = new Float64Array(purchases.users.length);
  purchases.users.forEach((user, i) => {
    keys[i] = user * productCount + (purchases.products[i] ?? 0);
  });
  keys.sort();
  const shared = new Map<number, number>();
  const bought: number[] = [];
  let user = -1;
  const countPairs = (): void => {
    for (let i = 0; i < bought.length; i += 1) {
      for (let j = i + 1; j < bought.length; j += 1) {
        // `bought` is sorted, so `bought[i] < bought[j]`.
        const pair = (bought[i] ?? 0) * productCount + (bought[j] ?? 0);
        shared.set(pair, (shared.get(pair) ?? 0) + 1);
      }
    }
  };
  for (const key of keys) {
    const keyUser = Math.floor(key / productCount);
    const product = key % productCount;
    if (keyUser !== user) {
      countPairs();
      bought.length = 0;
      user = keyUser;
    }
    if (bought.at(-1) !== product) bought.push(product);
  }
  countPairs();
  return shared;
}
