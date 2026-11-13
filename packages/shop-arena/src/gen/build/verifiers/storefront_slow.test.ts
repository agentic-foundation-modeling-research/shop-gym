/**
 * Storefront verifiers, the page lint and the final eval against the real
 * storefront template over the in-process sandbox backend.
 *
 * Gated by `SHOPGYM_SLOW_TESTS=1`: it seeds the template (real
 * `pnpm install`), builds it, and boots it through `StorefrontSidecar`.
 */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';
import { BrowserSession } from '@shop-gym/browser';
import type { VerifierContext } from '@shop-gym/harness';
import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../../../templates.js';
import { runFinalEval } from '../../final_eval/final_eval.js';
import { defaultBackendTemplateDir, seedTemplate } from '../seed.js';
import { freePort } from '../sidecar.js';
import { StorefrontSidecar, spawnStorefront } from '../storefront_sidecar.js';
import { addToCart } from './browser_steps.js';
import { cartConformanceVerifier } from './cart_conformance.js';
import { navCoverageVerifier } from './nav_coverage.js';
import { type PageLintResult, lintLoadedPage, pageLintVerifier } from './page_lint.js';
import { routes200Verifier } from './routes_200.js';
import { CART_DRAWER_SELECTOR, cartDrawerRoute } from './shop_pages.js';
import { storefrontTypecheckVerifier } from './storefront_commands.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
/** A fixture product whose only variant is the placeholder "Default Title". */
const SINGLE_VARIANT_PRODUCT = 'agoracage-skin-and-coat-chicken-with-grains-12lb';
const USAGE = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 };
/** The tax rate of the second backend; the fixture itself has no tax. */
const TAX_RATE = 0.08;

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

/** The cart summary rows under `summary` on `page`, as label -> amount in cents. */
async function summaryRows(
  page: BrowserSession['page'],
  summary: string,
): Promise<Map<string, number>> {
  const rows = await page
    .locator(`${summary} .cart-total-row`)
    .evaluateAll((elements) =>
      elements.map((row) => [
        row.children[0]?.textContent ?? '',
        row.children[1]?.textContent ?? '',
      ]),
    );
  return new Map(
    rows.map(([label = '', amount = '']) => [
      label.trim(),
      Math.round(Number(amount.replace(/[^0-9.]/g, '')) * 100),
    ]),
  );
}

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
      const steps = (result.details as { steps: { name: string }[] }).steps;
      expect(steps.map((step) => step.name).filter((name) => name.startsWith('/cart.js'))).toEqual([
        '/cart.js after add',
        '/cart.js after update',
        '/cart.js after remove',
      ]);
    }, 120_000);

    it('page_lint passes every canonical page and the open cart drawer', async () => {
      const result = await pageLintVerifier({ target: target(), dataDir: FIXTURE_DIR }).run(
        ctx('visual_fix'),
      );
      expect(result.verdict, result.feedback).toBe('pass');
      const pages = (result.details as { pages: PageLintResult[] }).pages;
      expect(pages.filter((page) => page.status !== 'pass')).toEqual([]);
      expect(pages.map((page) => page.name)).toContain('cartDrawer');
    }, 300_000);

    it('shows no "Default Title" for a product with one variant', async () => {
      const session = await BrowserSession.launch({ episodeId: 'slow-default-title' });
      try {
        const added = await addToCart(session.page, sidecar.url, SINGLE_VARIANT_PRODUCT);
        expect(added.ok, added.detail).toBe(true);
        for (const [route, scope] of [
          [`/products/${SINGLE_VARIANT_PRODUCT}`, 'page'],
          ['/cart', 'page'],
          [cartDrawerRoute(SINGLE_VARIANT_PRODUCT), 'cartDrawer'],
        ] as const) {
          await session.page.goto(`${sidecar.url}${route}`, { waitUntil: 'load' });
          expect(await lintLoadedPage(session.page, scope), route).toEqual([]);
        }
      } finally {
        await session.close();
      }
    }, 120_000);

    it('shows the estimated tax that makes the Total differ from the Subtotal', async () => {
      const data = loadShopData(FIXTURE_DIR);
      const taxedPort = await freePort();
      const taxed = createSandboxServer({
        data: { ...data, commerce: { ...data.commerce, tax_rate: TAX_RATE } },
        dataDir: FIXTURE_DIR,
        port: taxedPort,
      });
      await taxed.listen();
      const port = await freePort();
      const url = `http://127.0.0.1:${port}`;
      const storefront = await spawnStorefront({
        storefrontDir: path.join(workDir, 'artifact', 'storefront'),
        backendUrl: `http://127.0.0.1:${taxedPort}`,
        port,
        url,
        logPath: path.join(workDir, 'storefront-taxed.log'),
        healthTimeoutMs: 30_000,
      });
      const session = await BrowserSession.launch({ episodeId: 'slow-estimated-tax' });
      try {
        const added = await addToCart(session.page, url, SINGLE_VARIANT_PRODUCT);
        expect(added.ok, added.detail).toBe(true);
        for (const [route, summary] of [
          ['/cart', '.cart-summary-page'],
          [cartDrawerRoute(SINGLE_VARIANT_PRODUCT), `${CART_DRAWER_SELECTOR} .cart-summary`],
        ] as const) {
          await session.page.goto(`${url}${route}`, { waitUntil: 'load' });
          const rows = await summaryRows(session.page, summary);
          const subtotal = rows.get('Subtotal') ?? 0;
          const tax = rows.get('Estimated tax');
          expect(subtotal, route).toBeGreaterThan(0);
          expect(tax, route).toBe(Math.round(subtotal * TAX_RATE));
          expect(rows.get('Total'), route).toBe(subtotal + (tax ?? 0));
        }
      } finally {
        await session.close();
        await storefront.stop();
        await taxed.close();
      }
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
      const { visual, functional, pageLint } = result.report;
      expect(visual.pages.filter((page) => page.status === 'skipped')).toEqual([]);
      expect(visual.failed).toBe(0);
      expect(pageLint.pages.filter((page) => page.status !== 'pass')).toEqual([]);
      expect(functional.steps.map((step) => [step.name, step.status, step.detail])).toEqual([
        ['signUp', 'pass', expect.any(String)],
        ['logOut', 'pass', expect.any(String)],
        ['logIn', 'pass', expect.any(String)],
        ['addToCart', 'pass', expect.any(String)],
        ['applyDiscountCode', 'pass', expect.stringContaining('WELCOME10')],
        ['checkout', 'pass', expect.any(String)],
        ['viewOrder', 'pass', expect.any(String)],
        ['requestReturn', 'skipped', 'not supported by backend'],
      ]);
    }, 300_000);
  },
);
