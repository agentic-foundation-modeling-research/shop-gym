import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { FakeRuntime } from '@shop-gym/agent/testing';
import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../templates.js';
import type { SidecarLaunch } from './build/sidecar.js';
import type { CommandRunner } from './build/verifiers/subprocess.js';
import { GEN_STEPS } from './config.js';
import { generateShop } from './pipeline.js';
import { ScriptedSynthLlm, writeManualFixture } from './testing.js';

const DASH = '\u2014'; // the harness plan grammar's task separator (U+2014)
const DONE_PLAN = `# Plan - test\n\n## Tasks\n\n- [x] gen_homepage ${DASH} render the homepage [priority: 7]\n\n## Omitted Areas\n\n- (none)\n`;

const fakeRunner: CommandRunner = async (argv, options) => {
  if (argv[0] === 'git' && argv[1] === 'ls-files') {
    const files =
      options.cwd === STOREFRONT_TEMPLATE_DIR
        ? ['package.json', 'app/routes/home.tsx']
        : ['package.json', 'src/cli.ts'];
    return { exitCode: 0, stdout: `${files.join('\0')}\0`, stderr: '', timedOut: false };
  }
  return {
    exitCode: 0,
    stdout: argv[0] === 'git' ? 'deadbeef\n' : '',
    stderr: '',
    timedOut: false,
  };
};

const inProcessLaunch: SidecarLaunch = async (options) => {
  const server = createSandboxServer({
    data: loadShopData(options.dataDir),
    dataDir: options.dataDir,
    port: options.port,
  });
  await server.listen();
  return { stop: () => server.close() };
};

let root: string;

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'gen-pipeline-'));
});

afterEach(async () => {
  await fs.rm(root, { recursive: true, force: true });
});

describe('generateShop', () => {
  it('runs all four steps on a tiny manual and skips them on rerun', async () => {
    const manualDir = await writeManualFixture(path.join(root, 'manual'));
    const outDir = path.join(root, 'shop');
    const log: string[] = [];
    const run = () =>
      generateShop(
        {
          name: 'tiny',
          manualDirs: [manualDir],
          outDir,
          model: 'fake/scripted',
          catalog: { collections: 2, productsPerCollection: 2, imagesPerProduct: 1 },
          maxIters: 2,
        },
        {
          llm: new ScriptedSynthLlm(),
          runtime: new FakeRuntime([{ writeFiles: { 'plan.md': DONE_PLAN }, reply: 'planned' }]),
          credentials: {},
          commandRunner: fakeRunner,
          sidecarLaunch: inProcessLaunch,
          log: (line) => log.push(line),
        },
      );
    const result = await run();
    expect(result.reports.map((r) => `${r.id}:${r.status}`)).toEqual(
      GEN_STEPS.map((s) => `${s}:ran`),
    );
    expect(result.shopDir).toBe(outDir);
    const top = (await fs.readdir(outDir)).sort();
    expect(top).toEqual([
      '.pipeline',
      '.shop_gen',
      'data',
      'data_validation.json',
      'identity.json',
      'manual',
      'runs',
    ]);
    expect(await fs.readdir(path.join(outDir, 'runs', 'build', 'artifact'))).toEqual(
      expect.arrayContaining(['data', 'manual', 'storefront']),
    );
    const report = JSON.parse(await fs.readFile(result.dataValidationPath, 'utf-8'));
    expect(report.ok).toBe(true);
    expect(log.some((l) => l.includes('[build] completed'))).toBe(true);

    const again = await run();
    expect(again.reports.every((r) => r.status === 'skipped')).toBe(true);
  }, 60_000);
});
