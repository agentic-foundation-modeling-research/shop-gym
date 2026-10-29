import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';
import { FakeRuntime } from '@shop-gym/agent/testing';
import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../templates.js';
import type { SidecarLaunch } from './build/sidecar.js';
import type { CommandRunner } from './build/verifiers/subprocess.js';
import { GEN_STEPS } from './config.js';
import type { FinalEvalReport } from './final_eval/final_eval.js';
import {
  STANDARD_SUB_MANUAL_FILE,
  STANDARD_SUB_MANUAL_PATH,
} from './manual_merge/standard_sub_manual.js';
import { generateShop } from './pipeline.js';
import { readShopManifest } from './publish/publish.js';
import {
  ScriptedJudge,
  ScriptedSynthLlm,
  stubStorefrontLaunch,
  writeManualFixture,
} from './testing.js';

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

/** Synthesis prompts are strings; judge prompts carry screenshots. */
class PipelineLlm implements LlmClient {
  /** `provider/id` of every request, in call order. */
  readonly models: string[] = [];
  private readonly synth = new ScriptedSynthLlm();
  private readonly judge = new ScriptedJudge();
  complete(request: CompleteRequest): Promise<Completion> {
    this.models.push(`${request.model.provider}/${request.model.id}`);
    return typeof request.prompt === 'string'
      ? this.synth.complete(request)
      : this.judge.complete(request);
  }
}

let root: string;

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'gen-pipeline-'));
});

afterEach(async () => {
  await fs.rm(root, { recursive: true, force: true });
});

describe('generateShop', () => {
  it('runs all six steps on a tiny manual and skips them on rerun', async () => {
    const manualDir = await writeManualFixture(path.join(root, 'manual'));
    const outDir = path.join(root, 'shop');
    const log: string[] = [];
    const llm = new PipelineLlm();
    const runtime = new FakeRuntime([{ writeFiles: { 'plan.md': DONE_PLAN }, reply: 'planned' }]);
    const run = () =>
      generateShop(
        {
          name: 'tiny',
          manualDirs: [manualDir],
          outDir,
          model: 'fake/scripted',
          buildModel: 'fake/builder',
          catalog: { collections: 2, productsPerCollection: 2, imagesPerProduct: 1 },
          maxIters: 2,
        },
        {
          llm,
          runtime,
          credentials: {},
          commandRunner: fakeRunner,
          sidecarLaunch: inProcessLaunch,
          storefrontLaunch: stubStorefrontLaunch,
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
      'backend',
      'data',
      'data_validation.json',
      'final_eval',
      'identity.json',
      'manual',
      'runs',
      'shop.json',
      'storefront',
    ]);
    expect(await fs.readdir(path.join(outDir, 'runs', 'build', 'artifact'))).toEqual(
      expect.arrayContaining(['data', 'manual', 'storefront']),
    );
    const standard = await fs.readFile(STANDARD_SUB_MANUAL_PATH, 'utf-8');
    for (const manual of [
      path.join(outDir, 'manual'),
      path.join(outDir, 'runs', 'build', 'artifact', 'manual'),
    ]) {
      expect(await fs.readFile(path.join(manual, 'parts', STANDARD_SUB_MANUAL_FILE), 'utf-8')).toBe(
        standard,
      );
    }
    const report = JSON.parse(await fs.readFile(result.dataValidationPath, 'utf-8'));
    expect(report.ok).toBe(true);
    expect(log.some((l) => l.includes('[build] completed'))).toBe(true);
    // The build agent runs on `buildModel`; synthesis, merge and the judges on `model`.
    expect(new Set(runtime.requests.map((r) => `${r.model.provider}/${r.model.id}`))).toEqual(
      new Set(['fake/builder']),
    );
    expect(new Set(llm.models)).toEqual(new Set(['fake/scripted']));

    const finalEval = JSON.parse(
      await fs.readFile(path.join(result.finalEvalDir, 'report.json'), 'utf-8'),
    ) as FinalEvalReport;
    expect(finalEval.visual.pages).toHaveLength(13);
    expect(finalEval.visual.pages.filter((page) => page.status === 'skipped')).toEqual([]);
    expect(finalEval.visual.failed).toBe(1); // the scripted judge fails `/search`
    // The synthesized Dataset has no Discount code, so that step is skipped.
    expect(finalEval.functional.steps.map((step) => [step.name, step.status])).toEqual([
      ['signUp', 'pass'],
      ['logOut', 'pass'],
      ['logIn', 'pass'],
      ['addAddress', 'pass'],
      ['editAddress', 'pass'],
      ['addToCart', 'pass'],
      ['applyDiscountCode', 'skipped'],
      ['checkout', 'pass'],
      ['viewOrder', 'pass'],
      ['requestReturn', 'skipped'],
    ]);
    expect((await fs.readdir(result.finalEvalDir)).sort()).toEqual([
      'pages',
      'report.json',
      'screenshots',
      'storefront.log',
      'summary.md',
    ]);

    const manifest = await readShopManifest(outDir);
    expect(result.manifestPath).toBe(path.join(outDir, 'shop.json'));
    expect(manifest).toMatchObject({ name: 'shop', genBackend: false, finalStatus: 'completed' });
    expect(manifest.templates.storefront.name).toBe('storefront');
    expect(await fs.readdir(path.join(outDir, 'storefront'))).toContain('template.json');
    expect(await fs.readdir(path.join(outDir, 'backend'))).toContain('template.json');

    const again = await run();
    expect(again.reports.every((r) => r.status === 'skipped')).toBe(true);
  }, 180_000);
});
