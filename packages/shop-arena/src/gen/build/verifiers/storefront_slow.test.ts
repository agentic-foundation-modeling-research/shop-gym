/**
 * Storefront verifiers and the final-eval functional sweep against the
 * real storefront template over the in-process sandbox backend.
 *
 * Gated by `SHOPGYM_SLOW_TESTS=1`: it seeds the template (real
 * `pnpm install`), builds it, and boots it through `StorefrontSidecar`.
 */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';
import type { VerifierContext } from '@shop-gym/harness';
import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../../../templates.js';
import { runFinalEval } from '../../final_eval/final_eval.js';
import { defaultBackendTemplateDir, seedTemplate } from '../seed.js';
import { freePort } from '../sidecar.js';
import { StorefrontSidecar } from '../storefront_sidecar.js';
import { cartConformanceVerifier } from './cart_conformance.js';
import { navCoverageVerifier } from './nav_coverage.js';
import { routes200Verifier } from './routes_200.js';
import { storefrontTypecheckVerifier } from './storefront_commands.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
const USAGE = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 };

class PassingJudge implements LlmClient {
  async complete(_request: CompleteRequest): Promise<Completion> {
    const text = JSON.stringify({
      verdict: 'pass',
      score: 8,
      categoryScores: { structure: 8, components: 8, visualTone: 8 },
      feedback: 'Looks finished.',
      issues: [],
    });
    return { text, model: 'm', stopReason: 'stop', usage: USAGE };
  }
}

let workDir: string;
let backend: ReturnType<typeof createSandboxServer>;
let backendUrl: string;
let sidecar: StorefrontSidecar;

function ctx(selectedTaskId: string): VerifierContext {
  return {
    runDir: workDir,
    iterId: 'exec-0001',
    selectedTaskId,
    plan: [],
    artifactDir: path.join(workDir, 'artifact'),
  };
}

describe.skipIf(!process.env.SHOPGYM_SLOW_TESTS)(
  'storefront verifiers on the real template',
  () => {
    beforeAll(async () => {
      workDir = await fs.mkdtemp(path.join(os.tmpdir(), 'storefront-slow-'));
      const storefrontDir = path.join(workDir, 'artifact', 'storefront');
      await seedTemplate({ templateDir: STOREFRONT_TEMPLATE_DIR, destDir: storefrontDir });
      const backendPort = await freePort();
      backend = createSandboxServer({
        data: loadShopData(FIXTURE_DIR),
        dataDir: FIXTURE_DIR,
        port: backendPort,
      });
      await backend.listen();
      backendUrl = `http://127.0.0.1:${backendPort}`;
      sidecar = new StorefrontSidecar({
        storefrontDir,
        backendUrl,
        port: await freePort(),
        logPath: path.join(workDir, 'storefront.log'),
      });
      await sidecar.start();
    }, 600_000);

    afterAll(async () => {
      await sidecar?.stop();
      await backend?.close();
      if (workDir) await fs.rm(workDir, { recursive: true, force: true });
    });

    const target = () => ({ url: sidecar.url, prepare: () => sidecar.restartIfChanged() });

    it('typechecks the seeded copy', async () => {
      const result = await storefrontTypecheckVerifier().run(ctx('gen_homepage'));
      expect(result.verdict, result.feedback).toBe('pass');
    }, 300_000);

    it('routes_200 passes for every bucket including account and checkout', async () => {
      const result = await routes200Verifier({ target: target(), dataDir: FIXTURE_DIR }).run(
        ctx('visual_fix'),
      );
      expect(result.verdict, result.feedback).toBe('pass');
    }, 120_000);

    it('nav_coverage finds every menu target in the rendered shell', async () => {
      const result = await navCoverageVerifier({ target: target(), dataDir: FIXTURE_DIR }).run(
        ctx('gen_navigation'),
      );
      expect(result.verdict, result.feedback).toBe('pass');
    }, 120_000);

    it('cart_conformance completes add, update, totals, remove and guest checkout', async () => {
      const result = await cartConformanceVerifier({
        target: target(),
        backendUrl,
        dataDir: FIXTURE_DIR,
      }).run(ctx('gen_cart_search'));
      expect(result.verdict, result.feedback).toBe('pass');
    }, 120_000);

    it('final_eval captures every canonical page and passes the functional sweep', async () => {
      const result = await runFinalEval({
        dataDir: FIXTURE_DIR,
        backendUrl,
        storefrontUrl: sidecar.url,
        llm: new PassingJudge(),
        model: { provider: 'fake', id: 'judge' },
        outDir: path.join(workDir, 'final_eval'),
      });
      const { visual, functional } = result.report;
      expect(visual.pages.filter((page) => page.status === 'skipped')).toEqual([]);
      expect(visual.failed).toBe(0);
      expect(functional.steps.map((step) => [step.name, step.status, step.detail])).toEqual([
        ['signUp', 'pass', expect.any(String)],
        ['logOut', 'pass', expect.any(String)],
        ['logIn', 'pass', expect.any(String)],
        ['addToCart', 'pass', expect.any(String)],
        ['checkout', 'pass', expect.any(String)],
        ['viewOrder', 'pass', expect.any(String)],
        ['requestReturn', 'skipped', 'not supported by backend'],
      ]);
    }, 300_000);
  },
);
