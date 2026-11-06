import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';

import { type CompleteRequest, type Completion, type LlmClient, promptText } from '@shop-gym/agent';
import { FakeRuntime, type FakeScript } from '@shop-gym/agent/testing';
import { StepFailedError } from '@shop-gym/core';
import { ResumeRefusedError, type RunSummary } from '@shop-gym/harness';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { FixedAreaGap } from './coverage.js';
import { exploreStorefront, parseModel, runId } from './pipeline.js';
import { DEFAULT_USER_AGENT, PRODUCTS_PAGE_LIMIT } from './prefetch.js';
import { type FixtureSite, genericSitePages, startFixtureSite } from './testing.js';

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

/** A fragment with every marketplace Capability of schema 0.3. */
const MARKETPLACE_CAPS = {
  departments: { has_department_menu: true, department_count: 24, max_depth: 3 },
  search: { facets: ['brand', 'price', 'rating'], sort: ['featured', 'price_asc', 'newest'] },
  product: {
    has_rating_histogram: true,
    review_filters: ['star_rating', 'verified_purchase'],
    related_product_types: ['bought_together', 'also_viewed', 'sponsored'],
  },
};

const MARKETPLACE_SCRIPTS: readonly FakeScript[] = [
  { writeFiles: { 'plan.md': PLAN(' ', ' ') }, reply: 'planned' },
  {
    writeFiles: {
      'artifact/parts/homepage_sections.md': CLEAN_HOMEPAGE,
      'artifact/parts/homepage_sections.caps.json': JSON.stringify(MARKETPLACE_CAPS),
      'plan.md': PLAN('x', ' '),
    },
    reply: 'homepage done',
  },
  {
    writeFiles: { 'artifact/parts/cart_drawer.md': CART_PART, 'plan.md': PLAN('x', 'x') },
    reply: 'cart done',
  },
];

/** The 14 canonical Plan task ids, in planner order, that every run must plan. */
const EXPECTED_FIXED_AREAS = [
  'homepage_sections',
  'header_navigation',
  'cart_drawer',
  'product_variants',
  'product_reviews',
  'related_products',
  'collection_filters',
  'search_predictive',
  'search_results',
  'checkout_flow',
  'account_pages',
  'footer',
  'info_pages',
  'floating_widgets',
];

/**
 * A plan with every fixed area at one priority. Ties go to source order,
 * so the executor takes `search_results`, then `product_reviews`.
 */
function fixedPlan(lines: Readonly<Record<string, string>> = {}): string {
  const first = ['search_results', 'product_reviews'];
  const tasks = [...first, ...EXPECTED_FIXED_AREAS.filter((area) => !first.includes(area))].map(
    (id) => lines[id] ?? `- [ ] ${id} — open the area; capture it [priority: 5]`,
  );
  return `# Plan - Minimal Homeware Shop

A small homeware storefront with a single collection.

## Tasks

${tasks.join('\n')}

## Omitted Areas

(none)
`;
}

const SEARCH_RESULTS_PART = `## Search Results

### Results grid

- **Type:** full-page results grid
- **Layout:** facet column beside a product grid
- **Content:** product cards with price and rating
- **Behavior:** facets refine the grid in place
- **Styling:** light surface
- **UX Notes:** none
`;

const FIXED_AREA_SCRIPTS: readonly FakeScript[] = [
  { writeFiles: { 'plan.md': fixedPlan() }, reply: 'planned' },
  {
    writeFiles: {
      'artifact/parts/search_results.md': SEARCH_RESULTS_PART,
      'plan.md': fixedPlan({
        search_results: '- [x] search_results — open the area; capture it [priority: 5]',
      }),
    },
    reply: 'search results done',
  },
  {
    writeFiles: {
      'plan.md': fixedPlan({
        search_results: '- [x] search_results — open the area; capture it [priority: 5]',
        product_reviews:
          '- [!] product_reviews — open the area; capture it; reviews need a sign-in; none is public [priority: 5]',
      }),
    },
    reply: 'product reviews blocked',
  },
];

/** A `capabilities.json` that Storefront exploration published at schema 0.2. */
const CAPABILITIES_0_2 = {
  version: '0.2',
  shop: { descriptor: 'Minimal Homeware Shop', category: null, currency: 'USD', tone: [] },
  cart: { type: 'drawer', has_promo_input: true, has_upsells: null, has_shipping_estimate: null },
  search: { trigger: 'icon', has_predictive: true, predictive_types: [], results_layout: null },
};

/** The capabilities JSON Schema that the agent constitution shows. */
function constitutionSchema(systemPrompt: string | undefined): {
  properties: Record<string, { default?: unknown; properties?: Record<string, unknown> }>;
} {
  const block = /```json\n([\s\S]*?)\n```/.exec(systemPrompt ?? '')?.[1];
  if (block === undefined) throw new Error('the constitution has no JSON Schema block');
  return JSON.parse(block);
}

/** The ids of the `[ ]` task lines in a planner prompt, in prompt order. */
function plannedIds(prompt: string): (string | undefined)[] {
  return [...prompt.matchAll(/^- \[ \] ([a-z0-9_]+)\s+— /gm)].map((match) => match[1]);
}

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
  url?: string;
  scripts?: readonly FakeScript[];
  llm?: StubLlm;
  from?: 'prefetch' | 'explore' | 'merge' | 'synthesize';
  forceResume?: boolean;
  maxIters?: number;
}) {
  const runtime = new FakeRuntime(options.scripts ?? []);
  const llm = options.llm ?? new StubLlm();
  return exploreStorefront({
    url: options.url ?? baseUrl,
    outDir,
    model: 'anthropic/test-model',
    maxIters: options.maxIters ?? 5,
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

  it('shows the 0.3 schema to the agent and publishes the marketplace Capabilities', async () => {
    const { result, runtime } = await explore({ scripts: MARKETPLACE_SCRIPTS });

    const schema = constitutionSchema(runtime.requests[0]?.systemPrompt);
    expect(schema.properties.version?.default).toBe('0.3');
    expect(Object.keys(schema.properties.departments?.properties ?? {})).toEqual([
      'has_department_menu',
      'department_count',
      'max_depth',
    ]);
    expect(Object.keys(schema.properties.search?.properties ?? {})).toEqual(
      expect.arrayContaining(['facets', 'sort']),
    );
    expect(Object.keys(schema.properties.product?.properties ?? {})).toEqual(
      expect.arrayContaining(['has_rating_histogram', 'review_filters', 'related_product_types']),
    );

    expect(result.steps.map((step) => step.status)).toEqual(['ran', 'ran', 'ran', 'ran']);
    const capabilities = readJson(result.capabilitiesPath);
    expect(capabilities.version).toBe('0.3');
    expect(capabilities).toMatchObject(MARKETPLACE_CAPS);
  });

  it('synthesizes again from a capabilities.json at schema 0.2', async () => {
    await explore({ scripts: SCRIPTS });
    writeFileSync(join(outDir, 'capabilities.json'), JSON.stringify(CAPABILITIES_0_2));

    const { result, llm } = await explore({ from: 'synthesize' });
    expect(result.steps.map((step) => step.status)).toEqual([
      'skipped',
      'skipped',
      'skipped',
      'ran',
    ]);
    const prompt = String(llm.requests[0]?.prompt);
    expect(prompt).toContain('"version": "0.2"');
    expect(prompt).toContain('"has_department_menu": null');
    expect(prompt).toContain('"facets": []');
  });

  it('reports the area of an unfinished Plan task as a coverage gap', async () => {
    // The budget ends after the homepage iteration, so cart_drawer stays pending.
    const { result } = await explore({
      scripts: [
        { writeFiles: { 'plan.md': PLAN(' ', ' ') }, reply: 'planned' },
        {
          writeFiles: {
            'artifact/parts/homepage_sections.md': CLEAN_HOMEPAGE,
            'plan.md': PLAN('x', ' '),
          },
          reply: 'homepage done',
        },
      ],
      maxIters: 1,
    });

    expect(result.finalStatus).toBe('budget_exhausted');
    const manifest = readJson(result.manifestPath);
    expect(manifest).toMatchObject({ plan_tasks_total: 2, plan_tasks_done: 1 });
    expect(manifest.coverage_gaps).toEqual([
      'cart',
      'collection',
      'product_detail',
      'search_results',
    ]);
  });

  it('plans the 14 fixed areas within 4 navigations and records each unfinished one as a gap with a reason', async () => {
    // The budget ends after two executor iterations: search_results is
    // done, product_reviews is blocked, and the other areas stay pending.
    const { result, runtime } = await explore({ scripts: FIXED_AREA_SCRIPTS, maxIters: 2 });

    const planner = promptText(runtime.requests[0]?.prompt ?? '');
    expect(plannedIds(planner)).toEqual(EXPECTED_FIXED_AREAS);
    expect(planner).toContain('<= 4 `navigate` calls');

    expect(result.finalStatus).toBe('budget_exhausted');
    const manifest = readJson(result.manifestPath);
    expect(manifest.coverage_gaps).not.toContain('search_results');
    const gaps: FixedAreaGap[] = manifest.fixed_area_gaps;
    expect(gaps.map((gap) => gap.area)).toEqual(
      EXPECTED_FIXED_AREAS.filter((area) => area !== 'search_results'),
    );
    // The reason is the text after the planned brief, `;` included.
    expect(gaps).toContainEqual({
      area: 'product_reviews',
      reason: 'blocked: reviews need a sign-in; none is public',
    });
    expect(gaps).toContainEqual({
      area: 'related_products',
      reason: 'not started when the run ended',
    });
  });

  it('takes the shopify path when products.json returns a product list', async () => {
    const { result, runtime } = await explore({ scripts: SCRIPTS });

    expect(readJson(result.manifestPath).platform).toBe('shopify');
    const paths = readJson(join(result.prefetchDir, 'prefetch.json')).entries.map(
      (entry: { path: string }) => entry.path,
    );
    expect(paths).toEqual(
      expect.arrayContaining(['/collections.json?limit=50', '/cart.js', '/pages/faq']),
    );
    expect(runtime.requests[0]?.prompt).toBe(
      readFileSync(new URL('./prompts/planner.md', import.meta.url), 'utf8'),
    );
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

const GENERIC_PLAN = (homepage: string, product: string) => `# Plan - General Marketplace

A general marketplace with department menus, a search results page, and
product pages with reviews.

## Tasks

- [${homepage}] homepage_sections — capture every section below the hero [priority: 9]
- [${product}] product_variants — open /p/fm-1001 from the sitemap; capture the variant selectors [priority: 7]

## Omitted Areas

(none)
`;

const GENERIC_HOMEPAGE = `## Homepage Sections

### Section 1 - Hero

- **Type:** promotional banner with one call to action
- **Layout:** single column
- **Content:** headline and a link to a department
- **Behavior:** static
- **Styling:** light surface
- **UX Notes:** none
`;

const GENERIC_PRODUCT = `## Product Variants

### Variant selectors

- **Type:** two rows of option buttons (edition, platform)
- **Layout:** below the price
- **Content:** one button per option
- **Behavior:** a click selects the option
- **Styling:** outlined buttons
- **UX Notes:** none
`;

/** Planner, homepage executor, and product executor scripts for the generic site. */
function genericScripts(siteUrl: string): readonly FakeScript[] {
  return [
    {
      writeFiles: { 'plan.md': GENERIC_PLAN(' ', ' ') },
      toolCalls: [{ tool: 'navigate', arguments: { url: `${siteUrl}/` } }],
      reply: 'planned',
    },
    {
      writeFiles: {
        'artifact/parts/homepage_sections.md': GENERIC_HOMEPAGE,
        'artifact/parts/homepage_sections.caps.json': JSON.stringify({
          homepage: { section_types: ['hero', 'product_grid'], section_count: 2 },
        }),
        'plan.md': GENERIC_PLAN('x', ' '),
      },
      reply: 'homepage done',
    },
    {
      writeFiles: {
        'artifact/parts/product_variants.md': GENERIC_PRODUCT,
        'artifact/parts/product_variants.caps.json': JSON.stringify({
          product: { variant_selectors: ['option_button'], has_reviews: true },
        }),
        'plan.md': GENERIC_PLAN('x', 'x'),
      },
      toolCalls: [{ tool: 'navigate', arguments: { url: `${siteUrl}/p/fm-1001` } }],
      reply: 'product done',
    },
  ];
}

describe('exploreStorefront on a generic site', { timeout: 60_000 }, () => {
  let site: FixtureSite;

  beforeEach(async () => {
    site = await startFixtureSite(genericSitePages);
  });

  afterEach(async () => {
    await site.close();
  });

  it('takes the generic path on a site that is not a Shopify shop', async () => {
    const { result, runtime } = await explore({
      url: site.url,
      scripts: genericScripts(site.url),
    });

    expect(result.steps.map((step) => [step.id, step.status])).toEqual([
      ['prefetch', 'ran'],
      ['explore', 'ran'],
      ['merge', 'ran'],
      ['synthesize', 'ran'],
    ]);
    expect(result.finalStatus).toBe('completed');
    expect(readJson(result.manifestPath).platform).toBe('generic');

    // Prefetch reads robots.txt, the homepage and the sitemap. The one
    // products.json request is the platform probe; no other Shopify
    // endpoint is requested.
    const prefetched = site.requests
      .filter((request) => request.userAgent === DEFAULT_USER_AGENT)
      .map((request) => request.path);
    expect(prefetched).toEqual([
      '/robots.txt',
      '/',
      '/sitemap.xml',
      `/products.json?page=1&limit=${PRODUCTS_PAGE_LIMIT}`,
    ]);
    // The planner picks same-origin start URLs from the homepage links and the sitemap.
    const planner = promptText(runtime.requests[0]?.prompt ?? '').replace(/\s+/g, ' ');
    expect(planner).toContain('Pick your start URLs from the links in `index.html`');
    expect(planner).toContain('the `<loc>` entries of `sitemap.xml`');
    expect(planner).toContain('Use only URLs on the same origin as the homepage');

    // The scripted executor opened a product page with the real browser tools.
    expect(
      site.requests.some(
        (request) => request.path === '/p/fm-1001' && request.userAgent !== DEFAULT_USER_AGENT,
      ),
    ).toBe(true);

    // With no Shopify prefetch files, merge and synthesis still publish the
    // manual, and the catalog counts stay 0.
    for (const file of ['robots.txt', 'index.html', 'sitemap.xml', 'prefetch.json']) {
      expect(existsSync(join(result.prefetchDir, file)), file).toBe(true);
    }
    for (const file of ['products.json', 'collections.json', 'cart.js']) {
      expect(existsSync(join(result.prefetchDir, file)), file).toBe(false);
    }
    const stats = readJson(result.statsPath);
    expect(stats.products_total).toBe(0);
    expect(stats.collections_total).toBe(0);
    expect(stats.products_per_collection).toEqual({ avg: 0, median: 0, max: 0 });
    expect(readJson(result.manifestPath).coverage_gaps).toEqual([]);
    expect(readFileSync(result.manualPath, 'utf8')).toBe(MANUAL);
  });

  it('asks the generic planner for the 14 fixed areas within 4 navigations', async () => {
    const { runtime } = await explore({ url: site.url, scripts: genericScripts(site.url) });

    const planner = promptText(runtime.requests[0]?.prompt ?? '');
    expect(planner).toContain('explore planner for a generic site');
    expect(plannedIds(planner)).toEqual(EXPECTED_FIXED_AREAS);
    expect(planner).toContain('<= 4 `navigate` calls');
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
