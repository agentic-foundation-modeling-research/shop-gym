import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { DEFAULT_EPISODE_ID, EpisodeStore } from './episodes.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const data = loadShopData(FIXTURE_DIR);

describe('EpisodeStore', () => {
  it('creates episodes lazily and returns the same instance afterwards', () => {
    const store = new EpisodeStore(data);
    expect(store.has('a')).toBe(false);
    const a = store.get('a');
    expect(store.has('a')).toBe(true);
    expect(store.get('a')).toBe(a);
    expect(a.episodeId).toBe('a');
  });

  it('reset discards mutations and hands back a fresh seed', () => {
    const store = new EpisodeStore(data);
    const before = store.get('a');
    const cart = before.carts.create({});
    const after = store.reset('a');
    expect(after).not.toBe(before);
    expect(after.carts.get(cart.id)).toBeUndefined();
    expect(store.get('a')).toBe(after);
  });

  it('delete reports whether the episode existed', () => {
    const store = new EpisodeStore(data);
    store.get('a');
    expect(store.delete('a')).toBe(true);
    expect(store.delete('a')).toBe(false);
    expect(store.has('a')).toBe(false);
  });
});

describe('EpisodeStore - cart persistence', () => {
  let tmpDir: string | null = null;

  afterEach(() => {
    if (tmpDir !== null) fs.rmSync(tmpDir, { recursive: true, force: true });
    tmpDir = null;
  });

  function cartIdsInFile(file: string): readonly string[] {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8')) as { carts: Record<string, unknown> };
    return Object.keys(parsed.carts);
  }

  it('backs only the default episode with the cart file', () => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'episodes-'));
    const file = path.join(tmpDir, 'carts.json');
    const store = new EpisodeStore(data, { cartStorePath: file });

    const persisted = store.get(DEFAULT_EPISODE_ID).carts.create({});
    expect(cartIdsInFile(file)).toEqual([persisted.id]);

    store.get('scratch').carts.create({});
    expect(cartIdsInFile(file)).toEqual([persisted.id]);

    store.reset(DEFAULT_EPISODE_ID);
    expect(cartIdsInFile(file)).toEqual([]);
  });
});
