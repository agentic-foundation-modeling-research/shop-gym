/**
 * Storefront verifiers against a tiny `node:http` storefront stub that
 * mimics the template's routes, redirects and cart forms well enough for
 * `routes_200`, `nav_coverage` and the failure paths of
 * `cart_conformance`. The real template is exercised by the slow test.
 */

import * as fs from 'node:fs/promises';
import * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';

import type { VerifierContext } from '@shop-gym/harness';
import { afterEach, describe, expect, it } from 'vitest';

import { defaultBackendTemplateDir } from '../seed.js';
import { BackendSidecar } from '../sidecar.js';
import { StorefrontSidecar } from '../storefront_sidecar.js';
import { cartConformanceVerifier } from './cart_conformance.js';
import { buildVerifiers } from './index.js';
import { navCoverageVerifier } from './nav_coverage.js';
import { OwnedFilesVerifier } from './owned_files.js';
import { internalLinks, routes200Verifier } from './routes_200.js';
import { storefrontBuildVerifier, storefrontTypecheckVerifier } from './storefront_commands.js';
import type { CommandResult, CommandRunner } from './subprocess.js';
import { bucketRoutes, bucketsForTask, readDatasetHandles } from './task_routes.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
const OK: CommandResult = { exitCode: 0, stdout: '', stderr: '', timedOut: false };

interface StubOptions {
  /** Route prefixes answered with 500 instead of their normal response. */
  readonly broken?: readonly string[];
  /** Drop the footer link to this URL. */
  readonly unlinked?: string;
}

const MENU = ['/collections/dog-essentials', '/collections/cat-care'];
const FOOTER = ['/pages/about-us', '/policies/privacy-policy'];

/** Session-less stub: cookies `session=1` (logged in) and `cart=1` (non-empty cart). */
function stubStorefront(options: StubOptions = {}): http.Server {
  return http.createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    const cookies = req.headers.cookie ?? '';
    const page = (body: string, status = 200): void => {
      res.writeHead(status, { 'content-type': 'text/html' });
      res.end(
        `<html><body><header class="site-header"><nav>${MENU.map((u) => `<a href="${u}">${u}</a>`).join('')}</nav></header><main>${body}</main><footer class="site-footer">${FOOTER.filter(
          (u) => u !== options.unlinked,
        )
          .map((u) => `<a href="${u}">${u}</a>`)
          .join('')}</footer></body></html>`,
      );
    };
    const redirect = (location: string, cookie?: string): void => {
      res.writeHead(302, { location, ...(cookie ? { 'set-cookie': cookie } : {}) });
      res.end();
    };
    if (options.broken?.some((prefix) => url.pathname.startsWith(prefix))) {
      res.writeHead(500, { 'content-type': 'text/html' });
      res.end('<html><body><pre>TypeError: cannot read products of undefined</pre></body></html>');
      return;
    }
    if (req.method === 'POST') {
      let raw = '';
      req.on('data', (chunk) => {
        raw += chunk;
      });
      req.on('end', () => {
        const form = new URLSearchParams(raw);
        if (url.pathname === '/account/login') {
          redirect('/account', 'session=1; Path=/');
        } else if (url.pathname === '/cart' && form.get('intent') === 'add') {
          redirect(form.get('redirectTo') ?? '/cart', 'cart=1; Path=/');
        } else {
          redirect('/');
        }
      });
      return;
    }
    if (
      url.pathname.startsWith('/account') &&
      url.pathname !== '/account/login' &&
      url.pathname !== '/account/register'
    ) {
      if (!cookies.includes('session=1')) {
        redirect(`/account/login?redirectTo=${encodeURIComponent(url.pathname)}`);
        return;
      }
      page('<h1>Account</h1>');
      return;
    }
    if (url.pathname === '/checkout') {
      if (!cookies.includes('cart=1')) {
        redirect('/cart');
        return;
      }
      page('<h1>Checkout</h1>');
      return;
    }
    if (url.pathname.startsWith('/products/')) {
      page(
        '<form class="product-form" method="post" action="/cart"><input type="hidden" name="intent" value="add"><input type="radio" name="merchandiseId" value="gid://shopify/ProductVariant/1" checked><button>Add to cart</button></form>',
      );
      return;
    }
    page(`<h1>${url.pathname}</h1><a href="/collections">All</a>`);
  });
}

let server: http.Server | undefined;
let runDir: string;

async function serve(options?: StubOptions): Promise<string> {
  server = stubStorefront(options);
  await new Promise<void>((resolve) => server?.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('no port');
  return `http://127.0.0.1:${address.port}`;
}

afterEach(async () => {
  await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
  server = undefined;
});

async function ctx(selectedTaskId: string): Promise<VerifierContext> {
  runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'storefront-verifiers-'));
  const artifactDir = path.join(runDir, 'artifact');
  await fs.mkdir(path.join(artifactDir, 'storefront'), { recursive: true });
  return { runDir, iterId: 'exec-0001', selectedTaskId, plan: [], artifactDir };
}

describe('storefront command verifiers', () => {
  it('run for storefront tasks only; typecheck runs in the storefront copy', async () => {
    const calls: { argv: string[]; cwd: string }[] = [];
    const runner: CommandRunner = async (argv, options) => {
      calls.push({ argv: [...argv], cwd: options.cwd });
      return OK;
    };
    let builds = 0;
    const typecheck = storefrontTypecheckVerifier(runner);
    const build = storefrontBuildVerifier({
      build: async () => {
        builds += 1;
        return OK;
      },
    });
    expect(typecheck.appliesTo('gen_homepage')).toBe(true);
    expect(typecheck.appliesTo('gen_backend')).toBe(false);
    expect(build.appliesTo('visual_fix')).toBe(true);
    expect(build.appliesTo('gen_backend')).toBe(false);
    const context = await ctx('gen_homepage');
    expect((await typecheck.run(context)).verdict).toBe('pass');
    expect((await build.run(context)).verdict).toBe('pass');
    expect(calls).toEqual([
      { argv: ['pnpm', 'typecheck'], cwd: path.join(context.artifactDir, 'storefront') },
    ]);
    expect(builds).toBe(1);
  });

  it('fails with the command output when the build exits non-zero', async () => {
    const build = storefrontBuildVerifier({
      build: async () => ({
        exitCode: 1,
        stdout: '',
        stderr: 'app/root.tsx: Unexpected token',
        timedOut: false,
      }),
    });
    const result = await build.run(await ctx('gen_homepage'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('Unexpected token');
  });
});

describe('task routes', () => {
  it('derives per-bucket routes from the dataset handles', async () => {
    const handles = await readDatasetHandles(FIXTURE_DIR);
    expect(bucketsForTask('gen_product')).toEqual(['product']);
    expect(bucketsForTask('gen_backend')).toEqual([]);
    const caps = { maxCollections: 1, productsPerCollection: 1, maxPages: 1 };
    expect(bucketRoutes('collections', handles, caps)).toEqual([
      '/collections',
      '/collections/dog-essentials',
    ]);
    expect(bucketRoutes('product', handles, caps)).toHaveLength(1);
    expect(bucketRoutes('info_pages', handles, caps)).toEqual([
      '/pages/about-us',
      '/policies/privacy-policy',
    ]);
    expect(bucketRoutes('account', handles, caps)).toEqual(['/account/login', '/account']);
    expect(bucketRoutes('checkout', handles, caps)).toEqual(['/checkout']);
    expect(bucketsForTask('gen_account')).toEqual(['account']);
    expect(bucketsForTask('gen_checkout')).toEqual(['checkout']);
    expect(bucketsForTask('visual_fix')).toEqual(expect.arrayContaining(['account', 'checkout']));
  });

  it('collects same-origin links from rendered bodies', () => {
    expect(
      internalLinks(['<a href="/a">x</a><a href="https://example.com/b">y</a><a href="/a">z</a>']),
    ).toEqual(['/a']);
  });
});

describe('routes_200', () => {
  it('passes when every route answers as expected, including the logged-in account pages', async () => {
    const url = await serve();
    const verifier = routes200Verifier({ target: { url }, dataDir: FIXTURE_DIR });
    const result = await verifier.run(await ctx('gen_product'));
    expect(result.verdict).toBe('pass');
    const probes = (result.details as { probes: { route: string; ok: boolean }[] }).probes;
    expect(probes.every((p) => p.ok)).toBe(true);
    expect(probes.map((p) => p.route)).toEqual(
      expect.arrayContaining(['/', '/account', '/account/orders', '/checkout', '/account/login']),
    );
  });

  it('probes the dataset routes of every page bucket, whatever the task', async () => {
    const url = await serve();
    const verifier = routes200Verifier({ target: { url }, dataDir: FIXTURE_DIR });
    const result = await verifier.run(await ctx('gen_homepage'));
    const probes = (result.details as { probes: { route: string; expected: string }[] }).probes;
    expect(probes.filter((p) => p.expected === 'status 200').map((p) => p.route)).toEqual(
      expect.arrayContaining([
        '/collections/dog-essentials',
        '/collections/cat-care',
        '/pages/about-us',
        '/policies/privacy-policy',
      ]),
    );
  });

  it('reports status, redirect target and body excerpt for broken routes', async () => {
    const url = await serve({ broken: ['/collections/dog-essentials'] });
    const verifier = routes200Verifier({ target: { url }, dataDir: FIXTURE_DIR });
    const result = await verifier.run(await ctx('gen_collections'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('/collections/dog-essentials');
    expect(result.feedback).toContain('500');
    expect(result.feedback).toContain('cannot read products of undefined');
  });

  it('fails when the storefront cannot be prepared', async () => {
    const verifier = routes200Verifier({
      target: {
        url: 'http://127.0.0.1:1',
        prepare: async () => {
          throw new Error('build failed: boom');
        },
      },
      dataDir: FIXTURE_DIR,
    });
    const result = await verifier.run(await ctx('gen_homepage'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('did not start');
    expect(result.feedback).toContain('boom');
  });
});

describe('nav_coverage', () => {
  it('passes when every menu target resolves and is linked from the shell', async () => {
    const url = await serve();
    const result = await navCoverageVerifier({ target: { url }, dataDir: FIXTURE_DIR }).run(
      await ctx('gen_navigation'),
    );
    expect(result.verdict).toBe('pass');
  });

  it('fails when a footer target is not linked or does not resolve', async () => {
    const url = await serve({ unlinked: '/policies/privacy-policy', broken: ['/pages/about-us'] });
    const verifier = navCoverageVerifier({ target: { url }, dataDir: FIXTURE_DIR });
    expect(verifier.appliesTo('gen_navigation')).toBe(true);
    expect(verifier.appliesTo('gen_product')).toBe(false);
    const result = await verifier.run(await ctx('gen_navigation'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('/policies/privacy-policy');
    expect(result.feedback).toContain('/pages/about-us');
  });
});

describe('cart_conformance', () => {
  it('stops at the first failing step and names it', async () => {
    const url = await serve({ broken: ['/products/'] });
    const verifier = cartConformanceVerifier({
      target: { url },
      backendUrl: 'http://127.0.0.1:1',
      dataDir: FIXTURE_DIR,
    });
    expect(verifier.appliesTo('gen_cart_search')).toBe(true);
    expect(verifier.appliesTo('gen_checkout')).toBe(true);
    expect(verifier.appliesTo('gen_homepage')).toBe(false);
    const result = await verifier.run(await ctx('gen_cart_search'));
    expect(result.verdict).toBe('fail');
    const steps = (result.details as { steps: { name: string; ok: boolean }[] }).steps;
    expect(steps.at(-1)?.ok).toBe(false);
    expect(result.feedback).toContain(steps.at(-1)?.name ?? '');
  });
});

describe('buildVerifiers with a storefront', () => {
  it('orders storefront verifiers around the backend ones and keeps owned_files first', () => {
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
    const judge = {
      llm: {
        complete: async () => ({
          text: '',
          model: 'm',
          stopReason: 'stop',
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
        }),
      },
      model: { provider: 'fake', id: 'judge' },
    };
    const withJudge = buildVerifiers({
      genBackend: true,
      sidecar,
      ownedFiles,
      storefront: { sidecar: storefront, dataDir: '/d', judge },
    });
    expect(withJudge.map((v) => v.name)).toEqual([
      'owned_files',
      'typecheck',
      'build',
      'routes_200',
      'backend_typecheck',
      'backend_test',
      'sandbox_contract',
      'data_in_use',
      'nav_coverage',
      'cart_conformance',
      'account_flow',
      'discount_flow',
      'visual_judge',
    ]);
    const withoutJudge = buildVerifiers({
      genBackend: false,
      sidecar,
      ownedFiles,
      storefront: { sidecar: storefront, dataDir: '/d' },
    });
    expect(withoutJudge.map((v) => v.name)).toEqual([
      'owned_files',
      'typecheck',
      'build',
      'routes_200',
      'data_in_use',
      'nav_coverage',
      'cart_conformance',
      'account_flow',
      'discount_flow',
    ]);
    expect(buildVerifiers({ genBackend: false, sidecar, ownedFiles }).map((v) => v.name)).toEqual([
      'owned_files',
      'data_in_use',
    ]);
  });
});
