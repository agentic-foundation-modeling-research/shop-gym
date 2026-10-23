import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { SeedError, checkSeed, parseSeedManifest, snapshotSeed } from './seed.js';

let dir: string;
beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'seed-'));
  await fs.mkdir(path.join(dir, 'data', 'nested'), { recursive: true });
  await fs.writeFile(path.join(dir, 'data', 'a.json'), '1');
  await fs.writeFile(path.join(dir, 'data', 'nested', 'b.txt'), 'b');
  await fs.writeFile(path.join(dir, 'top.txt'), 't');
});

describe('snapshotSeed', () => {
  it('hashes every file under the seeded roots with sorted keys', async () => {
    const manifest = await snapshotSeed(dir, ['top.txt', 'data']);
    expect(manifest.seededRoots).toEqual(['data', 'top.txt']);
    expect(Object.keys(manifest.files)).toEqual(['data/a.json', 'data/nested/b.txt', 'top.txt']);
    expect(manifest.files['top.txt']).toMatch(/^[0-9a-f]{64}$/);
  });

  it('rejects missing roots and symlinks', async () => {
    await expect(snapshotSeed(dir, ['nope'])).rejects.toThrow(SeedError);
    await fs.symlink(path.join(dir, 'top.txt'), path.join(dir, 'data', 'link'));
    await expect(snapshotSeed(dir, ['data'])).rejects.toThrow('symlink in seed not supported');
  });
});

describe('checkSeed', () => {
  it('passes on an untouched tree', async () => {
    const manifest = await snapshotSeed(dir, ['data']);
    expect(await checkSeed(manifest, dir, 'exec-0001')).toEqual({
      iterId: 'exec-0001',
      passed: true,
      violations: [],
    });
  });

  it('reports mutated, deleted, and extended paths in that order', async () => {
    const manifest = await snapshotSeed(dir, ['data']);
    await fs.writeFile(path.join(dir, 'data', 'a.json'), '2');
    await fs.rm(path.join(dir, 'data', 'nested', 'b.txt'));
    await fs.writeFile(path.join(dir, 'data', 'c.txt'), 'c');
    await fs.writeFile(path.join(dir, 'outside.txt'), 'ok');
    const result = await checkSeed(manifest, dir, 'exec-0002');
    expect(result.passed).toBe(false);
    expect(result.violations).toEqual([
      'seed_mutated: data/a.json',
      'seed_deleted: data/nested/b.txt',
      'seed_extended: data/c.txt',
    ]);
  });
});

describe('parseSeedManifest', () => {
  it('round-trips and rejects wrong shapes', async () => {
    const manifest = await snapshotSeed(dir, ['top.txt']);
    expect(parseSeedManifest(JSON.parse(JSON.stringify(manifest)))).toEqual(manifest);
    expect(() => parseSeedManifest({ files: 1 })).toThrow('seed manifest has wrong shape');
  });
});
