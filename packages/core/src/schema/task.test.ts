import { describe, expect, it } from 'vitest';

import { checkSchema, taskSchema } from './task.js';

const baseTask = {
  id: 'cheapest_sock_to_cart',
  shop: 'mock_clothing',
  skill: 'browse',
  goal: 'Add the cheapest sock to the cart.',
  eval: [{ type: 'url_match', url: '/cart', rule: 'contains' }],
  source: 'explore',
};

describe('taskSchema', () => {
  it('accepts a task with every check type', () => {
    const task = {
      ...baseTask,
      setup: { login: 'persona_1', cart: [{ variantId: 42, quantity: 1 }] },
      eval: [
        { type: 'string_match', mustInclude: ['Tab Sock', '$29.99'] },
        { type: 'url_match', url: '/cart', rule: 'contains' },
        {
          type: 'locator_probe',
          url: 'last',
          locator: '.cart-line .title',
          required: { exactMatch: 'Tab Sock' },
        },
        {
          type: 'state_check',
          path: '/orders',
          match: 'some',
          value: { lineItems: [{ variantId: 42, quantity: 1 }] },
        },
        { type: 'llm_judge', rubric: 'The cart drawer is open and shows one sock.' },
      ],
    };
    expect(taskSchema.parse(task)).toEqual(task);
  });

  it('rejects identifiers that are not lower-case slugs', () => {
    expect(taskSchema.safeParse({ ...baseTask, id: 'Task 1' }).success).toBe(false);
  });

  it('rejects an empty eval list', () => {
    expect(taskSchema.safeParse({ ...baseTask, eval: [] }).success).toBe(false);
  });
});

describe('checkSchema', () => {
  it('rejects string_match without any reference', () => {
    expect(checkSchema.safeParse({ type: 'string_match' }).success).toBe(false);
  });

  it('rejects state_check with a path that is not a JSON pointer', () => {
    const check = { type: 'state_check', path: 'orders.0', match: 'equals', value: 1 };
    expect(checkSchema.safeParse(check).success).toBe(false);
  });

  it('rejects unknown check types', () => {
    expect(checkSchema.safeParse({ type: 'regex_match', pattern: '.*' }).success).toBe(false);
  });
});
