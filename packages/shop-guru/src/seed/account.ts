/**
 * Skill `account`: log in as a persona and read back profile details.
 */

import type { Task } from '@shop-gym/core';

import { type SeedContext, makeTaskId, skillRng } from './context.js';

export const SKILL = 'account';

export function generate(ctx: SeedContext, count: number): Task[] {
  const rng = skillRng(ctx, SKILL);
  const personas = rng.shuffle(
    ctx.data.customers.filter((c) => c.addresses.some((a) => a.id === c.default_address_id)),
  );
  return personas.slice(0, count).map((customer, i) => {
    const address = customer.addresses.find((a) => a.id === customer.default_address_id);
    const city = address?.city ?? '';
    return {
      id: makeTaskId(ctx.shop, SKILL, i + 1),
      shop: ctx.shop,
      skill: SKILL,
      goal:
        'You are already signed in. Open your account page and report the email address on ' +
        'the account and the city of your default shipping address.',
      setup: { login: String(customer.id) },
      eval: [{ type: 'string_match', mustInclude: [customer.email, city] }],
      source: 'seed',
      evidence: { customerId: customer.id },
    };
  });
}
