/**
 * Skill `exact`: find a named product and add any variant to the cart.
 *
 * Selection favours cross-category diversity: each `product_type` is used at
 * most once in a first pass, then the remaining candidates top up `count`.
 */

import type { Task } from '@shop-gym/core';
import type { Product } from '@shop-gym/shop-backend';

import { type SeedContext, makeTaskId, skillRng } from './context.js';
import { isTaskCandidate } from './filters.js';

export const SKILL = 'exact';

/** The products the `exact` and `substitute` generators share, in task order. */
export function pickExactProducts(ctx: SeedContext, count: number): Product[] {
  const rng = skillRng(ctx, SKILL);
  const candidates = rng.shuffle(ctx.data.products.filter(isTaskCandidate));

  const picked: Product[] = [];
  const seenTypes = new Set<string>();
  for (const product of candidates) {
    if (picked.length >= count) break;
    const type = product.product_type.trim().toLowerCase();
    if (type !== '' && seenTypes.has(type)) continue;
    picked.push(product);
    if (type !== '') seenTypes.add(type);
  }
  for (const product of candidates) {
    if (picked.length >= count) break;
    if (!picked.includes(product)) picked.push(product);
  }
  return picked;
}

export function generate(ctx: SeedContext, count: number): Task[] {
  return pickExactProducts(ctx, count).map((product, i) => ({
    id: makeTaskId(ctx.shop, SKILL, i + 1),
    shop: ctx.shop,
    skill: SKILL,
    goal: `Find the product named "${product.title}" and add any variant of it to the cart.`,
    eval: [
      {
        type: 'locator_probe',
        url: '/cart',
        locator: 'body',
        required: { mustInclude: [product.title] },
      },
    ],
    source: 'seed',
    evidence: { productHandle: product.handle },
  }));
}
