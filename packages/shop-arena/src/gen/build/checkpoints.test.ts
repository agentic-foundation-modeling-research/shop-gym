import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { ArtifactCheckpoints, CheckpointError } from './checkpoints.js';

let root: string;
let tree: string;

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'checkpoints-'));
  tree = path.join(root, 'artifact');
  await write('storefront/app/root.tsx', 'root v1');
  await write('storefront/node_modules/x/index.js', 'dep v1');
  await write('backend/src/schema/shop.ts', 'schema v1');
  await write('data/products.json', '[]');
});

async function write(rel: string, content: string): Promise<void> {
  await fs.mkdir(path.dirname(path.join(tree, rel)), { recursive: true });
  await fs.writeFile(path.join(tree, rel), content);
}

async function read(rel: string): Promise<string | undefined> {
  return fs.readFile(path.join(tree, rel), 'utf-8').catch(() => undefined);
}

function checkpoints(): ArtifactCheckpoints {
  return new ArtifactCheckpoints({
    gitDir: path.join(root, 'checkpoints.git'),
    workTree: tree,
    untrackedDirs: ['data'],
  });
}

/** Edit, delete and add tracked paths, and touch every untracked kind. */
async function iterate(): Promise<void> {
  await write('storefront/app/root.tsx', 'root v2');
  await fs.rm(path.join(tree, 'backend/src/schema/shop.ts'));
  await write('storefront/app/routes/new.tsx', 'new');
  await write('notes.md', 'stray');
  await write('storefront/node_modules/x/index.js', 'dep v2');
  await write('storefront/build/server.js', 'built');
  await write('data/products.json', '[1]');
}

describe('ArtifactCheckpoints', () => {
  it('lists what changed since the last commit, without untracked paths', async () => {
    const store = checkpoints();
    await store.open('seed');
    expect(await store.changedPaths()).toEqual([]);
    await iterate();
    expect(await store.changedPaths()).toEqual([
      'backend/src/schema/shop.ts',
      'notes.md',
      'storefront/app/root.tsx',
      'storefront/app/routes/new.tsx',
    ]);
    await store.commit('exec-0001 gen_theme');
    expect(await store.changedPaths()).toEqual([]);
    await store.commit('exec-0002 gen_product');
  });

  it('rolls back to the last commit and leaves untracked paths alone', async () => {
    const store = checkpoints();
    await store.open('seed');
    await iterate();
    await store.rollback();
    expect(await store.changedPaths()).toEqual([]);
    expect(await read('storefront/app/root.tsx')).toBe('root v1');
    expect(await read('backend/src/schema/shop.ts')).toBe('schema v1');
    expect(await read('storefront/app/routes/new.tsx')).toBeUndefined();
    expect(await read('notes.md')).toBeUndefined();
    expect(await read('storefront/node_modules/x/index.js')).toBe('dep v2');
    expect(await read('storefront/build/server.js')).toBe('built');
    expect(await read('data/products.json')).toBe('[1]');
  });

  it('opens an existing repository and commits what was left uncommitted', async () => {
    await checkpoints().open('seed');
    await write('storefront/app/root.tsx', 'interrupted');
    const resumed = checkpoints();
    await resumed.open('resume');
    expect(await resumed.changedPaths()).toEqual([]);
    await write('storefront/app/root.tsx', 'next');
    await resumed.rollback();
    expect(await read('storefront/app/root.tsx')).toBe('interrupted');
  });

  it('throws CheckpointError when git fails', async () => {
    await expect(checkpoints().changedPaths()).rejects.toThrow(CheckpointError);
  });
});
