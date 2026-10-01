/**
 * Skill `e2e`: a multi-step shopping journey composed from one collection.
 *
 * v1 authored these with an LLM; v2 composes them deterministically so the
 * seed set is reproducible: two products from one collection go into the
 * cart, one of them at quantity 2, and the cart is reviewed.
 */

import type { Task } from '@shop-gym/core';

import { type SeedContext, makeTaskId, skillRng } from './context.js';
import { collectionsWithMinProducts, isTaskCandidate } from './filters.js';

export const SKILL = 'e2e';
const MIN_PRODUCTS = 3;

export function generate(ctx: SeedContext, count: number): Task[] {
  const rng = skillRng(ctx, SKILL);
  const candidates = rng.shuffle(collectionsWithMinProducts(ctx.data.collections, MIN_PRODUCTS));
  const tasks: Task[] = [];
  for (const collection of candidates) {
    if (tasks.length >= count) break;
    const members = collection.product_handles
      .map((handle) => ctx.data.productsByHandle.get(handle))
      .filter((p) => p !== undefined && isTaskCandidate(p));
    const [first, second] = rng.shuffle(members);
    if (first === undefined || second === undefined) continue;
    tasks.push({
      id: makeTaskId(ctx.shop, SKILL, tasks.length + 1),
      shop: ctx.shop,
      skill: SKILL,
      goal:
        `You are shopping in the "${collection.title}" collection. Add any variant of ` +
        `"${first.title}" and any variant of "${second.title}" to the cart, then change the ` +
        `quantity of "${first.title}" to 2. Finish on the cart page with both products in it.`,
      eval: [
        {
          type: 'locator_probe',
          url: 'last',
          locator: 'body',
          required: { mustInclude: [first.title, second.title] },
        },
        { type: 'url_match', url: '/cart', rule: 'contains' },
        {
          type: 'state_check',
          path: '/carts',
          match: 'some',
          value: { lines: [{ quantity: 2 }, {}] },
        },
      ],
      source: 'seed',
      evidence: {
        collectionHandle: collection.handle,
        productHandles: [first.handle, second.handle],
      },
    });
  }
  return tasks;
}
