import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import type { Task, TaskStatus } from '@shop-gym/harness';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { coverageGaps, fixedAreaGaps } from './coverage.js';

const NO_OMISSIONS: ReadonlySet<string> = new Set();

function task(id: string, status: TaskStatus, note: string | null = null): Task {
  return { id, status, priority: 0, note };
}

let prefetchDir: string;

beforeEach(() => {
  prefetchDir = mkdtempSync(join(tmpdir(), 'coverage-'));
});

afterEach(() => {
  rmSync(prefetchDir, { recursive: true, force: true });
});

/** Saves the prefetch files that show the areas under test. */
function evidence(...files: readonly string[]): void {
  for (const file of files) writeFileSync(join(prefetchDir, file), '');
}

describe('coverageGaps', () => {
  it('counts an area covered when its Plan task is done', () => {
    evidence('cart.js');
    expect(coverageGaps(prefetchDir, [task('cart_drawer', 'done')], NO_OMISSIONS)).toEqual([]);
  });

  it.each<TaskStatus>(['pending', 'in_progress', 'blocked'])(
    'reports an area whose Plan task is %s as a gap',
    (status) => {
      evidence('cart.js');
      expect(coverageGaps(prefetchDir, [task('cart_drawer', status)], NO_OMISSIONS)).toEqual([
        'cart',
      ]);
    },
  );

  it('counts an area covered when one of its Plan tasks is done', () => {
    evidence('cart.js');
    const tasks = [task('cart_drawer', 'blocked'), task('cart_page', 'done')];
    expect(coverageGaps(prefetchDir, tasks, NO_OMISSIONS)).toEqual([]);
  });

  it('reports an area whose own Plan task is not done, even when a related task is done', () => {
    // The homepage shows the homepage, header, and footer areas.
    evidence('index.html');
    const tasks = [
      task('homepage_sections', 'done'),
      task('header_navigation', 'blocked'),
      task('footer', 'pending'),
    ];
    expect(coverageGaps(prefetchDir, tasks, NO_OMISSIONS)).toEqual(['footer', 'header_navigation']);
  });
});

describe('fixedAreaGaps', () => {
  /** The gap reason of `product_reviews` when the plan holds `tasks`. */
  function reviewsGap(tasks: readonly Task[]): string | undefined {
    return fixedAreaGaps(tasks).find((gap) => gap.area === 'product_reviews')?.reason;
  }

  it('reports every fixed area of an empty plan as not in the plan', () => {
    const gaps = fixedAreaGaps([]);
    expect(gaps).toHaveLength(14);
    expect(gaps.every((gap) => gap.reason === 'not in the plan')).toBe(true);
  });

  it('leaves out a fixed area whose Plan task is done, and ignores other Plan tasks', () => {
    const tasks = [task('product_reviews', 'done'), task('gift_card_purchase', 'pending')];
    expect(reviewsGap(tasks)).toBeUndefined();
    expect(fixedAreaGaps(tasks).map((gap) => gap.area)).not.toContain('gift_card_purchase');
  });

  it.each<[string, Task, string]>([
    ['pending', task('product_reviews', 'pending'), 'not started when the run ended'],
    ['in progress', task('product_reviews', 'in_progress'), 'in progress when the run ended'],
    [
      'blocked with a reason after the brief',
      task('product_reviews', 'blocked', 'open a review block; sort; no reviews on any page'),
      'blocked: no reviews on any page',
    ],
    [
      'blocked by a protocol violation',
      task(
        'product_reviews',
        'blocked',
        "protocol_violation: resurrected [x] task ids: ['footer']",
      ),
      "blocked: protocol_violation: resurrected [x] task ids: ['footer']",
    ],
    ['blocked with no note', task('product_reviews', 'blocked'), 'blocked: no reason given'],
  ])('gives a one-line reason for a Plan task that is %s', (_, planned, reason) => {
    expect(reviewsGap([planned])).toBe(reason);
  });
});
