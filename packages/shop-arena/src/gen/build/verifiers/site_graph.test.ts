/**
 * `site_graph` against the gen stub storefront, which serves the built
 * routes of the template. The graphs use made-up source URL patterns, so
 * a pass shows that the Verifier walks the built routes and not the
 * source ones. A stub route that answers 500, or a relabel that drops a
 * link, stands in for a transition that a task broke.
 */

import * as fs from 'node:fs/promises';
import type * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';

import { type SiteGraph, type SiteGraphState, parseSiteGraph } from '@shop-gym/core';
import type { VerifierContext, VerifierResult } from '@shop-gym/harness';
import { afterEach, describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../../../templates.js';
import { type StubStorefrontOptions, stubStorefront } from '../../testing.js';
import { defaultBackendTemplateDir } from '../seed.js';
import { BackendSidecar } from '../sidecar.js';
import { StorefrontSidecar } from '../storefront_sidecar.js';
import { buildVerifiers } from './index.js';
import { OwnedFilesVerifier } from './owned_files.js';
import {
  PAGE_TYPE_RULES,
  type TransitionCheck,
  readSiteGraph,
  siteGraphVerifier,
} from './site_graph.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');

let server: http.Server | undefined;
const tempDirs: string[] = [];

afterEach(async () => {
  await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
  server = undefined;
  await Promise.all(tempDirs.splice(0).map((dir) => fs.rm(dir, { recursive: true, force: true })));
});

async function serve(options?: StubStorefrontOptions): Promise<string> {
  server = stubStorefront(options);
  await new Promise<void>((resolve) => server?.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('no port');
  return `http://127.0.0.1:${address.port}`;
}

async function tempDir(): Promise<string> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'site-graph-'));
  tempDirs.push(dir);
  return dir;
}

async function ctx(selectedTaskId: string): Promise<VerifierContext> {
  const runDir = await tempDir();
  return { runDir, iterId: 'exec-0001', selectedTaskId, plan: [], artifactDir: runDir };
}

/** The states of a source shop, with URL patterns that the built shop does not use. */
const STATES: Readonly<Record<string, SiteGraphState>> = {
  home: { id: 'home', kind: 'page', page_type: 'home', url_pattern: '/' },
  department: {
    id: 'department',
    kind: 'page',
    page_type: 'collection',
    url_pattern: '/aisle/{node}',
  },
  item: { id: 'item', kind: 'page', page_type: 'product', url_pattern: '/item/{item_id}' },
  results: { id: 'results', kind: 'page', page_type: 'search', url_pattern: '/find?term={query}' },
  basket: { id: 'basket', kind: 'page', page_type: 'cart', url_pattern: '/basket' },
  sign_in: { id: 'sign_in', kind: 'page', page_type: 'login', url_pattern: '/signin' },
  legal: { id: 'legal', kind: 'page', page_type: 'policy', url_pattern: '/legal/{slug}' },
  help: { id: 'help', kind: 'page', page_type: 'other', url_pattern: '/help-center' },
  reviews: { id: 'reviews', kind: 'page', page_type: 'page', url_pattern: '/reviews/{item_id}' },
  pay: { id: 'pay', kind: 'page', page_type: 'checkout', url_pattern: '/buy/{session}' },
  cookie_notice: { id: 'cookie_notice', kind: 'overlay', overlay: 'modal', on: ['home'] },
};

type Edge = readonly [from: string, to: string, action: string];

/** A valid graph of `edges` over `STATES`: click and navigate unless `effects` says otherwise. */
function graphOf(
  edges: readonly Edge[],
  effects: Readonly<Record<string, Partial<SiteGraph['transitions'][number]>>> = {},
): SiteGraph {
  const ids = new Set([...edges.map(([from]) => from), ...edges.map(([, to]) => to)]);
  return parseSiteGraph({
    version: '0.1',
    states: Object.values(STATES).filter((state) => ids.has(state.id)),
    transitions: edges.map(([from, to, action]) => ({
      from,
      to,
      trigger: 'click',
      action,
      effect: 'navigate',
      source: 'site_shell',
      ...effects[action],
    })),
  });
}

/** `[from -> to (action), status, target or reason]` for each listed transition. */
function checks(result: VerifierResult): [string, string, string][] {
  const { transitions } = result.details as { transitions: TransitionCheck[] };
  return transitions.map((check) => [
    `${check.from} -> ${check.to} (${check.action})`,
    check.status,
    check.status === 'pass' ? `${check.url} => ${check.target}` : (check.reason ?? ''),
  ]);
}

/** A graph whose walkable transitions all work on the stub, plus one of each advisory kind. */
const WORKING = graphOf(
  [
    ['home', 'department', 'open_department'],
    ['home', 'sign_in', 'open_sign_in'],
    ['home', 'legal', 'open_policy'],
    ['item', 'basket', 'add_to_cart'],
    ['department', 'home', 'go_home'],
    ['home', 'home', 'open_home'],
    ['home', 'cookie_notice', 'show_cookie_notice'],
    ['department', 'department', 'sort_results'],
    ['home', 'help', 'open_help'],
    ['basket', 'home', 'continue_shopping'],
    ['item', 'pay', 'buy_now'],
    ['reviews', 'item', 'open_reviewed_item'],
  ],
  {
    add_to_cart: { trigger: 'submit', needs: ['variant'] },
    show_cookie_notice: { trigger: 'load', effect: 'open_overlay' },
    sort_results: { trigger: 'type', effect: 'update_in_place' },
    buy_now: { trigger: 'submit' },
  },
);

describe('site_graph', () => {
  it('walks the built routes, not the source URL patterns, and passes when every checked transition works', async () => {
    const verifier = siteGraphVerifier({
      target: { url: await serve() },
      dataDir: FIXTURE_DIR,
      graph: WORKING,
    });

    const result = await verifier.run(await ctx('visual_fix'));

    expect(result.verdict).toBe('pass');
    expect(checks(result)).toEqual([
      ['home -> department (open_department)', 'pass', '/ => /collections/dog-essentials'],
      ['home -> sign_in (open_sign_in)', 'pass', '/ => /account/login'],
      ['home -> legal (open_policy)', 'pass', '/ => /policies/privacy-policy'],
      ['item -> basket (add_to_cart)', 'pass', '/products/shopliseum-mushroom-dog-toys => /cart'],
      ['department -> home (go_home)', 'pass', '/collections/dog-essentials => /'],
      ['home -> home (open_home)', 'pass', '/ => /'],
      [
        'home -> cookie_notice (show_cookie_notice)',
        'advisory',
        expect.stringContaining('overlay'),
      ],
      [
        'department -> department (sort_results)',
        'advisory',
        expect.stringContaining('update_in_place'),
      ],
      ['home -> help (open_help)', 'advisory', expect.stringContaining('`other` page')],
      ['basket -> home (continue_shopping)', 'advisory', expect.stringContaining('`cart` page')],
      ['item -> pay (buy_now)', 'advisory', expect.stringContaining('`checkout` page')],
      ['reviews -> item (open_reviewed_item)', 'advisory', expect.stringContaining('`page` page')],
    ]);
  });

  it('fails and names the transition when no control leads to the built route', async () => {
    const graph = graphOf(
      [
        ['home', 'department', 'open_department'],
        ['home', 'results', 'search'],
      ],
      { search: { trigger: 'submit', params: ['query'] } },
    );
    const verifier = siteGraphVerifier({
      target: { url: await serve() },
      dataDir: FIXTURE_DIR,
      graph,
    });

    const result = await verifier.run(await ctx('gen_homepage'));

    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain(
      '- `home` -> `results` (`search`): no link or form on `/` leads to a search page (`/search`).',
    );
    expect(result.feedback).not.toContain('`open_department`');
  });

  it('fails when a link goes to the source URL pattern and not to the built route', async () => {
    const url = await serve({ relabel: { 'href="/account/login"': 'href="/signin"' } });
    const graph = graphOf([['home', 'sign_in', 'open_sign_in']]);

    const result = await siteGraphVerifier({ target: { url }, dataDir: FIXTURE_DIR, graph }).run(
      await ctx('gen_homepage'),
    );

    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain(
      '- `home` -> `sign_in` (`open_sign_in`): no link or form on `/` leads to a login page (`/account/login`).',
    );
  });

  it('does not count a control back to the same page of a type with many pages', async () => {
    const product = '/products/shopliseum-mushroom-dog-toys';
    const url = await serve({ relabel: { 'action="/cart"': `action="${product}"` } });
    const graph = graphOf([['item', 'item', 'open_related_item']]);

    const result = await siteGraphVerifier({ target: { url }, dataDir: FIXTURE_DIR, graph }).run(
      await ctx('gen_product'),
    );

    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain(
      `no link or form on \`${product}\` leads to a product page (\`/products/{product}\`).`,
    );
  });

  it('fails and names the transition when its target page answers an error', async () => {
    const url = await serve({ broken: ['/collections'] });
    const graph = graphOf([['home', 'department', 'open_department']]);

    const result = await siteGraphVerifier({ target: { url }, dataDir: FIXTURE_DIR, graph }).run(
      await ctx('gen_homepage'),
    );

    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain(
      '- `home` -> `department` (`open_department`): `/collections/dog-essentials`, linked from `/`, returned 500.',
    );
  });

  it('fails and names the transition when its first page answers an error', async () => {
    const url = await serve({ broken: ['/products'] });
    const graph = graphOf([['item', 'basket', 'add_to_cart']], {
      add_to_cart: { trigger: 'submit' },
    });

    const result = await siteGraphVerifier({ target: { url }, dataDir: FIXTURE_DIR, graph }).run(
      await ctx('gen_product'),
    );

    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain(
      '- `item` -> `basket` (`add_to_cart`): `/products/shopliseum-mushroom-dog-toys` returned 500.',
    );
  });

  it('applies to the task that builds the first page of a checked transition, and to visual_fix', () => {
    const verifier = siteGraphVerifier({
      target: { url: 'http://127.0.0.1:1' },
      dataDir: FIXTURE_DIR,
      graph: WORKING,
    });
    const tasks = [
      'gen_homepage',
      'gen_collections',
      'gen_product',
      'visual_fix',
      'gen_navigation',
      'gen_cart_search',
      'gen_checkout',
      'gen_backend',
    ];
    expect(tasks.filter(verifier.appliesTo)).toEqual([
      'gen_homepage',
      'gen_collections',
      'gen_product',
      'visual_fix',
    ]);
  });

  it('walks only the transitions of the selected task and lists every advisory one', async () => {
    const graph = graphOf(
      [
        ['home', 'results', 'search'],
        ['item', 'basket', 'add_to_cart'],
        ['home', 'help', 'open_help'],
      ],
      { search: { trigger: 'submit' }, add_to_cart: { trigger: 'submit' } },
    );
    const verifier = siteGraphVerifier({
      target: { url: await serve() },
      dataDir: FIXTURE_DIR,
      graph,
    });

    const result = await verifier.run(await ctx('gen_product'));

    expect(result.verdict).toBe('pass');
    expect(checks(result).map(([edge, status]) => [edge, status])).toEqual([
      ['item -> basket (add_to_cart)', 'pass'],
      ['home -> help (open_help)', 'advisory'],
    ]);
  });
});

describe('PAGE_TYPE_RULES', () => {
  it('names which page types are walked, which only as a target, and which are advisory', () => {
    const kinds = (kind: string) =>
      Object.entries(PAGE_TYPE_RULES)
        .filter(([, rule]) => rule.kind === kind)
        .map(([type]) => type);
    expect(kinds('checked')).toEqual([
      'home',
      'collection',
      'product',
      'search',
      'policy',
      'login',
      'register',
    ]);
    expect(kinds('target_only')).toEqual(['cart', 'page']);
    expect(kinds('advisory')).toEqual([
      'account',
      'addresses',
      'order_detail',
      'checkout',
      'checkout_confirmation',
      'other',
    ]);
  });

  it('gives each walked page type a route of the storefront template', async () => {
    const routesTs = await fs.readFile(
      path.join(STOREFRONT_TEMPLATE_DIR, 'app', 'routes.ts'),
      'utf-8',
    );
    const templateRoutes = new Set([
      '/',
      ...[...routesTs.matchAll(/route\('([^']+)'/g)].map(
        ([, route]) => `/${(route ?? '').replace(/:[a-zA-Z]+/g, '{}')}`,
      ),
    ]);
    for (const rule of Object.values(PAGE_TYPE_RULES)) {
      if (rule.kind === 'advisory') continue;
      const route = rule.route.replace(/\?.*$/, '').replace(/\{[a-z_]+\}/g, '{}');
      expect(templateRoutes).toContain(route);
    }
  });
});

describe('readSiteGraph', () => {
  it('reads the graph of a manual, and gives undefined for a manual with none', async () => {
    const manualDir = await tempDir();
    expect(await readSiteGraph(manualDir)).toBeUndefined();
    await fs.writeFile(path.join(manualDir, 'site_graph.json'), JSON.stringify(WORKING));
    expect(await readSiteGraph(manualDir)).toEqual(WORKING);
  });
});

describe('buildVerifiers with a Site state graph', () => {
  it('adds site_graph after discount_flow only when the manual has a graph', () => {
    const sidecar = new BackendSidecar({
      backendDir: '/b',
      dataDir: '/d',
      port: 1,
      logPath: '/tmp/x.log',
      launch: async () => ({ stop: async () => {} }),
    });
    const storefront = new StorefrontSidecar({
      storefrontDir: '/s',
      backendUrl: sidecar.url,
      port: 2,
      logPath: '/tmp/y.log',
      launch: async () => ({ stop: async () => {} }),
    });
    const ownedFiles = new OwnedFilesVerifier(
      { changedPaths: async () => [] },
      { genBackend: false },
    );
    const names = (siteGraph?: SiteGraph) =>
      buildVerifiers({
        genBackend: false,
        sidecar,
        ownedFiles,
        storefront: {
          sidecar: storefront,
          dataDir: '/d',
          ...(siteGraph !== undefined ? { siteGraph } : {}),
        },
      })
        .map((verifier) => verifier.name)
        .slice(-3);
    expect(names(WORKING)).toEqual(['discount_flow', 'site_graph', 'page_lint']);
    expect(names()).toEqual(['account_flow', 'discount_flow', 'page_lint']);
  });
});
