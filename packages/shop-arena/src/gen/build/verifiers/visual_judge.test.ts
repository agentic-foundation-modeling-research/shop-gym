/**
 * `visual_judge` against a static page served from `node:http`, captured
 * with a real `BrowserSession` and judged by a scripted `LlmClient`. The
 * live block (`SHOPGYM_LIVE=1`) sends one real judge call.
 */

import * as fs from 'node:fs/promises';
import * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  type CompleteRequest,
  type Completion,
  type LlmClient,
  PiLlmClient,
  type PromptContent,
} from '@shop-gym/agent';
import { loadCredentials } from '@shop-gym/core';
import type { VerifierContext } from '@shop-gym/harness';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { defaultBackendTemplateDir } from '../seed.js';
import { judgeContext, routeSlug } from './page_judge.js';
import { type RetryBudgetState, VISUAL_BUDGET_FILE, visualJudgeVerifier } from './visual_judge.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
const REPO_ROOT = fileURLToPath(new URL('../../../../../..', import.meta.url));
const [LIVE_PROVIDER = 'openai', LIVE_MODEL_ID = 'gpt-5.5'] = (
  process.env.SHOPGYM_LIVE_MODEL ?? 'openai/gpt-5.5'
).split('/', 2);
const MODEL = { provider: 'fake', id: 'judge' };
const USAGE = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 };

const PAGE = `<!doctype html><html><head><title>Sample Shop</title>
<style>body{margin:0;font-family:sans-serif}header,footer{background:#123;color:#fff;padding:16px}main{padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px}.card{border:1px solid #ccc;padding:12px}</style>
</head><body><header><nav><a href="/">Home</a> <a href="/collections">Shop</a></nav></header>
<main><h1>Everything for happy pets</h1><p>Toys, treats and essentials.</p>
<div class="grid">${Array.from({ length: 8 }, (_, i) => `<div class="card">Product ${i + 1}<br>$${10 + i}.00</div>`).join('')}</div></main>
<footer><a href="/pages/about-us">About</a> <a href="/policies/privacy-policy">Privacy</a></footer></body></html>`;

class ScriptedJudge implements LlmClient {
  readonly requests: CompleteRequest[] = [];
  constructor(private readonly reply: () => string) {}
  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    return { text: this.reply(), model: 'm', stopReason: 'stop', usage: USAGE };
  }
}

const PASS_VERDICT = {
  verdict: 'pass',
  score: 8.5,
  categoryScores: { structure: 9, components: 8, visualTone: 8 },
  feedback: 'Clear hero, a product grid and a complete shell.',
  issues: [],
};
const FAIL_VERDICT = {
  verdict: 'fail',
  score: 4,
  categoryScores: { structure: 4, components: 4, visualTone: 5 },
  feedback: 'The grid collapses to one column on mobile and the header has no logo.',
  issues: [
    {
      viewport: 'mobile',
      severity: 'major',
      summary: 'single-column grid',
      capability: 'homepage',
    },
  ],
};

let server: http.Server;
let url: string;
let runDir: string;
let manualDir: string;
let requestedPaths: string[] = [];

beforeAll(async () => {
  server = http.createServer((req, res) => {
    requestedPaths.push(req.url ?? '');
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(PAGE);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('no port');
  url = `http://127.0.0.1:${address.port}`;
  manualDir = await fs.mkdtemp(path.join(os.tmpdir(), 'manual-'));
  await fs.mkdir(path.join(manualDir, 'parts'));
  await fs.writeFile(
    path.join(manualDir, 'capabilities.json'),
    JSON.stringify({ homepage: { hero: true, featured_collections: 2 }, cart: { drawer: false } }),
  );
  await fs.writeFile(path.join(manualDir, 'parts', 'homepage.md'), '# Homepage\nHero then grid.\n');
  await fs.writeFile(path.join(manualDir, 'parts', 'cart.md'), '# Cart\nDrawer-less.\n');
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

beforeEach(async () => {
  runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'visual-judge-'));
  requestedPaths = [];
});

function ctx(selectedTaskId: string, iterId = 'exec-0001'): VerifierContext {
  return { runDir, iterId, selectedTaskId, plan: [], artifactDir: path.join(runDir, 'artifact') };
}

describe('judgeContext', () => {
  it('slices capabilities by bucket and picks matching manual parts', async () => {
    const context = await judgeContext(manualDir, ['homepage']);
    expect(context.capabilities).toContain('featured_collections');
    expect(context.capabilities).not.toContain('drawer');
    expect(context.manual).toContain('Hero then grid');
    expect(context.manual).not.toContain('Drawer-less');
    expect(await judgeContext(undefined, ['homepage'])).toEqual({ capabilities: '', manual: '' });
  });

  it('names screenshots after the route', () => {
    expect(routeSlug('/')).toBe('home');
    expect(routeSlug('/collections/dog-essentials')).toBe('collections-dog-essentials');
    expect(routeSlug('/search?q=dog')).toBe('search');
  });
});

describe('visual_judge', () => {
  it('applies to storefront page tasks only', () => {
    const verifier = visualJudgeVerifier({
      target: { url },
      dataDir: FIXTURE_DIR,
      llm: new ScriptedJudge(() => ''),
      model: MODEL,
    });
    expect(verifier.appliesTo('gen_homepage')).toBe(true);
    expect(verifier.appliesTo('visual_fix')).toBe(true);
    expect(verifier.appliesTo('gen_theme')).toBe(false);
    expect(verifier.appliesTo('gen_backend')).toBe(false);
  });

  it('captures both viewports, sends them with the rubric and context, and passes', async () => {
    const judge = new ScriptedJudge(() => JSON.stringify(PASS_VERDICT));
    const verifier = visualJudgeVerifier({
      target: { url },
      dataDir: FIXTURE_DIR,
      manualDir,
      llm: judge,
      model: MODEL,
    });
    const result = await verifier.run(ctx('gen_homepage'));
    expect(result.verdict).toBe('pass');
    const checksDir = path.join(runDir, 'iters', 'exec-0001', 'checks', 'visual_judge');
    expect((await fs.readdir(checksDir)).sort()).toEqual(['home__desktop.png', 'home__mobile.png']);
    expect(judge.requests).toHaveLength(1);
    const prompt = judge.requests[0]?.prompt as PromptContent;
    expect(prompt.images?.map((image) => image.mimeType)).toEqual(['image/png', 'image/png']);
    expect(prompt.text).toContain('visual quality judge');
    expect(prompt.text).toContain('featured_collections');
    expect(prompt.text).toContain('Hero then grid');
    expect(result.details).toMatchObject({ buckets: ['homepage'], score: 8.5 });
  }, 60_000);

  it('adds a product to the cart before judging cart routes', async () => {
    const judge = new ScriptedJudge(() => JSON.stringify(PASS_VERDICT));
    const verifier = visualJudgeVerifier({
      target: { url },
      dataDir: FIXTURE_DIR,
      llm: judge,
      model: MODEL,
    });
    const result = await verifier.run(ctx('gen_cart_search'));
    expect(result.verdict).toBe('pass');
    const productVisit = requestedPaths.findIndex((p) => p.startsWith('/products/'));
    expect(productVisit).toBeGreaterThanOrEqual(0);
    expect(productVisit).toBeLessThan(requestedPaths.indexOf('/cart'));
    expect(result.details).toMatchObject({
      buckets: ['cart_search'],
      cartSeed: expect.stringContaining('no add-to-cart form'),
    });
  }, 60_000);

  it('logs in as the seeded customer after the login page and before the account page', async () => {
    const judge = new ScriptedJudge(() => JSON.stringify(PASS_VERDICT));
    const verifier = visualJudgeVerifier({
      target: { url },
      dataDir: FIXTURE_DIR,
      llm: judge,
      model: MODEL,
    });
    const result = await verifier.run(ctx('visual_fix'));
    expect(result.verdict).toBe('pass');
    const loginAttempt = requestedPaths.lastIndexOf('/account/login');
    expect(loginAttempt).toBeGreaterThan(requestedPaths.indexOf('/account/login'));
    expect(loginAttempt).toBeLessThan(requestedPaths.indexOf('/account'));
    expect(result.details).toMatchObject({
      accountSeed: expect.stringContaining('no form with the expected fields'),
    });
  }, 90_000);

  it("returns the failing pages' screenshots as images", async () => {
    const judge = new ScriptedJudge(() => JSON.stringify(FAIL_VERDICT));
    const verifier = visualJudgeVerifier({
      target: { url },
      dataDir: FIXTURE_DIR,
      llm: judge,
      model: MODEL,
    });
    const result = await verifier.run(ctx('gen_homepage'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('screenshots of the failing pages are attached');
    const checksDir = path.join(runDir, 'iters', 'exec-0001', 'checks', 'visual_judge');
    expect(result.images).toEqual([
      path.join(checksDir, 'home__desktop.png'),
      path.join(checksDir, 'home__mobile.png'),
    ]);
  }, 60_000);

  it('fails until the per-task retry budget is spent, then reports advisory', async () => {
    const judge = new ScriptedJudge(() => JSON.stringify(FAIL_VERDICT));
    const verifier = visualJudgeVerifier({
      target: { url },
      dataDir: FIXTURE_DIR,
      llm: judge,
      model: MODEL,
      retryBudget: 2,
    });
    const first = await verifier.run(ctx('gen_homepage', 'exec-0001'));
    expect(first.verdict).toBe('fail');
    expect(first.feedback).toContain('single-column grid');
    const second = await verifier.run(ctx('gen_homepage', 'exec-0002'));
    expect(second.verdict).toBe('fail');
    const budgetFile = path.join(runDir, VISUAL_BUDGET_FILE);
    expect(JSON.parse(await fs.readFile(budgetFile, 'utf-8'))).toEqual({ gen_homepage: 2 });
    const third = await verifier.run(ctx('gen_homepage', 'exec-0003'));
    expect(third.verdict).toBe('advisory');
    const budget = (third.details as { retryBudget: RetryBudgetState }).retryBudget;
    expect(budget).toEqual({ budget: 2, priorFailures: 2, exhausted: true });
    const otherTask = await verifier.run(ctx('gen_product', 'exec-0004'));
    expect(otherTask.verdict).toBe('fail');
  }, 120_000);

  it('fails without calling the judge when a page cannot be captured', async () => {
    const judge = new ScriptedJudge(() => JSON.stringify(PASS_VERDICT));
    const verifier = visualJudgeVerifier({
      target: { url: 'http://127.0.0.1:1' },
      dataDir: FIXTURE_DIR,
      llm: judge,
      model: MODEL,
    });
    const result = await verifier.run(ctx('gen_homepage'));
    expect(result.verdict).toBe('fail');
    expect(judge.requests).toHaveLength(0);
    expect(result.feedback).toContain('page did not load');
  }, 60_000);

  it.skipIf(!process.env.SHOPGYM_LIVE)(
    'gets a structured verdict from the live judge',
    async () => {
      const llm = new PiLlmClient({ credentials: loadCredentials(REPO_ROOT, process.env) });
      const verifier = visualJudgeVerifier({
        target: { url },
        dataDir: FIXTURE_DIR,
        manualDir,
        llm,
        model: { provider: LIVE_PROVIDER, id: LIVE_MODEL_ID },
      });
      const result = await verifier.run(ctx('gen_homepage'));
      console.log('live visual_judge', JSON.stringify(result, null, 2));
      expect(['pass', 'fail']).toContain(result.verdict);
      const details = result.details as {
        pages: { route: string; effective: string; score: number; issues: unknown[] }[];
      };
      expect(details.pages).toHaveLength(1);
      expect(details.pages[0]).toMatchObject({ route: '/', effective: result.verdict });
      expect(details.pages[0]?.score).toBeGreaterThanOrEqual(0);
      expect(details.pages[0]?.score).toBeLessThanOrEqual(10);
      expect(Array.isArray(details.pages[0]?.issues)).toBe(true);
    },
    180_000,
  );
});
