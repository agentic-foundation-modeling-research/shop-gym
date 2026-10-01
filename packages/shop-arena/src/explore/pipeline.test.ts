import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';
import { FakeRuntime, type FakeScript } from '@shop-gym/agent/testing';
import { StepFailedError } from '@shop-gym/core';
import { ResumeRefusedError, type RunSummary } from '@shop-gym/harness';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { exploreStorefront, parseModel, runId } from './pipeline.js';

const CREDENTIALS = {} as const;
const HOME =
  '<!doctype html><html><head><title>Fixture Shop | Home</title></head><body><h1>Welcome</h1></body></html>';
const PRODUCTS = {
  products: [
    {
      id: 1,
      title: 'Vase',
      options: [{ name: 'Size' }],
      variants: [{ price: '10.00' }, { price: '12.00' }],
    },
    { id: 2, title: 'Bowl', options: [{ name: 'Color' }], variants: [{ price: '8.50' }] },
  ],
};
const COLLECTIONS = { collections: [{ handle: 'all', products_count: 2 }] };

const PLAN = (homepage: string, cart: string) => `# Plan - Minimal Homeware Shop

A small homeware storefront with a single collection.

## Tasks

- [${homepage}] homepage_sections — capture every section [priority: 9]
- [${cart}] cart_drawer — add 1 product and capture the drawer [priority: 8]

## Omitted Areas

- mega_menu - header is single-row links only.
`;

const CLEAN_HOMEPAGE = `## Homepage Sections

### Section 1 - Hero

- **Type:** full-bleed hero banner
- **Layout:** single column
- **Content:** headline and one call to action
- **Behavior:** static
- **Styling:** light surface
- **UX Notes:** none
`;

const LEAKY_HOMEPAGE = `${CLEAN_HOMEPAGE}
The storefront is branded Fixture Shop throughout.
`;

const CART_PART = `## Cart Drawer

### Filled state

- **Type:** slide-in drawer
- **Layout:** single column
- **Content:** line items with quantity steppers
- **Behavior:** opens on add to cart
- **Styling:** overlay
- **UX Notes:** none
`;

const MANUAL = `# Shop Manual - Minimal Homeware Shop

## Overview

A compact homeware storefront with one collection and a drawer cart. The
header is a single row of links; the homepage opens with a full-bleed
hero followed by a featured collection grid.

## UX Patterns Summary

| Pattern | Implementation |
| --- | --- |
| Navigation | single-row header |
| Floating Surfaces | none observed |
`;

const SCRIPTS: readonly FakeScript[] = [
  { writeFiles: { 'plan.md': PLAN(' ', ' ') }, reply: 'planned' },
  {
    writeFiles: {
      'artifact/parts/homepage_sections.md': LEAKY_HOMEPAGE,
      'artifact/parts/homepage_sections.caps.json': JSON.stringify({
        homepage: { section_types: ['hero', 'featured_collection'], section_count: 2 },
        shop: { descriptor: 'Minimal Homeware Shop', currency: 'USD' },
      }),
      'plan.md': PLAN('x', ' '),
    },
    reply: 'homepage done (leaky)',
  },
  {
    writeFiles: {
      'artifact/parts/homepage_sections.md': CLEAN_HOMEPAGE,
      'plan.md': PLAN('x', ' '),
    },
    reply: 'homepage done',
  },
  {
    writeFiles: {
      'artifact/parts/cart_drawer.md': CART_PART,
      'artifact/parts/cart_drawer.caps.json': JSON.stringify({
        cart: { type: 'drawer', has_promo_input: true },
        checkout: { has_guest_checkout: true, payment_methods: ['card'] },
      }),
      'plan.md': PLAN('x', 'x'),
    },
    reply: 'cart done',
  },
];

class StubLlm implements LlmClient {
  readonly requests: CompleteRequest[] = [];

  constructor(private readonly text: string = MANUAL) {}

  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    return {
      text: this.text,
      model: request.model.id,
      stopReason: 'end_turn',
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
    };
  }
}

let server: http.Server;
let baseUrl = '';
let root: string;
let outDir: string;

beforeAll(async () => {
  server = http.createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    const json = (body: unknown) =>
      res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(body));
    switch (url.pathname) {
      case '/robots.txt':
        return res.writeHead(200).end('User-agent: *\nAllow: /\n');
      case '/':
        return res.writeHead(200, { 'content-type': 'text/html' }).end(HOME);
      case '/products.json':
        return json(url.searchParams.get('page') === '1' ? PRODUCTS : { products: [] });
      case '/collections.json':
        return json(COLLECTIONS);
      case '/cart.js':
        return json({ currency: 'USD', items: [] });
      case '/cart':
      case '/search':
        return res.writeHead(200, { 'content-type': 'text/html' }).end('<html>page</html>');
      default:
        return res.writeHead(404).end();
    }
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'explore-'));
  outDir = join(root, 'out', runId(baseUrl, 'fake'));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

function explore(options: {
  scripts?: readonly FakeScript[];
  llm?: StubLlm;
  from?: 'prefetch' | 'explore' | 'merge' | 'synthesize';
  forceResume?: boolean;
}) {
  const runtime = new FakeRuntime(options.scripts ?? []);
  const llm = options.llm ?? new StubLlm();
  return exploreStorefront({
    url: baseUrl,
    outDir,
    model: 'anthropic/test-model',
    maxIters: 5,
    timeoutMs: 60_000,
    rateLimitMs: 0,
    credentials: CREDENTIALS,
    runtime,
    llm,
    ...(options.from ? { from: options.from } : {}),
    ...(options.forceResume ? { forceResume: true } : {}),
  }).then((result) => ({ result, runtime, llm }));
}

const readJson = (path: string) => JSON.parse(readFileSync(path, 'utf8'));

describe('exploreStorefront', { timeout: 60_000 }, () => {
  it('runs every step and publishes the manual, capabilities, stats, and manifest', async () => {
    const { result, runtime, llm } = await explore({ scripts: SCRIPTS });

    expect(result.steps.map((step) => [step.id, step.status])).toEqual([
      ['prefetch', 'ran'],
      ['explore', 'ran'],
      ['merge', 'ran'],
      ['synthesize', 'ran'],
    ]);
    expect(result.finalStatus).toBe('completed');
    for (const file of [
      'seed/prefetch/prefetch.json',
      'seed/prefetch/index.html',
      'run/plan.md',
      'run/run.json',
      'run/artifact/prefetch/index.html',
      'run/artifact/parts/cart_drawer.caps.json',
      'explore.json',
      'capabilities.json',
      'stats.json',
      'manifest.json',
      'manual.md',
    ]) {
      expect(existsSync(join(outDir, file)), file).toBe(true);
    }

    // Planner, leaky executor, fixed executor, cart executor.
    expect(runtime.requests).toHaveLength(4);
    expect(runtime.requests[2]?.prompt).toContain('Anonymization check failed');
    const toolNames = runtime.requests[1]?.tools.map((tool) => tool.name) ?? [];
    expect(toolNames).toEqual(expect.arrayContaining(['navigate', 'snapshot', 'write_file']));
    expect(runtime.requests[0]?.systemPrompt).toContain('"checkout"');
    const summary = readJson(join(outDir, 'run', 'run.json')) as RunSummary;
    expect(summary.verifierRuns.some((run) => run.verdict === 'fail')).toBe(true);

    const capabilities = readJson(result.capabilitiesPath);
    expect(capabilities.cart.type).toBe('drawer');
    expect(capabilities.checkout.payment_methods).toEqual(['card']);
    expect(capabilities.homepage.section_count).toBe(2);

    const stats = readJson(result.statsPath);
    expect(stats.products_total).toBe(2);
    expect(stats.collections_total).toBe(1);
    expect(stats.price).toEqual({ min: 8.5, max: 12, median: 10, currency: 'USD' });
    expect(stats.variant_axes_observed).toEqual(['size', 'color']);
    expect(stats.homepage_section_count).toBe(2);

    const manifest = readJson(result.manifestPath);
    expect(manifest).toMatchObject({
      run_id: basename(outDir),
      domain: '127.0.0.1',
      runtime: 'fake',
      model: 'anthropic/test-model',
      harness_status: 'completed',
      plan_tasks_total: 2,
      plan_tasks_done: 2,
      plan_tasks_blocked: 0,
      omitted_areas: [{ area: 'mega_menu', reason: 'header is single-row links only.' }],
      capability_conflicts: [],
    });
    expect(manifest.coverage_gaps).toEqual(['collection', 'product_detail', 'search_results']);

    expect(readFileSync(result.manualPath, 'utf8')).toBe(MANUAL);
    expect(llm.requests).toHaveLength(1);
    expect(llm.requests[0]?.prompt).toContain('## Capabilities');
    expect(llm.requests[0]?.prompt).toContain('### Filled state');
    expect(llm.requests[0]?.model).toEqual({ provider: 'anthropic', id: 'test-model' });
  });

  it('skips every step on a second call with the same outDir', async () => {
    await explore({ scripts: SCRIPTS });
    const { result, runtime, llm } = await explore({});
    expect(result.steps.every((step) => step.status === 'skipped')).toBe(true);
    expect(runtime.requests).toHaveLength(0);
    expect(llm.requests).toHaveLength(0);
  });

  it('reruns only the forced step and its dependents with from', async () => {
    await explore({ scripts: SCRIPTS });
    const second = await explore({ from: 'synthesize', llm: new StubLlm(`${MANUAL}\nUpdated.\n`) });
    expect(second.result.steps.map((step) => step.status)).toEqual([
      'skipped',
      'skipped',
      'skipped',
      'ran',
    ]);
    expect(readFileSync(second.result.manualPath, 'utf8')).toContain('Updated.');

    // Re-merging the same parts leaves capabilities.json byte-identical, so
    // synthesize is not stale and stays skipped.
    const third = await explore({ from: 'merge' });
    expect(third.result.steps.map((step) => step.status)).toEqual([
      'skipped',
      'skipped',
      'ran',
      'skipped',
    ]);
    expect(third.runtime.requests).toHaveLength(0);
  });

  it('fails the synthesize step when the manual is too short', async () => {
    await expect(
      explore({ scripts: SCRIPTS, llm: new StubLlm('# Shop Manual\n') }),
    ).rejects.toThrow(/manual response too short/);
    expect(existsSync(join(outDir, 'manual.md'))).toBe(false);
    expect(existsSync(join(outDir, 'capabilities.json'))).toBe(true);
  });

  it('resumes a refused harness run only with forceResume', async () => {
    const first = await explore({
      scripts: [{ writeFiles: { 'plan.md': PLAN(' ', ' ') }, status: 'error', error: 'boom' }],
    });
    expect(first.result.finalStatus).toBe('runtime_error');
    expect(existsSync(join(outDir, 'capabilities.json'))).toBe(true);

    await expect(explore({ from: 'explore', scripts: SCRIPTS })).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof StepFailedError && error.cause instanceof ResumeRefusedError,
    );

    // The failed planner iteration is quarantined, so the resume replans first.
    const resumed = await explore({ from: 'explore', scripts: SCRIPTS, forceResume: true });
    expect(resumed.result.finalStatus).toBe('completed');
    expect(resumed.runtime.requests).toHaveLength(4);
    expect(readJson(resumed.result.manifestPath).plan_tasks_done).toBe(2);
  });
});

describe('parseModel', () => {
  it('splits provider and id at the first slash', () => {
    expect(parseModel('anthropic/claude-opus-4-7')).toEqual({
      provider: 'anthropic',
      id: 'claude-opus-4-7',
    });
    expect(parseModel('openai/org/model')).toEqual({ provider: 'openai', id: 'org/model' });
  });

  it('rejects strings without a provider or id', () => {
    expect(() => parseModel('claude')).toThrow(/provider\/model-id/);
    expect(() => parseModel('anthropic/')).toThrow(/provider\/model-id/);
  });
});

describe('runId', () => {
  it('combines a UTC stamp with a stable hash of url and runtime', () => {
    const now = new Date('2026-09-30T12:34:56.789Z');
    const id = runId('https://example-shop.com', 'pi', now);
    expect(id).toMatch(/^20260930T123456Z-[0-9a-f]{8}$/);
    expect(runId('https://example-shop.com', 'pi', now)).toBe(id);
    expect(runId('https://example-shop.com', 'fake', now)).not.toBe(id);
  });
});
