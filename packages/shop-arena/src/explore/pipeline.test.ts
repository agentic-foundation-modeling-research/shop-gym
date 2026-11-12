import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';

import {
  type CompleteRequest,
  type Completion,
  type LlmClient,
  promptText,
  readTrajectory,
} from '@shop-gym/agent';
import { FakeRuntime, type FakeScript } from '@shop-gym/agent/testing';
import { SiteGraphValidationError, StepFailedError, parseSiteGraph } from '@shop-gym/core';
import { NOTE_PREFIX, ResumeRefusedError, type RunSummary } from '@shop-gym/harness';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { AnonymizationLeakError } from './anonymization.js';
import { NAVIGATION_CAP } from './browser.js';
import type { FixedAreaGap } from './coverage.js';
import { SiteGraphReplyError } from './graph.js';
import { type ExploreStep, exploreStorefront, parseModel, runId } from './pipeline.js';
import { DEFAULT_USER_AGENT, PRODUCTS_PAGE_LIMIT, ShopUnreachableError } from './prefetch.js';
import {
  BOT_CHECK_PAGE,
  type FixturePage,
  type FixtureSite,
  GENERIC_SITE_HOSTNAME,
  INTERSTITIAL_PAGE,
  RATE_LIMIT_PAGE,
  genericSitePages,
  startFixtureSite,
} from './testing.js';

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

/** An executor that writes the leaky homepage fragment again and marks it done. */
const LEAKY_HOMEPAGE_ATTEMPT: FakeScript = {
  writeFiles: {
    'artifact/parts/homepage_sections.md': LEAKY_HOMEPAGE,
    'plan.md': PLAN('x', ' '),
  },
  reply: 'homepage done (leaky)',
};

const HOMEPAGE_BLOCKED = `- [!] homepage_sections [priority: 9] ${NOTE_PREFIX} anonymization: parts/homepage_sections.md still identifies the storefront after 2 reopens`;

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

/** The `[ ]` task lines of a planner prompt as `[id, brief]` pairs, in prompt order. */
function plannedTasks(prompt: string): [string | undefined, string | undefined][] {
  return [...prompt.matchAll(/^- \[ \] ([a-z0-9_]+)\s+— (.*) \[priority: \d+\]$/gm)].map(
    (match) => [match[1], match[2]],
  );
}

/** The ids of the `[ ]` task lines in a planner prompt, in prompt order. */
function plannedIds(prompt: string): (string | undefined)[] {
  return plannedTasks(prompt).map(([id]) => id);
}

/** The brief of the `[ ]` task line `id` in a planner prompt. */
function plannedBrief(prompt: string, id: string): string {
  const brief = plannedTasks(prompt).find(([taskId]) => taskId === id)?.[1];
  if (brief === undefined) throw new Error(`the planner prompt plans no ${id} task`);
  return brief;
}

/**
 * Checks that the briefs keep the executor on the storefront pages that a
 * visitor sees, also in a brief that the planner makes more specific. The
 * same rules hold on every platform.
 */
function expectStorefrontBriefs(planner: string): void {
  expect(plannedBrief(planner, 'collection_filters')).toMatch(
    /^start on .*department or category landing page, not a search results page; /,
  );
  // The product page shows the review block; the all-reviews page can ask for a sign-in.
  const reviews = plannedBrief(planner, 'product_reviews');
  expect(reviews).toMatch(/^scroll a product page to its review block /);
  expect(reviews).toContain('skip all-reviews pages behind sign-in');
  // The suggestion API can be on another host, so the evidence is the dropdown.
  const predictive = plannedBrief(planner, 'search_predictive');
  expect(predictive).toContain(
    'type 2 prefixes into the search box; snapshot each suggestion dropdown',
  );
  expect(predictive).toContain('stay on storefront pages, no network or API capture');
  expect(predictive).not.toMatch(/network capture|suggest\.json/);
  // The planner adds paths and queries to the briefs, and the rules above stay.
  const prose = planner.replace(/\s+/g, ' ');
  expect(prose).toContain('A tweaked brief keeps every rule of its canonical brief');
  expect(prose).toContain('the paths and queries that you add do not count');
}

/** Checks that one Plan task owns the shop block, so the block does not stay empty. */
function expectShopBlockOwner(planner: string): void {
  expect(plannedBrief(planner, 'homepage_sections')).toContain(
    'fill the shop block (`shop`): descriptor, category, currency code, tone',
  );
}

/** A Site state graph with no states, which is valid for any finished parts. */
const EMPTY_GRAPH = { version: '0.1', states: [], transitions: [] };

/**
 * A Site state graph whose transitions come from the finished parts of
 * `SCRIPTS`. Its `home` state passes the scan, although the fixture title
 * "Fixture Shop | Home" has a "Home" segment.
 */
const SITE_GRAPH = {
  version: '0.1',
  states: [
    { id: 'home', kind: 'page', page_type: 'home', url_pattern: '/' },
    { id: 'product', kind: 'page', page_type: 'product', url_pattern: '/products/{handle}' },
    { id: 'cart_drawer', kind: 'overlay', overlay: 'side_sheet', on: ['product'] },
  ],
  transitions: [
    {
      from: 'home',
      to: 'product',
      trigger: 'click',
      action: 'open_product',
      effect: 'navigate',
      source: 'homepage_sections',
    },
    {
      from: 'product',
      to: 'cart_drawer',
      trigger: 'click',
      action: 'add_to_cart',
      effect: 'open_overlay',
      needs: ['variant'],
      source: 'cart_drawer',
    },
    {
      from: 'cart_drawer',
      to: 'product',
      trigger: 'click',
      action: 'close_cart',
      effect: 'close_overlay',
      source: 'cart_drawer',
    },
  ],
};

/** `value` as JSON in one fenced block, as a model often replies. */
function fencedJson(value: unknown): string {
  return `\`\`\`json\n${JSON.stringify(value, null, 2)}\n\`\`\`\n`;
}

/** True for the graph call, whose prompt starts with the title of the graph prompt. */
function isGraphRequest(request: CompleteRequest): boolean {
  const title = readPrompt('site_graph.md').split('\n', 1)[0] ?? '';
  return promptText(request.prompt).startsWith(title);
}

/**
 * A scripted completion client: the synthesis call gets `text` and the
 * graph call gets `graph`.
 */
class StubLlm implements LlmClient {
  readonly requests: CompleteRequest[] = [];

  constructor(
    private readonly text: string = MANUAL,
    private readonly graph: string = JSON.stringify(EMPTY_GRAPH),
  ) {}

  /** The one graph request. */
  graphRequest(): CompleteRequest {
    const [request, ...others] = this.requests.filter(isGraphRequest);
    expect(others).toEqual([]);
    if (request === undefined) throw new Error('the graph step made no request');
    return request;
  }

  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    return {
      text: isGraphRequest(request) ? this.graph : this.text,
      model: request.model.id,
      stopReason: 'end_turn',
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
    };
  }
}

/** The fixture's guest carts, keyed by the `cart` cookie. */
const carts = new Map<string, { variant_id: number; quantity: number }[]>();
/** The paths that the fixture shop served in the current test. */
const shopRequests: string[] = [];

function cartToken(req: http.IncomingMessage): string | undefined {
  return /(?:^|;\s*)cart=([^;]+)/.exec(req.headers.cookie ?? '')?.[1];
}

let server: http.Server;
let baseUrl = '';
let root: string;
let outDir: string;

beforeAll(async () => {
  server = http.createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    shopRequests.push(url.pathname);
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
      case '/cart/add': {
        // A guest cart lives on the server, found by the `cart` cookie.
        const token = cartToken(req) ?? `cart-${carts.size + 1}`;
        const lines = carts.get(token) ?? [];
        lines.push({ variant_id: Number(url.searchParams.get('id')), quantity: 1 });
        carts.set(token, lines);
        return res
          .writeHead(200, { 'content-type': 'text/html', 'set-cookie': `cart=${token}; Path=/` })
          .end('<html><head><title>Cart</title></head><body>Added</body></html>');
      }
      case '/cart.js':
        return json({ currency: 'USD', items: carts.get(cartToken(req) ?? '') ?? [] });
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
  shopRequests.length = 0;
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
  from?: ExploreStep;
  forceResume?: boolean;
  maxIters?: number;
  focus?: string;
  brandTerms?: readonly string[];
}) {
  const runtime = new FakeRuntime(options.scripts ?? []);
  const llm = options.llm ?? new StubLlm();
  const logs: string[] = [];
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
    ...(options.focus !== undefined ? { focus: options.focus } : {}),
    ...(options.brandTerms ? { brandTerms: options.brandTerms } : {}),
    log: (line) => logs.push(line),
  }).then((result) => ({ result, runtime, llm, logs }));
}

const readJson = (path: string) => JSON.parse(readFileSync(path, 'utf8'));
const readPrompt = (name: string) =>
  readFileSync(new URL(`./prompts/${name}`, import.meta.url), 'utf8');

describe('exploreStorefront', { timeout: 60_000 }, () => {
  it('runs every step and publishes the manual, capabilities, stats, and manifest', async () => {
    const { result, runtime, llm } = await explore({ scripts: SCRIPTS });

    expect(result.steps.map((step) => [step.id, step.status])).toEqual([
      ['prefetch', 'ran'],
      ['explore', 'ran'],
      ['merge', 'ran'],
      ['synthesize', 'ran'],
      ['graph', 'ran'],
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
      'site_graph.json',
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
    // The synthesis call, then the graph call.
    expect(llm.requests).toHaveLength(2);
    expect(llm.requests[1]).toBe(llm.graphRequest());
    expect(llm.requests[0]?.prompt).toContain('## Capabilities');
    expect(llm.requests[0]?.prompt).toContain('### Filled state');
    expect(llm.requests[0]?.model).toEqual({ provider: 'anthropic', id: 'test-model' });
  });

  it('tells every executor to write only what it saw and to mark the rest as unknown', async () => {
    const { runtime } = await explore({ scripts: SCRIPTS });

    const shared = (runtime.requests[1]?.systemPrompt ?? '').replace(/\s+/g, ' ');
    expect(shared).toContain('Write only what you saw.');
    expect(shared).toContain(
      'a snapshot, a screenshot, or a prefetch file or a response that you read',
    );
    expect(shared).toContain('Do not guess, do not compare with a page that you did not open');
    expect(shared).toContain(
      'write "unknown" in the markdown and leave its capabilities field `null`',
    );
    expect(shared).toContain('Use `false` only when you saw the place where the feature would be');
    expect(shared).toContain('A count or a depth stays `null` when you saw only part of it');
    const executor = promptText(runtime.requests[1]?.prompt ?? '').replace(/\s+/g, ' ');
    expect(executor).toContain(
      'Mark a field `N/A` when it does not apply and `unknown` when you did not see it',
    );
    expect(executor).toContain('learns what the run could not see');
  });

  it('tells the executors and the synthesizer to put site-specific names and lists into generic words', async () => {
    const { runtime, llm } = await explore({ scripts: SCRIPTS });

    const shared = (runtime.requests[1]?.systemPrompt ?? '').replace(/\s+/g, ' ');
    const synthesizer = promptText(llm.requests[0]?.prompt ?? '').replace(/\s+/g, ' ');
    for (const prompt of [shared, synthesizer]) {
      expect(prompt).toContain('Do not list what only this site has');
      expect(prompt).toContain('Do not name request endpoints, query parameters, response fields');
      expect(prompt).toContain(
        "not the site's own name for it, even when that name comes from a URL path or a page title",
      );
      expect(prompt).toContain(
        'generic program types, such as a paid membership or a loyalty program, without their own names',
      );
    }
    expect(synthesizer).toContain('rewrite only the words that break a rule of this prompt');
  });

  it('tells the synthesizer to state only what the parts show and to mark the rest as unknown', async () => {
    const { llm } = await explore({ scripts: SCRIPTS });

    const synthesizer = promptText(llm.requests[0]?.prompt ?? '').replace(/\s+/g, ' ');
    expect(synthesizer).toContain('**State only what the parts show.**');
    expect(synthesizer).toContain(
      'Drop guesses, comparisons with a page or a state that no part describes',
    );
    expect(synthesizer).toContain('Write a partial view as partial');
    expect(synthesizer).toContain(
      'When a part says that it did not see something, mark it as unknown',
    );
  });

  it('tells the synthesizer that no sentence may contradict the capabilities', async () => {
    const { llm } = await explore({ scripts: SCRIPTS });

    const synthesizer = promptText(llm.requests[0]?.prompt ?? '').replace(/\s+/g, ' ');
    expect(synthesizer).toContain('No sentence may contradict it');
    expect(synthesizer).toContain('a sentence that reports what a page says about a later step');
    expect(synthesizer).toContain(
      'A `null` field means that the run did not see it: when you write about it, write it as unknown, not as absent',
    );
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

  it('takes the Shopify stats from the catalog endpoints', async () => {
    const { result } = await explore({ scripts: SCRIPTS });

    const stats = readJson(result.statsPath);
    expect(stats.source).toBe('catalog_endpoint');
    expect(stats.sample_size).toBe(2);
  });

  it('does not ask the Shopify executors for product observations', async () => {
    const { runtime } = await explore({ scripts: SCRIPTS });
    expect(promptText(runtime.requests[1]?.prompt ?? '')).not.toMatch(/product observation/i);
    expect(runtime.requests[1]?.tools.map((tool) => tool.name)).not.toContain(
      'record_product_observation',
    );
  });

  it('reopens a leaking task twice, then blocks it without touching the other task', async () => {
    const { result, runtime } = await explore({
      scripts: [
        { writeFiles: { 'plan.md': PLAN(' ', ' ') }, reply: 'planned' },
        LEAKY_HOMEPAGE_ATTEMPT,
        LEAKY_HOMEPAGE_ATTEMPT,
        LEAKY_HOMEPAGE_ATTEMPT,
        {
          writeFiles: {
            'artifact/parts/cart_drawer.md': CART_PART,
            'plan.md': PLAN('x', 'x').replace(/^- \[x\] homepage_sections .*$/m, HOMEPAGE_BLOCKED),
          },
          reply: 'cart done',
        },
      ],
    });
    expect(result.finalStatus).toBe('completed');

    // Planner, three homepage attempts, one cart attempt.
    expect(runtime.requests).toHaveLength(5);
    expect(runtime.requests[2]?.prompt).toContain('1 of 2 reopens');
    expect(runtime.requests[3]?.prompt).toContain('2 of 2 reopens');
    const planBeforeCart = readFileSync(join(outDir, 'run/iters/exec-0004/plan.before.md'), 'utf8');
    expect(planBeforeCart).toContain(HOMEPAGE_BLOCKED);

    // The leaky homepage fragment is still on disk: the cart task passes and
    // does not see the homepage feedback.
    expect(runtime.requests[4]?.prompt).toContain('selected_task_id: cart_drawer');
    expect(runtime.requests[4]?.prompt).not.toContain('Anonymization check failed');
    const summary = readJson(join(outDir, 'run', 'run.json')) as RunSummary;
    expect(summary.verifierRuns.map((run) => [run.taskId, run.verdict])).toEqual([
      ['homepage_sections', 'fail'],
      ['homepage_sections', 'fail'],
      ['homepage_sections', 'fail'],
      ['cart_drawer', 'pass'],
    ]);
    expect(readJson(result.manifestPath)).toMatchObject({
      plan_tasks_total: 2,
      plan_tasks_done: 1,
      plan_tasks_blocked: 1,
    });
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

    expect(result.steps.map((step) => step.status)).toEqual(['ran', 'ran', 'ran', 'ran', 'ran']);
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
      'ran',
    ]);
    const prompt = String(llm.requests[0]?.prompt);
    expect(prompt).toContain('"version": "0.2"');
    expect(prompt).toContain('"has_department_menu": null');
    expect(prompt).toContain('"facets": []');
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

  it('keeps the fixed-area briefs on storefront pages', async () => {
    const { runtime } = await explore({ scripts: SCRIPTS });

    expectStorefrontBriefs(promptText(runtime.requests[0]?.prompt ?? ''));
  });

  it('gives the shop block to homepage_sections', async () => {
    const { runtime } = await explore({ scripts: SCRIPTS });

    expectShopBlockOwner(promptText(runtime.requests[0]?.prompt ?? ''));
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
      'skipped',
    ]);
    expect(readFileSync(second.result.manualPath, 'utf8')).toContain('Updated.');

    // Re-merging the same parts leaves capabilities.json byte-identical, so
    // synthesize is not stale and stays skipped. The graph reads the
    // manifest, which merge writes again with a new time, so it runs.
    const third = await explore({ from: 'merge' });
    expect(third.result.steps.map((step) => step.status)).toEqual([
      'skipped',
      'skipped',
      'ran',
      'skipped',
      'ran',
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

  it('starts every Iteration in a fresh browser, so a cart made in one is not in the next', async () => {
    const readCart = [
      { tool: 'navigate', arguments: { url: `${baseUrl}/cart.js` } },
      { tool: 'snapshot', arguments: {} },
    ];
    const { result } = await explore({
      scripts: [
        { writeFiles: { 'plan.md': PLAN(' ', ' ') } },
        {
          writeFiles: {
            'artifact/parts/homepage_sections.md': CLEAN_HOMEPAGE,
            'plan.md': PLAN('x', ' '),
          },
          toolCalls: [
            { tool: 'navigate', arguments: { url: `${baseUrl}/cart/add?id=101` } },
            ...readCart,
          ],
        },
        {
          writeFiles: { 'artifact/parts/cart_drawer.md': CART_PART, 'plan.md': PLAN('x', 'x') },
          toolCalls: readCart,
        },
      ],
    });
    expect(result.finalStatus).toBe('completed');

    const cartSnapshot = async (iterId: string): Promise<string | undefined> => {
      const { steps } = await readTrajectory(
        join(result.runDir, 'iters', iterId, 'trajectory.json'),
      );
      return steps.flatMap((step) => (step.kind === 'tool_result' ? [step.output] : [])).at(-1);
    };
    // The snapshot shows the `/cart.js` body: one line, then no lines.
    expect(await cartSnapshot('exec-0001')).toContain('variant_id');
    expect(await cartSnapshot('exec-0002')).not.toContain('variant_id');
  });

  it('records where the browser of every Iteration started', async () => {
    const { result } = await explore({
      scripts: [
        { writeFiles: { 'plan.md': PLAN(' ', ' ') } },
        {
          writeFiles: {
            'artifact/parts/homepage_sections.md': CLEAN_HOMEPAGE,
            'plan.md': PLAN('x', ' '),
          },
        },
        { writeFiles: { 'artifact/parts/cart_drawer.md': CART_PART, 'plan.md': PLAN('x', 'x') } },
      ],
    });
    expect(result.finalStatus).toBe('completed');

    for (const iterId of ['plan', 'exec-0001', 'exec-0002']) {
      expect(readJson(join(result.runDir, 'iters', iterId, 'start_state.json')), iterId).toEqual({
        url: `${baseUrl}/`,
        cart: { items: [] },
        error: null,
      });
    }
  });

  it('opens a site path from navigate on the storefront', async () => {
    const { result } = await explore({
      scripts: [
        {
          writeFiles: { 'plan.md': PLAN(' ', ' ') },
          toolCalls: [{ tool: 'navigate', arguments: { url: '/cart' } }],
        },
        {
          writeFiles: {
            'artifact/parts/homepage_sections.md': CLEAN_HOMEPAGE,
            'plan.md': PLAN('x', ' '),
          },
        },
        { writeFiles: { 'artifact/parts/cart_drawer.md': CART_PART, 'plan.md': PLAN('x', 'x') } },
      ],
    });
    expect(result.finalStatus).toBe('completed');

    const { steps } = await readTrajectory(join(result.runDir, 'iters', 'plan', 'trajectory.json'));
    expect(steps.find((step) => step.kind === 'tool_result')).toMatchObject({
      isError: false,
      output: expect.stringContaining(`Navigated to ${baseUrl}/cart\n`),
    });
  });

  it('stops at the prefetch gates before any Iteration starts', async () => {
    const gated = http.createServer((_req, res) =>
      res.writeHead(200).end('User-agent: *\nDisallow: /\n'),
    );
    await new Promise<void>((resolve) => gated.listen(0, '127.0.0.1', resolve));
    const runtime = new FakeRuntime(SCRIPTS);
    try {
      await expect(
        exploreStorefront({
          url: `http://127.0.0.1:${(gated.address() as AddressInfo).port}`,
          outDir,
          model: 'anthropic/test-model',
          rateLimitMs: 0,
          credentials: CREDENTIALS,
          runtime,
          llm: new StubLlm(),
        }),
      ).rejects.toSatisfy(
        (error: unknown) =>
          error instanceof StepFailedError && error.cause instanceof ShopUnreachableError,
      );
    } finally {
      await new Promise<void>((resolve) => gated.close(() => resolve()));
    }
    expect(runtime.requests).toHaveLength(0);
    expect(existsSync(join(outDir, 'run'))).toBe(false);
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

  it('gives the planner the focus as a hint and records it in manifest.json', async () => {
    const { result, runtime } = await explore({ scripts: SCRIPTS, focus: 'Video Games' });

    // The hint follows the unchanged planner prompt.
    const planner = promptText(runtime.requests[0]?.prompt ?? '');
    const prompt = readPrompt('planner.md');
    expect(planner.startsWith(prompt)).toBe(true);
    const hint = planner.slice(prompt.length).replace(/\s+/g, ' ');
    expect(hint).toContain('## Focus hint');
    expect(hint).toContain('"Video Games"');
    expect(hint).toContain('Keep every canonical task');
    // Executors get the focus only through the task briefs in plan.md.
    for (const request of runtime.requests.slice(1)) {
      expect(promptText(request.prompt)).not.toContain('Video Games');
    }
    expect(readJson(result.manifestPath).focus).toBe('Video Games');
  });

  it('refuses to continue a run with a focus other than the one it started with', async () => {
    await explore({ scripts: SCRIPTS, focus: 'Video Games' });

    // A resumed harness run keeps its plan, so the focus cannot change.
    await expect(explore({ from: 'merge', focus: 'Board Games' })).rejects.toThrow(
      /started with focus "Video Games"/,
    );
    await expect(explore({ from: 'merge' })).rejects.toThrow(/started with focus "Video Games"/);
    const { result } = await explore({ from: 'merge', focus: 'Video Games' });
    expect(readJson(result.manifestPath).focus).toBe('Video Games');
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

/** The product observation facts of the three product pages of the generic site. */
const OBSERVED = {
  '/p/fm-1001': {
    price: 59.99,
    currency: 'USD',
    has_variants: true,
    variant_axes: ['Edition', 'Platform'],
  },
  '/p/fm-1002': { price: 44.5, currency: 'USD', has_variants: true, variant_axes: ['Color'] },
  '/p/fm-1003': { price: 79, currency: 'USD', has_variants: false, variant_axes: [] },
} as const;

/** Tool calls that open `path` and record `facts` for it as a product observation of `taskId`. */
function observe(
  siteUrl: string,
  taskId: string,
  path: string,
  facts: Readonly<Record<string, unknown>>,
): NonNullable<FakeScript['toolCalls']> {
  return [
    { tool: 'navigate', arguments: { url: `${siteUrl}${path}` } },
    { tool: 'record_product_observation', arguments: { task_id: taskId, ...facts } },
  ];
}

/**
 * The generic-site product executor: it opens each page of `observed`,
 * records its facts with the product observation tool, writes its part,
 * and marks its task done.
 */
function productExecutor(
  siteUrl: string,
  observed: Readonly<Record<string, Readonly<Record<string, unknown>>>>,
): FakeScript {
  return {
    writeFiles: {
      'artifact/parts/product_variants.md': GENERIC_PRODUCT,
      'plan.md': GENERIC_PLAN('x', 'x'),
    },
    toolCalls: Object.entries(observed).flatMap(([path, facts]) =>
      observe(siteUrl, 'product_variants', path, facts),
    ),
    reply: 'product done',
  };
}

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

/** The Plan tasks of the bot-check plan, highest priority first. */
const BOT_CHECK_PLAN_TASKS = [
  ['homepage_sections', 'capture every section below the hero', 9],
  ['product_variants', 'open a product page; capture the variant selectors', 8],
  ['header_navigation', 'capture the department menu and its sub-levels', 7],
  ['footer', 'capture the footer link groups', 6],
] as const;

type BotCheckTaskId = (typeof BOT_CHECK_PLAN_TASKS)[number][0];

/**
 * `plan.md` with four Plan tasks. A task in `done` is `[x]`; a task in
 * `botChecked` is `[!]` with the note "bot check", as the executor writes
 * it after a bot check; every other task is pending.
 */
function botCheckPlan(
  done: readonly BotCheckTaskId[],
  botChecked: readonly BotCheckTaskId[] = [],
): string {
  const lines = BOT_CHECK_PLAN_TASKS.map(([id, brief, priority]) => {
    if (botChecked.includes(id)) {
      return `- [!] ${id} ${NOTE_PREFIX} ${brief}; bot check [priority: ${priority}]`;
    }
    return `- [${done.includes(id) ? 'x' : ' '}] ${id} ${NOTE_PREFIX} ${brief} [priority: ${priority}]`;
  });
  return `# Plan - General Marketplace

A general marketplace with department menus and product pages.

## Tasks

${lines.join('\n')}

## Omitted Areas

(none)
`;
}

/** The part of `id`, written by an executor that finished it. */
function finishedPart(id: BotCheckTaskId): Record<string, string> {
  return { [`artifact/parts/${id}.md`]: GENERIC_HOMEPAGE.replace('Homepage Sections', id) };
}

/** The tool results of one Iteration, in call order. */
async function toolResults(runDir: string, iterId: string): Promise<string[]> {
  const { steps } = await readTrajectory(join(runDir, 'iters', iterId, 'trajectory.json'));
  return steps.flatMap((step) => (step.kind === 'tool_result' ? [step.output] : []));
}

/**
 * The tool results of a run on `url` with one executor Iteration: it makes
 * `toolCalls` and marks its Plan task blocked with the note "bot check".
 */
async function blockedIterationResults(
  url: string,
  toolCalls: NonNullable<FakeScript['toolCalls']>,
): Promise<string[]> {
  const { result } = await explore({
    url,
    maxIters: 1,
    scripts: [
      { writeFiles: { 'plan.md': botCheckPlan([]) } },
      { writeFiles: { 'plan.md': botCheckPlan([], ['homepage_sections']) }, toolCalls },
    ],
  });
  return toolResults(result.runDir, 'exec-0001');
}

describe('exploreStorefront Site state graph', { timeout: 60_000 }, () => {
  it('writes the Site state graph next to the capabilities and names it in the manifest', async () => {
    const { result, llm, logs } = await explore({
      scripts: SCRIPTS,
      llm: new StubLlm(MANUAL, fencedJson(SITE_GRAPH)),
    });

    expect(result.steps.at(-1)).toMatchObject({ id: 'graph', status: 'ran' });
    expect(result.siteGraphPath).toBe(join(outDir, 'site_graph.json'));
    expect(parseSiteGraph(readJson(result.siteGraphPath))).toEqual(SITE_GRAPH);
    expect(readJson(result.manifestPath).paths.site_graph).toBe('site_graph.json');
    expect(llm.graphRequest().model).toEqual({ provider: 'anthropic', id: 'test-model' });
    expect(logs).toContain('wrote site_graph.json: pages 2, overlays 1, transitions 3');
  });

  it('gives the graph call the closed lists, the capabilities, and the outline of each finished part', async () => {
    const { llm } = await explore({ scripts: SCRIPTS });

    const prompt = promptText(llm.graphRequest().prompt);
    expect(prompt).toContain(
      '`home`, `collection`, `product`, `search`, `cart`, `page`, `policy`, `login`, `register`, `account`, `addresses`, `order_detail`, `checkout`, `checkout_confirmation`, `other`',
    );
    expect(prompt).toContain('`modal`, `side_sheet`, `popover`, `dropdown`, `flyout`');
    expect(prompt).toContain('`click`, `hover`, `type`, `submit`, `key`');
    expect(prompt).toContain(
      '`navigate`, `open_overlay`, `swap_overlay`, `close_overlay`, `update_in_place`',
    );
    expect(prompt).toContain('"type": "drawer"');
    expect(prompt).toContain(
      '<part task="homepage_sections">\n## Homepage Sections\n### Section 1 - Hero\n- **Behavior:** static\n</part>',
    );
    expect(prompt).toContain(
      '<part task="cart_drawer">\n## Cart Drawer\n### Filled state\n- **Behavior:** opens on add to cart\n</part>',
    );
    expect(prompt).not.toContain('**Type:**');
    expect(prompt).not.toContain('{{');
  });

  it('gives the graph call only the parts of the Plan tasks that plan.md marks done', async () => {
    // The cart executor writes its part but does not end its task, so the
    // harness blocks the task.
    const { result, llm } = await explore({
      scripts: [
        { writeFiles: { 'plan.md': PLAN(' ', ' ') }, reply: 'planned' },
        {
          writeFiles: {
            'artifact/parts/homepage_sections.md': CLEAN_HOMEPAGE,
            'plan.md': PLAN('x', ' '),
          },
          reply: 'homepage done',
        },
        { writeFiles: { 'artifact/parts/cart_drawer.md': CART_PART }, reply: 'cart not done' },
      ],
    });
    expect(readFileSync(join(result.runDir, 'plan.md'), 'utf8')).toMatch(/^- \[!\] cart_drawer /m);
    expect(existsSync(join(result.runDir, 'artifact', 'parts', 'cart_drawer.md'))).toBe(true);

    const prompt = promptText(llm.graphRequest().prompt);
    expect(prompt).toContain('<part task="homepage_sections">');
    expect(prompt).not.toContain('<part task="cart_drawer">');
  });

  it('adds a graph to an existing manual with from graph and no site traffic', async () => {
    await explore({ scripts: SCRIPTS });
    const manual = readFileSync(join(outDir, 'manual.md'), 'utf8');
    shopRequests.length = 0;

    const { result, runtime, llm } = await explore({
      from: 'graph',
      llm: new StubLlm(MANUAL, JSON.stringify(SITE_GRAPH)),
    });
    expect(result.steps.map((step) => [step.id, step.status])).toEqual([
      ['prefetch', 'skipped'],
      ['explore', 'skipped'],
      ['merge', 'skipped'],
      ['synthesize', 'skipped'],
      ['graph', 'ran'],
    ]);
    expect(runtime.requests).toHaveLength(0);
    expect(shopRequests).toEqual([]);
    expect(llm.requests).toEqual([llm.graphRequest()]);
    expect(readFileSync(result.manualPath, 'utf8')).toBe(manual);
    expect(parseSiteGraph(readJson(result.siteGraphPath))).toEqual(SITE_GRAPH);
  });

  it('skips a complete graph step on a later call', async () => {
    await explore({ scripts: SCRIPTS, llm: new StubLlm(MANUAL, JSON.stringify(SITE_GRAPH)) });

    const { result, llm } = await explore({});
    expect(result.steps.at(-1)).toMatchObject({ id: 'graph', status: 'skipped' });
    expect(llm.requests).toHaveLength(0);
    expect(parseSiteGraph(readJson(result.siteGraphPath))).toEqual(SITE_GRAPH);
  });

  it('writes the graph again with from merge', async () => {
    await explore({ scripts: SCRIPTS });

    const { result } = await explore({
      from: 'merge',
      llm: new StubLlm(MANUAL, JSON.stringify(SITE_GRAPH)),
    });
    expect(result.steps.map((step) => step.status)).toEqual([
      'skipped',
      'skipped',
      'ran',
      'skipped',
      'ran',
    ]);
    expect(parseSiteGraph(readJson(result.siteGraphPath))).toEqual(SITE_GRAPH);
  });

  it('fails the graph step with the leak error on a brand token and writes no graph', async () => {
    const leaky = {
      ...SITE_GRAPH,
      states: SITE_GRAPH.states.map((state) =>
        state.id === 'product' ? { ...state, url_pattern: '/fixture-picks/{handle}' } : state,
      ),
    };
    const run = explore({ scripts: SCRIPTS, llm: new StubLlm(MANUAL, JSON.stringify(leaky)) });

    await expect(run).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof StepFailedError &&
        error.stepId === 'graph' &&
        error.cause instanceof AnonymizationLeakError,
    );
    await expect(run).rejects.toThrow(/site_graph\.json:\d+ \[fixture\]: "url_pattern"/);
    expect(existsSync(join(outDir, 'site_graph.json'))).toBe(false);
  });

  /** `SITE_GRAPH` with its state at `index` changed by `edit`. */
  const withState = (index: number, edit: Record<string, unknown>) => ({
    ...SITE_GRAPH,
    states: SITE_GRAPH.states.map((state, i) => (i === index ? { ...state, ...edit } : state)),
  });
  /** `SITE_GRAPH` with its transition at `index` changed by `edit`. */
  const withTransition = (index: number, edit: Record<string, unknown>) => ({
    ...SITE_GRAPH,
    transitions: SITE_GRAPH.transitions.map((t, i) => (i === index ? { ...t, ...edit } : t)),
  });

  it.each([
    [
      'is not one JSON object',
      `Here is the graph:\n${fencedJson(SITE_GRAPH)}`,
      SiteGraphReplyError,
      /the graph reply is not one JSON object/,
    ],
    [
      'has an unknown page type',
      JSON.stringify(withState(0, { page_type: 'department' })),
      SiteGraphValidationError,
      /states\[0\]\.page_type: .* \(got "department"\)/,
    ],
    [
      'has a transition to a missing state',
      JSON.stringify(withTransition(1, { to: 'checkout' })),
      SiteGraphValidationError,
      /transitions\[1\]\.to names no state: "checkout"/,
    ],
    [
      'has a source that names no finished part',
      JSON.stringify(withTransition(0, { source: 'footer' })),
      SiteGraphValidationError,
      /transitions\[0\]\.source names no finished part: "footer"/,
    ],
  ])(
    'fails the graph step with no retry and writes no graph when the reply %s',
    async (_name, reply, type, message) => {
      const llm = new StubLlm(MANUAL, reply);
      const run = explore({ scripts: SCRIPTS, llm });

      await expect(run).rejects.toSatisfy(
        (error: unknown) =>
          error instanceof StepFailedError &&
          error.stepId === 'graph' &&
          error.cause instanceof type,
      );
      await expect(run).rejects.toThrow(message);
      llm.graphRequest();
      expect(existsSync(join(outDir, 'site_graph.json'))).toBe(false);
      expect(existsSync(join(outDir, 'manual.md'))).toBe(true);
    },
  );
});

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
      ['graph', 'ran'],
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

  it('asks the executors for product observations and shows their schema', async () => {
    const { runtime } = await explore({ url: site.url, scripts: genericScripts(site.url) });

    expect(runtime.requests[1]?.tools.map((tool) => tool.name)).toContain(
      'record_product_observation',
    );
    const executor = promptText(runtime.requests[1]?.prompt ?? '').replace(/\s+/g, ' ');
    expect(executor).toContain('call `record_product_observation` while the page is open');
    const constitution = runtime.requests[1]?.systemPrompt ?? '';
    for (const field of ['"price"', '"currency"', '"has_variants"', '"variant_axes"']) {
      expect(constitution).toContain(field);
    }
    expect(constitution).toContain('"pattern": "^[A-Z]{3}$"');
    // Axis names are generic nouns, so that no site label reaches `stats.json`.
    expect(constitution).toContain('not the label text of the page');
  });

  it('asks the executors to mark what they did not see as unknown', async () => {
    const { runtime } = await explore({ url: site.url, scripts: genericScripts(site.url) });

    const executor = promptText(runtime.requests[1]?.prompt ?? '').replace(/\s+/g, ' ');
    expect(executor).toContain(
      '`N/A` when it does not apply and `unknown` when you did not see it',
    );
    expect(executor).toContain('marks it as unknown, not as absent');
  });

  it('publishes stats from the product observation fragments', async () => {
    const { result } = await explore({
      url: site.url,
      scripts: [...genericScripts(site.url).slice(0, 2), productExecutor(site.url, OBSERVED)],
    });

    expect(result.finalStatus).toBe('completed');
    const stats = readJson(result.statsPath);
    expect(stats).toMatchObject({
      source: 'observed_sample',
      sample_size: 3,
      price: { min: 44.5, max: 79, median: 59.99, currency: 'USD' },
      variant_axes_observed: ['color', 'edition', 'platform'],
      // The site shows no catalog totals, so they stay 0.
      products_total: 0,
      collections_total: 0,
      products_per_collection: { avg: 0, median: 0, max: 0 },
      homepage_section_count: 2,
    });
    expect(stats.products_with_variants_pct).toBeCloseTo(0.667, 3);
  });

  it('counts a product page once when two tasks record it', async () => {
    const { result } = await explore({
      url: site.url,
      scripts: [
        ...genericScripts(site.url).slice(0, 1),
        {
          writeFiles: {
            'artifact/parts/homepage_sections.md': GENERIC_HOMEPAGE,
            'plan.md': GENERIC_PLAN('x', ' '),
          },
          toolCalls: observe(site.url, 'homepage_sections', '/p/fm-1001', OBSERVED['/p/fm-1001']),
          reply: 'homepage done',
        },
        productExecutor(site.url, OBSERVED),
      ],
    });

    expect(result.finalStatus).toBe('completed');
    const stats = readJson(result.statsPath);
    expect(stats.sample_size).toBe(3);
    expect(stats.products_with_variants_pct).toBeCloseTo(0.667, 3);
  });

  it('counts a product page once when two paths open it', async () => {
    const aliased = await startFixtureSite((origin) => {
      const pages = genericSitePages(origin);
      // The first product page also answers at a longer path, as on a site
      // that puts a name slug in its product URLs. The fixture has the page.
      return { ...pages, '/p/fm-1001/star-drifter': pages['/p/fm-1001'] as FixturePage };
    });
    try {
      const { result } = await explore({
        url: aliased.url,
        scripts: [
          ...genericScripts(aliased.url).slice(0, 2),
          productExecutor(aliased.url, {
            '/p/fm-1001': OBSERVED['/p/fm-1001'],
            '/p/fm-1001/star-drifter?ref=search': OBSERVED['/p/fm-1001'],
            '/p/fm-1002': OBSERVED['/p/fm-1002'],
          }),
        ],
      });

      expect(result.finalStatus).toBe('completed');
      expect(readJson(result.statsPath).sample_size).toBe(2);
    } finally {
      await aliased.close();
    }
  });

  it('takes the prices only from the fragments in the most frequent currency', async () => {
    const facts = (price: number, currency: string) => ({
      price,
      currency,
      has_variants: false,
      variant_axes: [],
    });
    const { result } = await explore({
      url: site.url,
      scripts: [
        ...genericScripts(site.url).slice(0, 2),
        productExecutor(site.url, {
          '/p/fm-1001': facts(40, 'USD'),
          '/p/fm-1002': facts(15, 'EUR'),
          '/p/fm-1003': facts(60, 'USD'),
        }),
      ],
    });

    expect(readJson(result.statsPath)).toMatchObject({
      sample_size: 3,
      price: { min: 40, max: 60, median: 50, currency: 'USD' },
    });
  });

  it('refuses a product observation that does not match the schema', async () => {
    const { result } = await explore({
      url: site.url,
      scripts: [
        ...genericScripts(site.url).slice(0, 2),
        {
          writeFiles: {
            'artifact/parts/product_variants.md': GENERIC_PRODUCT,
            'plan.md': GENERIC_PLAN('x', 'x'),
          },
          toolCalls: [
            // A lowercase currency does not match the schema.
            ...observe(site.url, 'product_variants', '/p/fm-1001', {
              ...OBSERVED['/p/fm-1001'],
              currency: 'usd',
            }),
            // A task id must be a plan task id, so it cannot name a path.
            ...observe(site.url, '../product_variants', '/p/fm-1002', OBSERVED['/p/fm-1002']),
          ],
          reply: 'product done',
        },
      ],
    });

    const trajectory = readJson(join(outDir, 'run', 'iters', 'exec-0002', 'trajectory.json'));
    const refusals = (trajectory.steps as { kind: string; output?: string; isError?: boolean }[])
      .filter((step) => step.kind === 'tool_result' && step.isError === true)
      .map((step) => step.output);
    expect(refusals).toEqual([
      expect.stringContaining('currency'),
      expect.stringContaining('invalid task id'),
    ]);
    expect(readJson(result.statsPath).sample_size).toBe(0);
  });

  it('fails the Iteration of a fragment that does not match the schema', async () => {
    // The executor edits a fragment by hand with `write_file`.
    const fragment = 'artifact/parts/product_variants.product-0123456789ab.json';
    const valid = { price: 59.99, currency: 'USD', has_variants: true, variant_axes: ['edition'] };
    const handWritten = (content: unknown): FakeScript => ({
      writeFiles: {
        'artifact/parts/product_variants.md': GENERIC_PRODUCT,
        [fragment]: JSON.stringify(content),
        'plan.md': GENERIC_PLAN('x', 'x'),
      },
      reply: 'product done',
    });
    const { result, runtime } = await explore({
      url: site.url,
      scripts: [
        ...genericScripts(site.url).slice(0, 2),
        // A product name and a lowercase currency do not match the schema.
        handWritten({ ...valid, currency: 'usd', title: 'Star Drifter' }),
        handWritten(valid),
      ],
    });

    expect(result.finalStatus).toBe('completed');
    const summary = readJson(join(outDir, 'run', 'run.json')) as RunSummary;
    expect(
      summary.verifierRuns
        .filter((run) => run.name === 'product_observations')
        .map((run) => [run.taskId, run.verdict]),
    ).toEqual([
      ['homepage_sections', 'pass'],
      ['product_variants', 'fail'],
      ['product_variants', 'pass'],
    ]);
    // The task reopens, and the next Iteration gets the feedback.
    expect(runtime.requests).toHaveLength(4);
    const retry = promptText(runtime.requests[3]?.prompt ?? '');
    expect(retry).toContain('Product observation check failed');
    expect(retry).toContain('parts/product_variants.product-0123456789ab.json');
    expect(retry).toContain('Unrecognized key: "title"');
    expect(retry).toContain('currency');
    expect(readJson(result.statsPath)).toMatchObject({ source: 'observed_sample', sample_size: 1 });
  });

  it('gives the generic planner the focus as a hint', async () => {
    const { result, runtime } = await explore({
      url: site.url,
      scripts: genericScripts(site.url),
      focus: 'Video Games',
    });

    const planner = promptText(runtime.requests[0]?.prompt ?? '');
    const prompt = readPrompt('planner_generic.md');
    expect(planner.startsWith(prompt)).toBe(true);
    const hint = planner.slice(prompt.length).replace(/\s+/g, ' ');
    expect(hint).toContain('## Focus hint');
    expect(hint).toContain('"Video Games"');
    expect(readJson(result.manifestPath).focus).toBe('Video Games');
  });

  it('adds no hint and records a null focus when the run has no focus', async () => {
    const { result, runtime } = await explore({ url: site.url, scripts: genericScripts(site.url) });

    expect(runtime.requests[0]?.prompt).toBe(readPrompt('planner_generic.md'));
    expect(readJson(result.manifestPath).focus).toBeNull();
  });

  it('records no focus when the run stops before the explore step', async () => {
    const blocked = await startFixtureSite((origin) => ({
      ...genericSitePages(origin),
      '/': { status: 503, contentType: 'text/html', body: '' },
    }));
    try {
      await expect(explore({ url: blocked.url, focus: 'Video Games' })).rejects.toThrow(
        /unreachable/,
      );
    } finally {
      await blocked.close();
    }
    // So a retry on the same outDir may take another focus.
    expect(existsSync(join(outDir, 'focus.json'))).toBe(false);
  });

  it('asks the generic planner for the 14 fixed areas within 4 navigations', async () => {
    const { runtime } = await explore({ url: site.url, scripts: genericScripts(site.url) });

    const planner = promptText(runtime.requests[0]?.prompt ?? '');
    expect(planner).toContain('explore planner for a generic site');
    expect(plannedIds(planner)).toEqual(EXPECTED_FIXED_AREAS);
    expect(planner).toContain('<= 4 `navigate` calls');
  });

  it('keeps the fixed-area briefs on storefront pages', async () => {
    const { runtime } = await explore({ url: site.url, scripts: genericScripts(site.url) });

    const planner = promptText(runtime.requests[0]?.prompt ?? '');
    expectStorefrontBriefs(planner);
    // The planner picks the listing page of collection_filters, and the
    // search results page is not one.
    expect(planner.replace(/\s+/g, ' ')).toContain(
      'a department or category landing page for `collection_filters`',
    );
  });

  it('gives the shop block to homepage_sections', async () => {
    const { runtime } = await explore({ url: site.url, scripts: genericScripts(site.url) });

    expectShopBlockOwner(promptText(runtime.requests[0]?.prompt ?? ''));
  });

  it.each([
    ['a captcha page (HTTP 200)', BOT_CHECK_PAGE],
    ['a captcha page (HTTP 503)', { ...BOT_CHECK_PAGE, status: 503 }],
    ['an interstitial page', INTERSTITIAL_PAGE],
    ['a rate-limit page', RATE_LIMIT_PAGE],
  ])('stops prefetch with bot_check when the homepage is %s', async (_, homepage) => {
    const blocked = await startFixtureSite((origin) => ({
      ...genericSitePages(origin),
      '/': homepage,
    }));
    const runtime = new FakeRuntime(genericScripts(blocked.url));
    try {
      await expect(
        exploreStorefront({
          url: blocked.url,
          outDir,
          model: 'anthropic/test-model',
          rateLimitMs: 0,
          credentials: CREDENTIALS,
          runtime,
          llm: new StubLlm(),
        }),
      ).rejects.toSatisfy(
        (error: unknown) =>
          error instanceof StepFailedError &&
          error.cause instanceof ShopUnreachableError &&
          error.cause.reason === 'bot_check',
      );
    } finally {
      await blocked.close();
    }
    expect(runtime.requests).toHaveLength(0);
    expect(existsSync(join(outDir, 'run'))).toBe(false);
  });

  it('blocks a Plan task that meets a bot check and goes on with the run', async () => {
    const botCheck = { tool: 'navigate', arguments: { url: `${site.url}/bot-check` } };
    const product = { tool: 'navigate', arguments: { url: `${site.url}/p/fm-1001` } };
    // Bot checks in exec-0001 and exec-0003 are not in a row, so the run does not stop.
    const { result, runtime } = await explore({
      url: site.url,
      scripts: [
        { writeFiles: { 'plan.md': botCheckPlan([]) } },
        {
          writeFiles: { 'plan.md': botCheckPlan([], ['homepage_sections']) },
          toolCalls: [botCheck],
        },
        {
          writeFiles: {
            ...finishedPart('product_variants'),
            'plan.md': botCheckPlan(['product_variants'], ['homepage_sections']),
          },
          toolCalls: [product],
        },
        {
          writeFiles: {
            'plan.md': botCheckPlan(
              ['product_variants'],
              ['homepage_sections', 'header_navigation'],
            ),
          },
          toolCalls: [botCheck],
        },
        {
          writeFiles: {
            ...finishedPart('footer'),
            'plan.md': botCheckPlan(
              ['product_variants', 'footer'],
              ['homepage_sections', 'header_navigation'],
            ),
          },
          toolCalls: [product],
        },
      ],
    });

    expect(result.finalStatus).toBe('completed');
    expect(runtime.requests).toHaveLength(5);
    const [notice] = await toolResults(result.runDir, 'exec-0001');
    expect(notice).toContain('this page is a bot check');
    expect(notice).toContain('Do not try to pass it');
    expect(notice).toContain('`[!]`');
    expect(notice).toContain('"bot check"');
    expect(await toolResults(result.runDir, 'exec-0002')).not.toEqual(
      expect.arrayContaining([expect.stringContaining('bot check')]),
    );
    const manifest = readJson(result.manifestPath);
    expect(manifest).toMatchObject({
      harness_status: 'completed',
      plan_tasks_done: 2,
      plan_tasks_blocked: 2,
      stop: null,
    });
  });

  it('stops the run after two Iterations in a row with a bot check and still publishes the manual', async () => {
    const botCheck = { tool: 'navigate', arguments: { url: `${site.url}/bot-check` } };
    const { result, runtime } = await explore({
      url: site.url,
      scripts: [
        { writeFiles: { 'plan.md': botCheckPlan([]) } },
        {
          writeFiles: {
            ...finishedPart('homepage_sections'),
            'plan.md': botCheckPlan(['homepage_sections']),
          },
          toolCalls: [{ tool: 'snapshot', arguments: {} }],
        },
        {
          writeFiles: { 'plan.md': botCheckPlan(['homepage_sections'], ['product_variants']) },
          toolCalls: [botCheck],
        },
        {
          writeFiles: {
            'plan.md': botCheckPlan(
              ['homepage_sections'],
              ['product_variants', 'header_navigation'],
            ),
          },
          toolCalls: [botCheck],
        },
        { writeFiles: { ...finishedPart('footer') }, reply: 'never runs' },
      ],
    });

    expect(runtime.requests).toHaveLength(4);
    expect(result.finalStatus).toBe('stopped');
    expect(result.stop).toEqual({ reason: 'bot_check', iteration: 'exec-0003' });
    expect(readJson(join(result.runDir, 'run.json'))).toMatchObject({
      finalStatus: 'stopped',
      stopReason: 'bot_check',
    });
    expect(readFileSync(result.manualPath, 'utf8')).toBe(MANUAL);
    const manifest = readJson(result.manifestPath);
    expect(manifest).toMatchObject({
      harness_status: 'stopped',
      plan_tasks_done: 1,
      plan_tasks_blocked: 2,
      coverage_gaps: ['footer', 'header_navigation'],
      stop: {
        reason: 'bot_check',
        iteration: 'exec-0003',
        blocked_tasks: ['product_variants', 'header_navigation'],
      },
    });
  });

  it('finds a bot check after a browser action other than navigate', async () => {
    const [, product, back] = await blockedIterationResults(site.url, [
      { tool: 'navigate', arguments: { url: `${site.url}/bot-check` } },
      { tool: 'navigate', arguments: { url: `${site.url}/p/fm-1001` } },
      { tool: 'back', arguments: {} },
    ]);
    expect(product).not.toContain('bot check');
    expect(back).toContain('Went back');
    expect(back).toContain('this page is a bot check');
  });

  it.each([
    ['a Shopify shop', () => ({ url: baseUrl, scripts: SCRIPTS })],
    ['a generic site', () => ({ url: site.url, scripts: genericScripts(site.url) })],
  ])(
    'tells the planner and the executor on %s never to act on a bot-check page',
    async (_, options) => {
      const { runtime } = await explore(options());

      const [planner, executor] = runtime.requests.map((request) =>
        promptText(request.prompt).replace(/\s+/g, ' '),
      );
      const rule = 'Never click, type or submit on an interstitial or bot-check page';
      expect(planner).toContain(rule);
      expect(planner).toContain('plan only from the pages that you could read');
      expect(executor).toContain(rule);
      expect(executor).toContain('Mark your task `[!]` with the reason "bot check"');
    },
  );

  it('refuses page actions on a bot-check page and allows them again after back', async () => {
    const [, , press, click, type, select, back, pressAfterBack] = await blockedIterationResults(
      site.url,
      [
        { tool: 'navigate', arguments: { url: `${site.url}/p/fm-1001` } },
        { tool: 'navigate', arguments: { url: `${site.url}/bot-check` } },
        { tool: 'press', arguments: { key: 'Enter' } },
        { tool: 'click', arguments: { ref: 'e1' } },
        { tool: 'type', arguments: { ref: 'e1', text: 'abc', submit: true } },
        { tool: 'select', arguments: { ref: 'e1', value: 'abc' } },
        { tool: 'back', arguments: {} },
        { tool: 'press', arguments: { key: 'Tab' } },
      ],
    );
    for (const [tool, output] of [
      ['press', press],
      ['click', click],
      ['type', type],
      ['select', select],
    ]) {
      expect(output).toContain(`${tool} refused`);
      expect(output).toContain('this page is a bot check');
    }
    // The focused captcha input would send the form on Enter.
    expect(site.requests.some((request) => request.path.startsWith('/errors/'))).toBe(false);
    expect(back).toContain('Went back');
    expect(back).not.toContain('bot check');
    expect(pressAfterBack).toContain('Pressed Tab');
  });

  it.each([
    ['an interstitial page', '/interstitial'],
    ['a rate-limit page served with HTTP 503', '/rate-limit'],
  ])('finds a bot check on %s', async (_, path) => {
    const [navigate] = await blockedIterationResults(site.url, [
      { tool: 'navigate', arguments: { url: `${site.url}${path}` } },
    ]);
    expect(navigate).toContain('this page is a bot check');
  });

  it('does not take a normal error page for a rate-limit page', async () => {
    const errors = await startFixtureSite((origin) => ({
      ...genericSitePages(origin),
      '/server-error': { ...RATE_LIMIT_PAGE, status: 500 },
      '/unavailable': {
        status: 503,
        contentType: 'text/html',
        body: '<!doctype html><html><head><title>Back soon</title></head><body>Down for maintenance.</body></html>',
      },
    }));
    try {
      const [serverError, unavailable] = await blockedIterationResults(errors.url, [
        { tool: 'navigate', arguments: { url: `${errors.url}/server-error` } },
        { tool: 'navigate', arguments: { url: `${errors.url}/unavailable` } },
      ]);
      expect(serverError).toContain('Title: Sorry! Something went wrong!');
      expect(serverError).not.toContain('bot check');
      expect(unavailable).toContain('Title: Back soon');
      expect(unavailable).not.toContain('bot check');
    } finally {
      await errors.close();
    }
  });

  it('refuses navigate at the navigation cap and stops the run', async () => {
    const search = { tool: 'navigate', arguments: { url: `${site.url}/search?q=cap` } };
    const { result, runtime } = await explore({
      url: site.url,
      scripts: [
        { writeFiles: { 'plan.md': botCheckPlan([]) } },
        {
          writeFiles: {
            ...finishedPart('homepage_sections'),
            'plan.md': botCheckPlan(['homepage_sections']),
          },
          toolCalls: Array.from({ length: NAVIGATION_CAP + 1 }, () => search),
        },
        { writeFiles: { ...finishedPart('footer') }, reply: 'never runs' },
      ],
    });

    const results = await toolResults(result.runDir, 'exec-0001');
    expect(results).toHaveLength(NAVIGATION_CAP + 1);
    expect(results.at(-2)).toContain('Navigated to');
    expect(results.at(-1)).toContain(
      `navigate refused: this run has made its cap of ${NAVIGATION_CAP}`,
    );
    expect(site.requests.filter((request) => request.path === '/search?q=cap')).toHaveLength(
      NAVIGATION_CAP,
    );
    expect(runtime.requests).toHaveLength(2);
    expect(result.finalStatus).toBe('stopped');
    expect(result.stop).toEqual({ reason: 'navigation_cap', iteration: 'exec-0001' });
    expect(readJson(result.manifestPath)).toMatchObject({
      harness_status: 'stopped',
      plan_tasks_done: 1,
      stop: { reason: 'navigation_cap', iteration: 'exec-0001', blocked_tasks: [] },
    });
  });
});

/** Invented sub-brands of the generic site, as `--brand-term` gives them. */
const BRAND_TERMS = ['Nova Pass', 'Zephyr'] as const;

/** A homepage fragment with the words of the title's tagline in plain prose. */
const TAGLINE_HOMEPAGE = `${GENERIC_HOMEPAGE}
The hero headline asks the shopper to spend less and shop more.
`;

/** Planner, then one executor per Plan task; `product` is the product fragment(s) in order. */
function brandScripts(
  product: readonly string[],
  homepageCaps: object = { homepage: { section_count: 2 } },
): readonly FakeScript[] {
  return [
    { writeFiles: { 'plan.md': GENERIC_PLAN(' ', ' ') }, reply: 'planned' },
    {
      writeFiles: {
        'artifact/parts/homepage_sections.md': TAGLINE_HOMEPAGE,
        'artifact/parts/homepage_sections.caps.json': JSON.stringify(homepageCaps),
        'plan.md': GENERIC_PLAN('x', ' '),
      },
      reply: 'homepage done',
    },
    ...product.map((fragment) => ({
      writeFiles: {
        'artifact/parts/product_variants.md': fragment,
        'plan.md': GENERIC_PLAN('x', 'x'),
      },
      reply: 'product done',
    })),
  ];
}

describe('exploreStorefront anonymization with brand terms', { timeout: 60_000 }, () => {
  let site: FixtureSite;

  beforeEach(async () => {
    site = await startFixtureSite(genericSitePages, GENERIC_SITE_HOSTNAME);
  });

  afterEach(async () => {
    await site.close();
  });

  it('fails a brand term but not a tagline word, and publishes no brand term', async () => {
    const { result, runtime } = await explore({
      url: site.url,
      brandTerms: BRAND_TERMS,
      scripts: brandScripts([
        `${GENERIC_PRODUCT}\nMembers of Nova Pass see a free delivery badge.\n`,
        `${GENERIC_PRODUCT}\nMembers see a free delivery badge; a season pass and a nova-blue label sit next to the price.\n`,
      ]),
    });
    expect(result.finalStatus).toBe('completed');

    // The tagline words pass; the phrase "Nova Pass" reopens the product
    // task, and its words alone pass.
    const summary = readJson(join(outDir, 'run', 'run.json')) as RunSummary;
    expect(
      summary.verifierRuns
        .filter((run) => run.name === 'anonymization')
        .map((run) => [run.taskId, run.verdict]),
    ).toEqual([
      ['homepage_sections', 'pass'],
      ['product_variants', 'fail'],
      ['product_variants', 'pass'],
    ]);
    const retry = promptText(runtime.requests[3]?.prompt ?? '');
    expect(retry).toContain('Anonymization check failed');
    expect(retry).toContain('[nova pass]: Members of Nova Pass see a free delivery badge.');

    // The terms stay in the run directory, and no published file holds one.
    expect(readJson(join(outDir, 'brand_terms.json'))).toEqual(BRAND_TERMS);
    for (const path of [
      result.manualPath,
      result.capabilitiesPath,
      result.statsPath,
      result.manifestPath,
    ]) {
      const text = readFileSync(path, 'utf8').toLowerCase();
      for (const term of BRAND_TERMS) expect(text, path).not.toContain(term.toLowerCase());
    }
  });

  it('fails the final scan on a leak in a published file and publishes no manual', async () => {
    const leakyManual = `${MANUAL}
Members of Nova Pass get free delivery.
Returns go through ${GENERIC_SITE_HOSTNAME}/help.
`;
    const run = explore({
      url: site.url,
      brandTerms: BRAND_TERMS,
      scripts: brandScripts([GENERIC_PRODUCT], {
        shop: { descriptor: 'Fixture Mart general marketplace' },
      }),
      llm: new StubLlm(leakyManual),
    });

    await expect(run).rejects.toSatisfy(
      (error: unknown) => error instanceof StepFailedError && error.stepId === 'synthesize',
    );
    await expect(run).rejects.toThrow(/manual\.md:\d+ \[nova pass\]/);
    await expect(run).rejects.toThrow(/manual\.md:\d+ \[fixturemart\.localhost\]/);
    await expect(run).rejects.toThrow(/capabilities\.json:\d+ \[fixture\]/);
    expect(existsSync(join(outDir, 'manual.md'))).toBe(false);
  });

  it('keeps the stored brand terms on a later call and scans again when they change', async () => {
    await explore({
      url: site.url,
      brandTerms: ['Zephyr'],
      scripts: brandScripts([GENERIC_PRODUCT]),
    });

    const again = await explore({ url: site.url });
    expect(again.result.steps.every((step) => step.status === 'skipped')).toBe(true);
    expect(readJson(join(outDir, 'brand_terms.json'))).toEqual(['Zephyr']);

    // MANUAL names "Minimal Homeware", which is now a brand term.
    await expect(
      explore({ url: site.url, brandTerms: ['Zephyr', 'Minimal Homeware'] }),
    ).rejects.toThrow(/manual\.md:1 \[minimal homeware\]/);
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
