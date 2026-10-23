import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { FakeRuntime } from '@shop-gym/agent/testing';
import { taskSchema } from '@shop-gym/core';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { readBenchmarks, writeBenchmarks } from './benchmarks.js';
import { type GuruConfig, loadGuruConfig, parseGuruConfig } from './config.js';
import { build, evaluate } from './pipeline.js';
import { RuntimeBrowserAgent } from './solve/agent.js';
import {
  type Backend,
  FIXTURE_DIR,
  type FakeStorefront,
  SHOP_PAGES,
  startBackend,
  startFakeStorefront,
} from './testing/fixtures.js';

const DEFAULT_CONFIG = fileURLToPath(new URL('../configs/default.json', import.meta.url));

let backend: Backend;
let shop: FakeStorefront;
let outDir: string;
let config: GuruConfig;

beforeAll(async () => {
  backend = await startBackend();
  shop = await startFakeStorefront(SHOP_PAGES);
  outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'shopgym-guru-pipeline-'));
  config = parseGuruConfig({
    shop: 'fixture',
    shopUrl: shop.url,
    backendUrl: backend.url,
    dataDir: FIXTURE_DIR,
    outDir,
    model: { provider: 'fake', id: 'm' },
    caps: { exact: 2, account: 1 },
    episodeTimeoutMs: 20_000,
  });
}, 60_000);

afterAll(async () => {
  await shop.close();
  await backend.server.close();
});

describe('config', () => {
  it('loads the default config with paths resolved against the file', async () => {
    const loaded = await loadGuruConfig(DEFAULT_CONFIG);
    expect(path.isAbsolute(loaded.dataDir)).toBe(true);
    expect(loaded.dataDir).toBe(FIXTURE_DIR);
    expect(loaded.concurrency).toBe(1);
    expect(loaded.model).toEqual({ provider: 'anthropic', id: 'claude-sonnet-4-5' });
  });

  it('rejects malformed input', () => {
    expect(() => parseGuruConfig({ shop: 'Bad' })).toThrow();
  });
});

describe('build', () => {
  it('writes one benchmark file per skill and is idempotent', async () => {
    const first = await build(config);
    expect(first.dropped).toEqual([]);
    expect(first.tasks.map((t) => t.skill)).toEqual(['exact', 'exact', 'account']);
    expect(first.files.map((f) => path.basename(f)).sort()).toEqual(['account.json', 'exact.json']);

    const second = await build(config);
    expect(second.tasks).toEqual(first.tasks);
    const onDisk = await readBenchmarks(path.join(outDir, 'fixture'));
    expect(onDisk.map((t) => t.id)).toEqual([
      'fixture-account-1',
      'fixture-exact-1',
      'fixture-exact-2',
    ]);
    for (const task of onDisk) expect(() => taskSchema.parse(task)).not.toThrow();
  });

  it('merges by id when writing again', async () => {
    const shopDir = path.join(outDir, 'fixture');
    const [existing] = await readBenchmarks(shopDir, ['exact']);
    if (existing === undefined) throw new Error('expected a task');
    await writeBenchmarks(shopDir, [
      { ...existing, goal: 'replaced' },
      { ...existing, id: 'fixture-explore-1', source: 'explore' },
    ]);
    const merged = await readBenchmarks(shopDir, ['exact']);
    expect(merged.map((t) => t.id)).toEqual([
      'fixture-exact-1',
      'fixture-exact-2',
      'fixture-explore-1',
    ]);
    expect(merged[0]?.goal).toBe('replaced');
  });
});

describe('evaluate', () => {
  it('runs every benchmark task and writes results and aggregate', async () => {
    const tasks = await readBenchmarks(path.join(outDir, 'fixture'));
    const runtime = new FakeRuntime(
      tasks.map(() => ({ toolCalls: [{ tool: 'finish', arguments: { answer: 'n/a' } }] })),
    );
    const agent = new RuntimeBrowserAgent({ runtime, model: config.model, name: 'fake' });
    const stage = await evaluate(config, { agent });

    expect(stage.results).toHaveLength(tasks.length);
    expect(stage.aggregate.total).toBe(tasks.length);
    expect(Object.keys(stage.aggregate.by_skill).sort()).toEqual(['account', 'exact']);
    expect(stage.aggregate.by_shop.fixture?.total).toBe(tasks.length);
    const written = JSON.parse(
      await fs.readFile(path.join(stage.runDir, 'aggregate.json'), 'utf-8'),
    );
    expect(written).toEqual(stage.aggregate);
    const results = JSON.parse(await fs.readFile(path.join(stage.runDir, 'results.json'), 'utf-8'));
    expect(results).toHaveLength(tasks.length);
  }, 60_000);
});
