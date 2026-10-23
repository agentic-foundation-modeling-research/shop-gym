import type { EpisodeResult } from '@shop-gym/core';
import { describe, expect, it } from 'vitest';

import { aggregate } from './aggregate.js';

function result(overrides: Partial<EpisodeResult>): EpisodeResult {
  return {
    taskId: 't',
    shop: 'shop-a',
    skill: 'exact',
    agent: { name: 'fake', model: 'm' },
    status: 'completed',
    answer: null,
    finalUrl: null,
    passed: false,
    checks: [],
    usage: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0, costUsd: 0.5 },
    startedAt: '2026-09-30T00:00:00.000Z',
    durationMs: 10,
    ...overrides,
  };
}

describe('aggregate', () => {
  it('counts passes, failures, errors, and sums usage', () => {
    const summary = aggregate([
      result({ passed: true }),
      result({ passed: false, skill: 'browse' }),
      result({ status: 'error', skill: 'browse', shop: 'shop-b', error: 'boom' }),
      result({ passed: true, shop: 'shop-b' }),
    ]);
    expect(summary).toMatchObject({ total: 4, passed: 2, failed: 2, errors: 1, passRate: 0.5 });
    expect(summary.by_skill).toEqual({
      browse: { total: 2, passed: 0, passRate: 0 },
      exact: { total: 2, passed: 2, passRate: 1 },
    });
    expect(summary.by_shop).toEqual({
      'shop-a': { total: 2, passed: 1, passRate: 0.5 },
      'shop-b': { total: 2, passed: 1, passRate: 0.5 },
    });
    expect(summary.usage).toEqual({ input: 4, output: 8, cacheRead: 0, cacheWrite: 0, costUsd: 2 });
  });

  it('handles an empty result set', () => {
    expect(aggregate([])).toMatchObject({ total: 0, passRate: 0, by_skill: {}, by_shop: {} });
  });
});
