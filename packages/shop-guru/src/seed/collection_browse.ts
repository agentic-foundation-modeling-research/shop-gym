/**
 * Skill `browse`: open a collection, choose a product from it, add it to cart.
 */

import type { Task } from '@shop-gym/core';

import { type SeedContext, makeTaskId, skillRng } from './context.js';
import { collectionsWithMinProducts } from './filters.js';

export const SKILL = 'browse';
const MIN_PRODUCTS = 3;
const MAX_TITLES_IN_RUBRIC = 20;

export function generate(ctx: SeedContext, count: number): Task[] {
  const rng = skillRng(ctx, SKILL);
  const eligible = rng.shuffle(collectionsWithMinProducts(ctx.data.collections, MIN_PRODUCTS));
  return eligible.slice(0, count).map((collection, i) => {
    const members = collection.product_handles
      .map((handle) => ctx.data.productsByHandle.get(handle)?.title)
      .filter((title): title is string => title !== undefined)
      .slice(0, MAX_TITLES_IN_RUBRIC);
    return {
      id: makeTaskId(ctx.shop, SKILL, i + 1),
      shop: ctx.shop,
      skill: SKILL,
      goal: `Browse the "${collection.title}" collection, pick any product from it, choose a variant if the product has options, and add it to the cart.`,
      eval: [
        { type: 'state_check', path: '/carts', match: 'some', value: { lines: [{}] } },
        {
          type: 'llm_judge',
          rubric:
            `The cart contains a product from the "${collection.title}" collection. ` +
            `Products in that collection include: ${members.map((t) => `"${t}"`).join(', ')}.`,
        },
      ],
      source: 'seed',
      evidence: { collectionHandle: collection.handle },
    };
  });
}
