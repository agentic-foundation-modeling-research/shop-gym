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
