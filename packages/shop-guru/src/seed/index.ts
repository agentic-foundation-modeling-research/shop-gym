/**
 * Seed task generation: deterministic tasks from a SandboxShop dataset.
 *
 * Every skill has one pure generator. `generateSeedTasks` runs them all with
 * per-skill caps and returns the tasks in a stable order.
 */

import type { Task } from '@shop-gym/core';

import * as account from './account.js';
import * as checkout from './checkout.js';
import * as collectionBrowse from './collection_browse.js';
import * as collectionFilter from './collection_filter.js';
import type { SeedContext } from './context.js';
import * as e2e from './e2e.js';
import * as exactSearch from './exact_search.js';
import * as findPolicy from './find_policy.js';
import * as orderHistory from './order_history.js';
import * as substituteSearch from './substitute_search.js';

export type { SeedContext, SeedGenerator } from './context.js';
export { makeTaskId } from './context.js';

/** Every seed skill with its generator. Order is the output order. */
const GENERATORS: readonly {
  readonly skill: string;
  readonly generate: (ctx: SeedContext, count: number) => Task[];
}[] = [
  { skill: 'exact', generate: exactSearch.generate },
  { skill: 'substitute', generate: substituteSearch.generate },
  { skill: 'browse', generate: collectionBrowse.generate },
  { skill: 'filter', generate: collectionFilter.generate },
  { skill: 'shipping', generate: (ctx) => findPolicy.generateShipping(ctx) },
  { skill: 'returns', generate: (ctx) => findPolicy.generateReturns(ctx) },
  { skill: 'e2e', generate: e2e.generate },
  { skill: 'account', generate: account.generate },
  { skill: 'checkout', generate: checkout.generate },
  { skill: 'order_history', generate: orderHistory.generate },
];

/** Skill names in generation order. */
export const SEED_SKILLS: readonly string[] = GENERATORS.map((g) => g.skill);

/** Default per-skill task counts; mirror the v1 generator defaults. */
export const DEFAULT_SKILL_CAPS: Readonly<Record<string, number>> = {
  exact: 5,
  substitute: 5,
  browse: 5,
  filter: 3,
  shipping: 1,
  returns: 1,
  e2e: 3,
  account: 3,
  checkout: 3,
  order_history: 3,
};

/**
 * Run the generators named in `caps`, each asked for at most its cap. Skills
 * missing from `caps` are skipped.
 */
export function generateSeedTasks(
  ctx: SeedContext,
  caps: Readonly<Record<string, number>>,
): Task[] {
  const tasks: Task[] = [];
  for (const { skill, generate } of GENERATORS) {
    const count = caps[skill] ?? 0;
    if (count > 0) tasks.push(...generate(ctx, count));
  }
  return tasks;
}
