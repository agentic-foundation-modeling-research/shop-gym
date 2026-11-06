import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import type { Task, TaskStatus } from '@shop-gym/harness';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { coverageGaps } from './coverage.js';

const NO_OMISSIONS: ReadonlySet<string> = new Set();

function task(id: string, status: TaskStatus): Task {
  return { id, status, priority: 0, note: null };
}

let prefetchDir: string;

beforeEach(() => {
  // A prefetched `/cart.js` is the only evidence, so `cart` is the only area.
  prefetchDir = mkdtempSync(join(tmpdir(), 'coverage-'));
  writeFileSync(join(prefetchDir, 'cart.js'), '{"items":[]}');
});

afterEach(() => {
  rmSync(prefetchDir, { recursive: true, force: true });
});

describe('coverageGaps', () => {
  it('counts an area covered when its Plan task is done', () => {
    expect(coverageGaps(prefetchDir, [task('cart_drawer', 'done')], NO_OMISSIONS)).toEqual([]);
  });

  it.each<TaskStatus>(['pending', 'in_progress', 'blocked'])(
    'reports an area whose Plan task is %s as a gap',
    (status) => {
      expect(coverageGaps(prefetchDir, [task('cart_drawer', status)], NO_OMISSIONS)).toEqual([
        'cart',
      ]);
    },
  );

  it('counts an area covered when one of its Plan tasks is done', () => {
    const tasks = [task('cart_drawer', 'blocked'), task('cart_page', 'done')];
    expect(coverageGaps(prefetchDir, tasks, NO_OMISSIONS)).toEqual([]);
  });
});
