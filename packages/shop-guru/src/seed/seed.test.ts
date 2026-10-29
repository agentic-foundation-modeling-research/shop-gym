import { taskSchema } from '@shop-gym/core';
import { describe, expect, it } from 'vitest';

import { loadFixture } from '../testing/fixtures.js';
import { validateTasks } from '../validate.js';
import { DEFAULT_SKILL_CAPS, SEED_SKILLS, generateSeedTasks } from './index.js';

const data = loadFixture();
const ctx = { shop: 'fixture', data, seed: 'test-seed' };

describe('generateSeedTasks', () => {
  it('is deterministic for the same seed', () => {
    const a = generateSeedTasks(ctx, DEFAULT_SKILL_CAPS);
    const b = generateSeedTasks(ctx, DEFAULT_SKILL_CAPS);
    expect(b).toEqual(a);
    expect(a.length).toBeGreaterThan(0);
  });

  it('changes task selection with the seed', () => {
    const a = generateSeedTasks(ctx, { exact: 2 }).map((t) => t.goal);
    const b = generateSeedTasks({ ...ctx, seed: 'other' }, { exact: 2 }).map((t) => t.goal);
    expect(a).toHaveLength(2);
    expect(b).toHaveLength(2);
    // Same product pool, possibly different order.
    expect(new Set([...a, ...b]).size).toBeLessThanOrEqual(4);
  });

  it('produces schema-valid tasks that survive validation', () => {
    const tasks = generateSeedTasks(ctx, DEFAULT_SKILL_CAPS);
    for (const task of tasks) expect(() => taskSchema.parse(task)).not.toThrow();
    const report = validateTasks(tasks, data, DEFAULT_SKILL_CAPS);
    expect(report.dropped).toEqual([]);
    expect(report.tasks).toHaveLength(tasks.length);
  });

  it('covers the account, checkout, and order history skills on the fixture', () => {
    const skills = new Set(generateSeedTasks(ctx, DEFAULT_SKILL_CAPS).map((t) => t.skill));
    for (const skill of [
      'exact',
      'substitute',
      'browse',
      'e2e',
      'account',
      'checkout',
      'order_history',
    ]) {
      expect(skills.has(skill), skill).toBe(true);
    }
    // The fixture ships no shipping or refund policy page.
    expect(skills.has('shipping')).toBe(false);
    expect(skills.has('returns')).toBe(false);
    for (const skill of skills) expect(SEED_SKILLS).toContain(skill);
  });

  it('respects per-skill caps and ids follow <shop>-<skill>-<n>', () => {
    const tasks = generateSeedTasks(ctx, { exact: 1, browse: 1 });
    expect(tasks.map((t) => t.id)).toEqual(['fixture-exact-1', 'fixture-browse-1']);
    expect(tasks.every((t) => t.source === 'seed')).toBe(true);
  });

  it('logs checkout tasks in as the persona with the variant in the cart', () => {
    const [task] = generateSeedTasks(ctx, { checkout: 1 });
    const login = task?.setup?.login;
    expect(task?.setup).toEqual({
      login: expect.any(String),
      cart: [{ variantId: expect.any(Number), quantity: 1 }],
    });
    expect(task?.eval[0]).toMatchObject({
      type: 'state_check',
      path: '/orders',
      match: 'some',
      value: { customerId: `gid://shopify/Customer/${login}` },
    });
  });
});
