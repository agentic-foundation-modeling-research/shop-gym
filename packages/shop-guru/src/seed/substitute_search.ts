/**
 * Skill `substitute`: find a product similar to a named one and add it.
 *
 * Uses the same products as `exact` so the two skills are paired; only the
 * intent differs. Similarity is judged by an LLM; the cart having a line is
 * checked programmatically.
 */

import type { Task } from '@shop-gym/core';

import { type SeedContext, makeTaskId } from './context.js';
import { pickExactProducts } from './exact_search.js';

export const SKILL = 'substitute';

export function generate(ctx: SeedContext, count: number): Task[] {
  return pickExactProducts(ctx, count).map((product, i) => ({
    id: makeTaskId(ctx.shop, SKILL, i + 1),
    shop: ctx.shop,
    skill: SKILL,
    goal: `Find a product that is similar to "${product.title}" but is not that exact product, and add any variant of it to the cart.`,
    eval: [
      { type: 'state_check', path: '/carts', match: 'some', value: { lines: [{}] } },
      {
        type: 'llm_judge',
        rubric: `The cart contains exactly one product. It is not "${product.title}" but serves a comparable purpose (same category or use).`,
      },
    ],
    source: 'seed',
    evidence: { productHandle: product.handle },
  }));
}
