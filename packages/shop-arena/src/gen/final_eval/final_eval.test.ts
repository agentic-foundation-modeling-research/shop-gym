/**
 * `runFinalEval` against a stateful `node:http` storefront stub (cookie
 * session and cart) with a scripted judge. Checks the report layout; the
 * real template is covered by the slow storefront test. A relabel of the
 * stub's stylesheet stands in for a restyle that broke the cart drawer.
 */

import * as fs from 'node:fs/promises';
import type * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { defaultBackendTemplateDir } from '../build/seed.js';
import type { PageLintResult } from '../build/verifiers/page_lint.js';
import { ScriptedJudge, type StubStorefrontOptions, stubStorefront } from '../testing.js';
import { type FinalEvalReport, runFinalEval } from './final_eval.js';
import { FUNCTIONAL_STEP_NAMES } from './functional_sweep.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
const MODEL = { provider: 'fake', id: 'judge' };

const servers: http.Server[] = [];
let storefrontUrl: string;

async function serve(options?: StubStorefrontOptions): Promise<string> {
  const server = stubStorefront(options);
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('no port');
  return `http://127.0.0.1:${address.port}`;
}

beforeAll(async () => {
  storefrontUrl = await serve();
});

afterAll(async () => {
  await Promise.all(
    servers.map((server) => new Promise<void>((resolve) => server.close(() => resolve()))),
  );
});

describe('runFinalEval', () => {
  it('writes the report, per-page files and screenshots and counts the sweeps and the page lint', async () => {
    const outDir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'final-eval-')), 'final_eval');
    const judge = new ScriptedJudge();
    const lines: string[] = [];
    const result = await runFinalEval({
      dataDir: FIXTURE_DIR,
      backendUrl: 'http://127.0.0.1:1',
      storefrontUrl,
      llm: judge,
      model: MODEL,
      outDir,
      log: (line) => lines.push(line),
    });
    expect(result.reportPath).toBe(path.join(outDir, 'report.json'));
    const report = JSON.parse(await fs.readFile(result.reportPath, 'utf-8')) as FinalEvalReport;
    expect(report.visual.pages.map((page) => page.name).sort()).toEqual(
      [
        'home',
        'collection',
        'product',
        'search',
        'accountLogin',
        'accountRegister',
        'policy',
        'cartDrawer',
        'cart',
        'checkout',
        'thankYou',
        'accountProfile',
        'orderList',
        'orderDetail',
        'addresses',
      ].sort(),
    );
    expect(report.visual.pages.every((page) => page.status !== 'skipped')).toBe(true);
    expect(report.visual).toMatchObject({ passed: 14, failed: 1, skipped: 0 });
    const drawer = report.visual.pages.find((page) => page.name === 'cartDrawer');
    expect(drawer).toMatchObject({
      route: '/products/shopliseum-mushroom-dog-toys?cart=open',
      bucket: 'cart_search',
      status: 'pass',
    });
    expect(drawer?.screenshots.map((shot) => shot.path)).toEqual([
      'screenshots/cartDrawer__desktop.png',
      'screenshots/cartDrawer__mobile.png',
    ]);
    const search = report.visual.pages.find((page) => page.name === 'search');
    expect(search).toMatchObject({ status: 'fail', score: 5, httpStatus: 200 });
    expect(search?.screenshots.map((shot) => shot.path)).toEqual([
      'screenshots/search__desktop.png',
      'screenshots/search__mobile.png',
    ]);
    const register = report.visual.pages.find((page) => page.name === 'accountRegister');
    expect(register).toMatchObject({ route: '/account/register', bucket: 'account' });
    const orderList = report.visual.pages.find((page) => page.name === 'orderList');
    expect(orderList).toMatchObject({ route: '/account/orders', bucket: 'account' });
    const addresses = report.visual.pages.find((page) => page.name === 'addresses');
    expect(addresses).toMatchObject({ route: '/account/addresses', bucket: 'account' });
    const orderDetail = report.visual.pages.find((page) => page.name === 'orderDetail');
    expect(orderDetail?.route).toBe('/account/orders/1001');
    const thankYou = report.visual.pages.find((page) => page.name === 'thankYou');
    expect(thankYou?.route).toBe('/checkout/confirmation/1001');
    expect(judge.requests).toHaveLength(15);
    // The page lint checks the same canonical pages as the visual sweep.
    expect(report.pageLint.pages.map((page) => page.name).sort()).toEqual(
      report.visual.pages.map((page) => page.name).sort(),
    );
    expect(report.pageLint).toMatchObject({ passed: 15, failed: 0, skipped: 0 });

    expect(report.functional.steps.map((step) => step.name)).toEqual([...FUNCTIONAL_STEP_NAMES]);
    expect(report.functional.steps.map((step) => step.status)).toEqual([
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'skipped',
    ]);
    // The fixture's first percent or fixed code with no minimum.
    expect(
      report.functional.steps.find((step) => step.name === 'applyDiscountCode')?.detail,
    ).toContain('WELCOME10');
    expect(report.functional.steps.at(-1)?.detail).toBe('not supported by backend');
    expect(report.functional).toMatchObject({ passed: 10, failed: 0, skipped: 1 });
    expect(report).toMatchObject({
      passed: 39,
      failed: 1,
      skipped: 1,
      storefrontUrl,
      model: MODEL,
    });
    expect(result).toMatchObject({ passed: 39, failed: 1, skipped: 1 });

    expect((await fs.readdir(path.join(outDir, 'pages'))).sort()).toHaveLength(15);
    expect(await fs.readdir(path.join(outDir, 'screenshots'))).toHaveLength(30);
    const summary = await fs.readFile(path.join(outDir, 'summary.md'), 'utf-8');
    expect(summary).toContain('39 passed, 1 failed, 1 skipped');
    expect(summary).toContain('| search | /search?q=');
    expect(summary).toContain('## Page lint');
    expect(summary).toContain(
      '| cartDrawer | /products/shopliseum-mushroom-dog-toys?cart=open | pass | - |',
    );
    expect(lines.some((line) => line.includes('final_eval: capturing home'))).toBe(true);
  }, 180_000);

  it('records skipped pages and steps when the dataset has no product', async () => {
    const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'empty-data-'));
    for (const name of ['collections', 'products', 'pages', 'policies']) {
      await fs.writeFile(path.join(dataDir, `${name}.json`), '[]');
    }
    const outDir = path.join(dataDir, 'final_eval');
    const result = await runFinalEval({
      dataDir,
      backendUrl: 'http://127.0.0.1:1',
      storefrontUrl,
      llm: new ScriptedJudge(),
      model: MODEL,
      outDir,
    });
    const skipped = result.report.visual.pages.filter((page) => page.status === 'skipped');
    expect(skipped.map((page) => page.name).sort()).toEqual(
      [
        'accountProfile',
        'addresses',
        'cart',
        'checkout',
        'collection',
        'orderDetail',
        'orderList',
        'policy',
        'product',
        'cartDrawer',
        'thankYou',
      ].sort(),
    );
    expect(
      result.report.pageLint.pages.filter((page) => page.status === 'skipped').map((p) => p.name),
    ).toEqual(skipped.map((page) => page.name));
    expect(skipped.find((page) => page.name === 'cart')?.reason).toContain('no product');
    expect(result.report.functional.steps.find((step) => step.name === 'addToCart')?.status).toBe(
      'skipped',
    );
    expect(
      result.report.functional.steps.find((step) => step.name === 'applyDiscountCode')?.status,
    ).toBe('skipped');
    expect(result.report.functional.steps.find((step) => step.name === 'checkout')?.status).toBe(
      'fail',
    );
  }, 180_000);

  it('fails the page lint of the open cart drawer when its backdrop is a giant pill', async () => {
    const url = await serve({
      relabel: { '.cart-backdrop{border-radius:0': '.cart-backdrop{border-radius:999px' },
    });
    const outDir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'final-eval-')), 'final_eval');
    const result = await runFinalEval({
      dataDir: FIXTURE_DIR,
      backendUrl: 'http://127.0.0.1:1',
      storefrontUrl: url,
      llm: new ScriptedJudge(),
      model: MODEL,
      outDir,
    });
    const failed = result.report.pageLint.pages.filter(
      (page): page is Extract<PageLintResult, { status: 'fail' }> => page.status === 'fail',
    );
    expect(failed.map((page) => page.name)).toEqual(['cartDrawer']);
    expect(failed[0]?.issues.map((issue) => [issue.rule, issue.selector, issue.viewports])).toEqual(
      [['drawer_backdrop', 'main > div.cart-popup > button.cart-backdrop', ['desktop', 'mobile']]],
    );
    expect(result.report.pageLint).toMatchObject({ passed: 14, failed: 1, skipped: 0 });
    expect(result.failed).toBe(2); // the judge's `/search` and the drawer backdrop
    const summary = await fs.readFile(path.join(outDir, 'summary.md'), 'utf-8');
    expect(summary).toContain(
      '| cartDrawer | /products/shopliseum-mushroom-dog-toys?cart=open | fail | drawer_backdrop',
    );
  }, 180_000);
});
