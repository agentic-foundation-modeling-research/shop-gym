/**
 * Skill `order_history`: log in as a persona and report facts about the most
 * recent seeded order.
 */

import type { Task } from '@shop-gym/core';

import { type SeedContext, makeTaskId, skillRng } from './context.js';

export const SKILL = 'order_history';

export function generate(ctx: SeedContext, count: number): Task[] {
  const rng = skillRng(ctx, SKILL);
  const tasks: Task[] = [];
  for (const customer of rng.shuffle(ctx.data.customers)) {
    if (tasks.length >= count) break;
    const latest = ctx.data.orders
      .filter((o) => o.customer_id === customer.id)
      .sort((a, b) => b.processed_at.localeCompare(a.processed_at))[0];
    if (latest === undefined) continue;
    tasks.push({
      id: makeTaskId(ctx.shop, SKILL, tasks.length + 1),
      shop: ctx.shop,
      skill: SKILL,
      goal:
        'You are already signed in. Open your order history and report the order number and ' +
        'the total amount paid for your most recent order.',
      setup: { login: String(customer.id) },
      eval: [{ type: 'string_match', mustInclude: [String(latest.id), latest.total_price] }],
      source: 'seed',
      evidence: { customerId: customer.id, orderId: latest.id },
    });
  }
  return tasks;
}
