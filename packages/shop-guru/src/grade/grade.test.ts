import type { Completion, LlmClient } from '@shop-gym/agent';
import { BrowserSession } from '@shop-gym/browser';
import type { Check, Task } from '@shop-gym/core';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { BackendClient } from '../backend.js';
import {
  type Backend,
  type FakeStorefront,
  SHOP_PAGES,
  startBackend,
  startFakeStorefront,
} from '../testing/fixtures.js';
import { grade } from './grade.js';

const VARIANT = 'gid://shopify/ProductVariant/47642512195758';
const MODEL = { provider: 'fake', id: 'judge' };

let backend: Backend;
let shop: FakeStorefront;
let session: BrowserSession;
let client: BackendClient;

function task(evalChecks: Check[]): Task {
  return {
    id: 'fixture-exact-1',
    shop: 'fixture',
    skill: 'exact',
    goal: 'g',
    eval: evalChecks,
    source: 'seed',
  };
}

function fakeJudge(reply: string): LlmClient & { prompts: string[]; images: number } {
  const seen = { prompts: [] as string[], images: 0 };
  return {
    ...seen,
    async complete(request): Promise<Completion> {
      seen.prompts.push(typeof request.prompt === 'string' ? request.prompt : request.prompt.text);
      if (typeof request.prompt !== 'string') seen.images += request.prompt.images?.length ?? 0;
      return {
        text: reply,
        model: 'judge',
        stopReason: 'stop',
        usage: { input: 3, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0.01 },
      };
    },
    get prompts() {
      return seen.prompts;
    },
    get images() {
      return seen.images;
    },
  };
}

beforeAll(async () => {
  backend = await startBackend();
  shop = await startFakeStorefront(SHOP_PAGES);
  session = await BrowserSession.launch({ episodeId: 'grade-ep', baseUrl: shop.url });
  client = new BackendClient(backend.url, 'grade-ep');
  await client.reset();
}, 60_000);

afterAll(async () => {
  await session.close();
  await shop.close();
  await backend.server.close();
});

describe('grade string_match and url_match', () => {
  it('passes when the answer and final url satisfy the checks', async () => {
    const result = await grade({
      task: task([
        { type: 'string_match', mustInclude: ['blue', 'collar'] },
        { type: 'url_match', url: '/cart', rule: 'exact' },
      ]),
      answer: 'The Blue Collar',
      finalUrl: `${shop.url}/cart`,
      baseUrl: shop.url,
    });
    expect(result.passed).toBe(true);
    expect(result.checks.map((c) => c.passed)).toEqual([true, true]);
  });

  it('fails with details when the answer is missing or the url differs', async () => {
    const result = await grade({
      task: task([
        { type: 'string_match', exactMatch: '42' },
        { type: 'url_match', url: '/cart', rule: 'prefix' },
      ]),
      answer: null,
      finalUrl: `${shop.url}/`,
      baseUrl: shop.url,
    });
    expect(result.passed).toBe(false);
    expect(result.checks[0]).toMatchObject({ passed: false, detail: 'no answer' });
    expect(result.checks[1]?.passed).toBe(false);
  });
});

describe('grade locator_probe', () => {
  it('probes the page the agent ended on for url "last"', async () => {
    await session.page.goto(`${shop.url}/collections/dog-essentials`);
    const result = await grade({
      task: task([
        {
          type: 'locator_probe',
          url: 'last',
          locator: '.product .title',
          required: { exactMatch: 'AisleArena Anti Tick Collar' },
        },
        {
          type: 'locator_probe',
          url: 'last',
          locator: 'h1',
          required: { mustInclude: ['dog essentials'] },
        },
      ]),
      answer: null,
      finalUrl: session.page.url(),
      baseUrl: shop.url,
      session,
    });
    expect(result.checks.map((c) => c.passed)).toEqual([true, true]);
    expect(result.checks[0]?.detail).toContain('2 match(es)');
  });

  it('navigates to an explicit url and fails on no match or wrong text', async () => {
    const result = await grade({
      task: task([
        {
          type: 'locator_probe',
          url: '/cart',
          locator: '.total',
          required: { mustInclude: ['$29.98'] },
        },
        {
          type: 'locator_probe',
          url: '/cart',
          locator: '.missing',
          required: { mustInclude: ['x'] },
        },
        { type: 'locator_probe', url: '/cart', locator: 'h1', required: { exactMatch: 'Cart' } },
      ]),
      answer: null,
      finalUrl: null,
      baseUrl: shop.url,
      session,
    });
    expect(result.checks.map((c) => c.passed)).toEqual([true, false, false]);
    expect(result.checks[1]?.detail).toContain('matched nothing');
    expect(session.page.url()).toBe(`${shop.url}/cart`);
  });

  it('fails without a browser session', async () => {
    const result = await grade({
      task: task([
        { type: 'locator_probe', url: 'last', locator: 'h1', required: { mustInclude: ['x'] } },
      ]),
      answer: null,
      finalUrl: null,
      baseUrl: shop.url,
    });
    expect(result.checks[0]).toMatchObject({ passed: false, detail: 'no browser session' });
  });
});

describe('grade state_check', () => {
  it('reads the real episode snapshot from the control API', async () => {
    const created = await client.graphql<{ cartCreate: { cart: { id: string } } }>(
      'mutation($lines: [CartLineInput!]) { cartCreate(input: { lines: $lines }) { cart { id } } }',
      { lines: [{ merchandiseId: VARIANT, quantity: 2 }] },
    );
    expect(created.cartCreate.cart.id).toBeTruthy();

    const result = await grade({
      task: task([
        {
          type: 'state_check',
          path: '/carts',
          match: 'some',
          value: { lines: [{ merchandiseId: VARIANT, quantity: 2 }] },
        },
        { type: 'state_check', path: '/carts/0/lines/0/quantity', match: 'equals', value: 2 },
        { type: 'state_check', path: '/orders/0/name', match: 'equals', value: '#1001' },
        { type: 'state_check', path: '/carts', match: 'some', value: { lines: [{ quantity: 3 }] } },
        { type: 'state_check', path: '/nope', match: 'equals', value: 1 },
      ]),
      answer: null,
      finalUrl: null,
      baseUrl: shop.url,
      backend: client,
    });
    expect(result.checks.map((c) => c.passed)).toEqual([true, true, true, false, false]);
    expect(result.checks[4]?.detail).toBe('nothing at /nope');
  });

  it('sees a fresh branch under another episode id', async () => {
    const other = new BackendClient(backend.url, 'grade-ep-other');
    await other.reset();
    const result = await grade({
      task: task([{ type: 'state_check', path: '/carts', match: 'equals', value: [] }]),
      answer: null,
      finalUrl: null,
      baseUrl: shop.url,
      backend: other,
    });
    expect(result.passed).toBe(true);
  });
});

describe('grade llm_judge', () => {
  it('runs the judge after programmatic checks with the screenshot attached', async () => {
    const judgeClient = fakeJudge('{"passed": true, "reason": "looks right"}');
    const result = await grade({
      task: task([
        { type: 'llm_judge', rubric: 'Cart holds one collar.' },
        { type: 'string_match', mustInclude: ['x'] },
      ]),
      answer: 'x marks the spot',
      finalUrl: `${shop.url}/cart`,
      baseUrl: shop.url,
      judge: { client: judgeClient, model: MODEL },
      screenshot: Buffer.from('png'),
    });
    expect(result.passed).toBe(true);
    expect(result.checks.map((c) => c.check.type)).toEqual(['string_match', 'llm_judge']);
    expect(result.checks[1]?.detail).toBe('looks right');
    expect(result.usage.input).toBe(3);
    expect(judgeClient.images).toBe(1);
    expect(judgeClient.prompts[0]).toContain('Cart holds one collar.');
    expect(judgeClient.prompts[0]).toContain('string_match: pass');
  });

  it('fails the judge check when no judge is configured', async () => {
    const result = await grade({
      task: task([{ type: 'llm_judge', rubric: 'r' }]),
      answer: null,
      finalUrl: null,
      baseUrl: shop.url,
    });
    expect(result.checks[0]).toMatchObject({ passed: false, detail: 'no judge configured' });
  });

  it('uses the judge for fuzzyMatch only after literal checks pass', async () => {
    const judgeClient = fakeJudge('{"passed": false, "reason": "different total"}');
    const result = await grade({
      task: task([
        { type: 'string_match', mustInclude: ['total'], fuzzyMatch: 'The total is 29.98' },
      ]),
      answer: 'total: 30',
      finalUrl: null,
      baseUrl: shop.url,
      judge: { client: judgeClient, model: MODEL },
    });
    expect(result.checks[0]).toMatchObject({ passed: false, detail: 'different total' });
    expect(judgeClient.prompts[0]).toContain('The total is 29.98');
  });
});
