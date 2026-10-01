/**
 * `runFinalEval` against a stateful `node:http` storefront stub (cookie
 * session and cart) with a scripted judge. Checks the report layout; the
 * real template is covered by the slow storefront test.
 */

import * as fs from 'node:fs/promises';
import * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { defaultBackendTemplateDir } from '../build/seed.js';
import { type FinalEvalReport, runFinalEval } from './final_eval.js';
import { FUNCTIONAL_STEP_NAMES } from './functional_sweep.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
const MODEL = { provider: 'fake', id: 'judge' };
const USAGE = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 };

class ScriptedJudge implements LlmClient {
  readonly requests: CompleteRequest[] = [];
  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    const failing =
      typeof request.prompt !== 'string' && request.prompt.text.includes('Route: `/search');
    const text = JSON.stringify({
      verdict: failing ? 'fail' : 'pass',
      score: failing ? 5 : 8,
      categoryScores: { structure: 8, components: 8, visualTone: 8 },
      feedback: failing ? 'No results grid.' : 'Looks finished.',
      issues: failing
        ? [{ viewport: 'both', severity: 'major', summary: 'empty results', capability: null }]
        : [],
    });
    return { text, model: 'm', stopReason: 'stop', usage: USAGE };
  }
}

function html(body: string, loggedIn: boolean): string {
  const logout = loggedIn
    ? '<form method="post" action="/account/logout"><button type="submit">Log out</button></form>'
    : '<a href="/account/login">Log in</a>';
  return `<!doctype html><html><head><title>Stub</title></head><body><header><nav><a href="/">Home</a><a href="/collections/dog-essentials">Dogs</a>${logout}</nav></header><main>${body}</main><footer><a href="/policies/privacy-policy">Privacy</a></footer></body></html>`;
}

/** Cookie `session=1` marks a logged-in customer, `cart=1` a non-empty cart. */
function stubStorefront(): http.Server {
  return http.createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    const cookies = req.headers.cookie ?? '';
    const loggedIn = cookies.includes('session=1');
    const hasCart = cookies.includes('cart=1');
    const page = (body: string): void => {
      res.writeHead(200, { 'content-type': 'text/html' });
      res.end(html(body, loggedIn));
    };
    const redirect = (location: string, cookie?: string): void => {
      res.writeHead(302, { location, ...(cookie ? { 'set-cookie': cookie } : {}) });
      res.end();
    };
    if (req.method === 'POST') {
      let raw = '';
      req.on('data', (chunk) => {
        raw += chunk;
      });
      req.on('end', () => {
        const form = new URLSearchParams(raw);
        switch (url.pathname) {
          case '/account/register':
          case '/account/login':
            redirect('/account', 'session=1; Path=/');
            return;
          case '/account/logout':
            redirect('/', 'session=; Path=/; Max-Age=0');
            return;
          case '/cart':
            redirect(form.get('redirectTo') ?? '/cart', 'cart=1; Path=/');
            return;
          case '/checkout':
            redirect(
              loggedIn ? '/account/orders/1001' : '/checkout/confirmation/1001',
              'cart=; Path=/; Max-Age=0',
            );
            return;
          default:
            redirect('/');
        }
      });
      return;
    }
    switch (true) {
      case url.pathname === '/account/login':
        page(
          '<h1>Log in</h1><form method="post"><input name="email"><input name="password" type="password"><button type="submit">Log in</button></form>',
        );
        return;
      case url.pathname === '/account/register':
        page(
          '<h1>Create account</h1><form method="post"><input name="firstName"><input name="lastName"><input name="email"><input name="password" type="password"><button type="submit">Create account</button></form>',
        );
        return;
      case url.pathname.startsWith('/account'):
        if (!loggedIn) {
          redirect(`/account/login?redirectTo=${encodeURIComponent(url.pathname)}`);
          return;
        }
        page(
          url.pathname.startsWith('/account/orders/')
            ? `<h1>Order #${url.pathname.split('/').at(-1)}</h1>`
            : '<h1>Account</h1>',
        );
        return;
      case url.pathname.startsWith('/products/'):
        page(
          '<h1>Product</h1><form method="post" action="/cart" class="product-form"><input type="hidden" name="redirectTo" value="/cart"><input type="hidden" name="intent" value="add"><input type="radio" name="merchandiseId" value="gid://shopify/ProductVariant/1" checked><button type="submit">Add to cart</button></form>',
        );
        return;
      case url.pathname === '/cart':
        page(
          hasCart
            ? '<h1>Cart</h1><p>1 x Product</p><p>Subtotal CA$10.00</p>'
            : '<h1>Cart</h1><p>Your cart is empty.</p>',
        );
        return;
      case url.pathname === '/checkout':
        if (!hasCart) {
          redirect('/cart');
          return;
        }
        page(
          '<h1>Checkout</h1><form method="post"><input name="email"><input name="firstName"><input name="lastName"><input name="address1"><input name="city"><input name="province"><input name="country"><input name="zip"><input type="radio" name="shippingMethodHandle" value="standard"><input type="radio" name="paymentMethodHandle" value="card"><button type="submit">Place order</button></form>',
        );
        return;
      default:
        page(`<h1>${url.pathname}</h1>`);
    }
  });
}

let server: http.Server;
let storefrontUrl: string;

beforeAll(async () => {
  server = stubStorefront();
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('no port');
  storefrontUrl = `http://127.0.0.1:${address.port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

describe('runFinalEval', () => {
  it('writes the report, per-page files and screenshots and counts both sweeps', async () => {
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
        'policy',
        'cart',
        'checkout',
        'accountProfile',
        'orderDetail',
      ].sort(),
    );
    expect(report.visual.pages.every((page) => page.status !== 'skipped')).toBe(true);
    expect(report.visual).toMatchObject({ passed: 9, failed: 1, skipped: 0 });
    const search = report.visual.pages.find((page) => page.name === 'search');
    expect(search).toMatchObject({ status: 'fail', score: 5, httpStatus: 200 });
    expect(search?.screenshots.map((shot) => shot.path)).toEqual([
      'screenshots/search__desktop.png',
      'screenshots/search__mobile.png',
    ]);
    const orderDetail = report.visual.pages.find((page) => page.name === 'orderDetail');
    expect(orderDetail?.route).toBe('/account/orders/1001');
    expect(judge.requests).toHaveLength(10);

    expect(report.functional.steps.map((step) => step.name)).toEqual([...FUNCTIONAL_STEP_NAMES]);
    expect(report.functional.steps.map((step) => step.status)).toEqual([
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'pass',
      'skipped',
    ]);
    expect(report.functional.steps.at(-1)?.detail).toBe('not supported by backend');
    expect(report.functional).toMatchObject({ passed: 6, failed: 0, skipped: 1 });
    expect(report).toMatchObject({
      passed: 15,
      failed: 1,
      skipped: 1,
      storefrontUrl,
      model: MODEL,
    });
    expect(result).toMatchObject({ passed: 15, failed: 1, skipped: 1 });

    expect((await fs.readdir(path.join(outDir, 'pages'))).sort()).toHaveLength(10);
    expect(await fs.readdir(path.join(outDir, 'screenshots'))).toHaveLength(20);
    const summary = await fs.readFile(path.join(outDir, 'summary.md'), 'utf-8');
    expect(summary).toContain('15 passed, 1 failed, 1 skipped');
    expect(summary).toContain('| search | /search?q=');
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
        'cart',
        'checkout',
        'collection',
        'orderDetail',
        'policy',
        'product',
      ].sort(),
    );
    expect(skipped.find((page) => page.name === 'cart')?.reason).toContain('no product');
    expect(result.report.functional.steps.find((step) => step.name === 'addToCart')?.status).toBe(
      'skipped',
    );
    expect(result.report.functional.steps.find((step) => step.name === 'checkout')?.status).toBe(
      'fail',
    );
  }, 180_000);
});
