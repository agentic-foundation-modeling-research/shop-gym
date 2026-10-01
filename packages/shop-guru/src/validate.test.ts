import type { Task } from '@shop-gym/core';
import { describe, expect, it } from 'vitest';

import { loadFixture } from './testing/fixtures.js';
import { validateTasks } from './validate.js';

const data = loadFixture();

function task(overrides: Partial<Task> & { id: string }): Task {
  return {
    shop: 'fixture',
    skill: 'exact',
    goal: `goal for ${overrides.id}`,
    eval: [{ type: 'url_match', url: '/cart', rule: 'contains' }],
    source: 'seed',
    ...overrides,
  };
}

describe('validateTasks', () => {
  it('keeps tasks whose references resolve', () => {
    const ok = task({
      id: 'ok',
      setup: { login: '1', cart: [{ variantId: 47642512195758, quantity: 1 }] },
      eval: [
        { type: 'url_match', url: '/collections/dog-essentials', rule: 'prefix' },
        {
          type: 'locator_probe',
          url: '/products/aislearena-anti-tick-collar',
          locator: 'h1',
          required: { mustInclude: ['Collar'] },
        },
        {
          type: 'state_check',
          path: '/orders',
          match: 'some',
          value: {
            customerId: 'gid://shopify/Customer/1',
            lineItems: [{ variantId: 'gid://shopify/ProductVariant/47242666836142' }],
          },
        },
      ],
    });
    expect(validateTasks([ok], data)).toEqual({ tasks: [ok], dropped: [] });
  });

  it('drops unknown handles, personas, variants, and gids with a reason each', () => {
    const report = validateTasks(
      [
        task({
          id: 'bad-handle',
          eval: [{ type: 'url_match', url: '/collections/nope', rule: 'exact' }],
        }),
        task({
          id: 'bad-page',
          eval: [
            {
              type: 'locator_probe',
              url: '/pages/nope',
              locator: 'h1',
              required: { mustInclude: ['x'] },
            },
          ],
        }),
        task({ id: 'bad-persona', setup: { login: '99' } }),
        task({ id: 'bad-variant', setup: { cart: [{ variantId: 1, quantity: 1 }] } }),
        task({
          id: 'bad-gid',
          eval: [
            {
              type: 'state_check',
              path: '/carts',
              match: 'some',
              value: { lines: [{ merchandiseId: 'gid://shopify/ProductVariant/5' }] },
            },
          ],
        }),
      ],
      data,
    );
    expect(report.tasks).toEqual([]);
    expect(report.dropped.map((d) => d.taskId)).toEqual([
      'bad-handle',
      'bad-page',
      'bad-persona',
      'bad-variant',
      'bad-gid',
    ]);
    expect(report.dropped[0]?.reason).toContain('collections handle "nope"');
  });

  it('drops probes without a selector and schema-invalid candidates', () => {
    const report = validateTasks(
      [
        task({
          id: 'blank',
          eval: [
            { type: 'locator_probe', url: 'last', locator: '  ', required: { mustInclude: ['x'] } },
          ],
        }),
        { id: 'Bad Id', shop: 'x', skill: 'exact', goal: 'g', eval: [], source: 'seed' },
      ],
      data,
    );
    expect(report.tasks).toEqual([]);
    expect(report.dropped[0]?.reason).toBe('locator_probe without a selector');
    expect(report.dropped[1]?.reason).toMatch(/^schema:/);
  });

  it('dedupes by goal and applies per-skill caps in input order', () => {
    const report = validateTasks(
      [
        task({ id: 'a', goal: 'Same goal' }),
        task({ id: 'b', goal: 'same goal ' }),
        task({ id: 'c', goal: 'Another' }),
        task({ id: 'd', goal: 'Third' }),
      ],
      data,
      { exact: 2 },
    );
    expect(report.tasks.map((t) => t.id)).toEqual(['a', 'c']);
    expect(report.dropped).toEqual([
      { taskId: 'b', reason: 'duplicate goal' },
      { taskId: 'd', reason: 'skill "exact" cap 2 reached' },
    ]);
  });
});
