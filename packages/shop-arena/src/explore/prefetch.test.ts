import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import {
  DEFAULT_USER_AGENT,
  PRODUCTS_PAGE_LIMIT,
  ShopUnreachableError,
  normalizeBase,
  prefetch,
  robotsDisallowsRoot,
} from './prefetch.js';

/** Fixed-plan URLs plus the single products page of a small catalog. */
const EXPECTED_FETCH_COUNT = 16;

interface Route {
  readonly status: number;
  readonly body: string;
  readonly contentType?: string;
}

const HOME =
  '<!doctype html><html><head><title>Fixture Shop | Home</title></head><body>ok</body></html>';

const DEFAULT_ROUTES: Record<string, Route> = {
  '/robots.txt': { status: 200, body: 'User-agent: *\nAllow: /\n' },
  '/': { status: 200, body: HOME, contentType: 'text/html' },
  '/sitemap.xml': { status: 200, body: '<urlset/>', contentType: 'application/xml' },
  '/collections.json?limit=50': {
    status: 200,
    body: JSON.stringify({ collections: [{ handle: 'all', products_count: 3 }] }),
  },
  '/search/suggest.json?q=a&resources[type]=product': {
    status: 200,
    body: JSON.stringify({ resources: { results: { products: [] } } }),
  },
  '/cart.js': { status: 200, body: JSON.stringify({ currency: 'USD', items: [] }) },
  '/cart': { status: 200, body: '<html>cart</html>' },
  '/search': { status: 200, body: '<html>search</html>' },
  '/policies/refund-policy': { status: 200, body: '<html>refund</html>' },
  '/policies/privacy-policy': { status: 200, body: '<html>privacy</html>' },
  '/policies/terms-of-service': { status: 200, body: '<html>tos</html>' },
  '/policies/shipping-policy': { status: 200, body: '<html>shipping</html>' },
  '/pages/about': { status: 200, body: '<html>about</html>' },
  '/pages/contact': { status: 200, body: '<html>contact</html>' },
  '/pages/faq': { status: 200, body: '<html>faq</html>' },
};

function products(count: number, offset = 0): string {
  const items = Array.from({ length: count }, (_, i) => ({
    id: offset + i,
    title: `Item ${offset + i}`,
    variants: [{ price: '10.00' }],
    options: [{ name: 'Size' }],
  }));
  return JSON.stringify({ products: items });
}

let server: http.Server;
let baseUrl = '';
let routes: Record<string, Route>;
let productPages: Record<number, string>;
let seen: http.IncomingMessage[];
let outDir: string;

beforeAll(async () => {
  server = http.createServer((req, res) => {
    seen.push(req);
    const url = new URL(req.url ?? '/', 'http://localhost');
    if (url.pathname === '/products.json') {
      const page = Number(url.searchParams.get('page'));
      const body = productPages[page];
      if (body === undefined) {
        res.writeHead(404).end();
      } else {
        res.writeHead(200, { 'content-type': 'application/json' }).end(body);
      }
      return;
    }
    const route = routes[decodeURIComponent(req.url ?? '/')];
    if (route === undefined) {
      res.writeHead(404).end('not found');
      return;
    }
    res.writeHead(route.status, { 'content-type': route.contentType ?? 'text/plain' });
    res.end(route.body);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

beforeEach(() => {
  routes = { ...DEFAULT_ROUTES };
  productPages = { 1: products(3) };
  seen = [];
  outDir = mkdtempSync(join(tmpdir(), 'prefetch-'));
});

afterEach(() => {
  rmSync(outDir, { recursive: true, force: true });
});

const run = () => prefetch(baseUrl, outDir, { rateLimitMs: 0 });

async function unreachable(): Promise<ShopUnreachableError> {
  try {
    await run();
  } catch (error) {
    if (error instanceof ShopUnreachableError) return error;
    throw error;
  }
  throw new Error('expected ShopUnreachableError');
}

describe('prefetch', () => {
  it('writes every planned file and prefetch.json on the happy path', async () => {
    const report = await run();
    expect(report.base_url).toBe(baseUrl);
    expect(report.entries).toHaveLength(EXPECTED_FETCH_COUNT);
    for (const file of [
      'robots.txt',
      'index.html',
      'sitemap.xml',
      'collections.json',
      'search_suggest.json',
      'cart.js',
      'cart.html',
      'search.html',
      'policies/refund-policy.html',
      'policies/privacy-policy.html',
      'policies/terms-of-service.html',
      'policies/shipping-policy.html',
      'pages/about.html',
      'pages/contact.html',
      'pages/faq.html',
      'products.json',
      'prefetch.json',
    ]) {
      expect(existsSync(join(outDir, file)), file).toBe(true);
    }
    const onDisk = JSON.parse(readFileSync(join(outDir, 'prefetch.json'), 'utf8'));
    expect(onDisk.entries).toHaveLength(EXPECTED_FETCH_COUNT);
    expect(Object.keys(onDisk)).toEqual([
      'base_url',
      'entries',
      'finished_at',
      'started_at',
      'user_agent',
    ]);
    expect(readFileSync(join(outDir, 'prefetch.json'), 'utf8').endsWith('\n')).toBe(true);
    expect(JSON.parse(readFileSync(join(outDir, 'products.json'), 'utf8')).products).toHaveLength(
      3,
    );
  });

  it('sends the user agent on every request', async () => {
    await run();
    expect(seen.length).toBe(EXPECTED_FETCH_COUNT);
    for (const req of seen) {
      expect(req.headers['user-agent']).toBe(DEFAULT_USER_AGENT);
    }
  });

  it('aborts with http_status when the homepage returns 403', async () => {
    routes['/'] = { status: 403, body: 'blocked' };
    const error = await unreachable();
    expect(error.reason).toBe('http_status');
    expect(error.message).toBe('shop unreachable (http_status): / returned HTTP 403');
  });

  it('aborts with cloudflare_challenge when the homepage is a challenge page', async () => {
    routes['/'] = { status: 200, body: '<html><title>Just a moment...</title></html>' };
    const error = await unreachable();
    expect(error.reason).toBe('cloudflare_challenge');
  });

  it('aborts with robots_disallow after fetching only robots.txt', async () => {
    routes['/robots.txt'] = { status: 200, body: 'User-agent: *\nDisallow: /\n' };
    const error = await unreachable();
    expect(error.reason).toBe('robots_disallow');
    expect(seen.map((req) => req.url)).toEqual(['/robots.txt']);
  });

  it('aborts with network_error when robots.txt is unreachable', async () => {
    const closed = http.createServer();
    await new Promise<void>((resolve) => closed.listen(0, '127.0.0.1', resolve));
    const port = (closed.address() as AddressInfo).port;
    await new Promise<void>((resolve) => closed.close(() => resolve()));
    await expect(
      prefetch(`http://127.0.0.1:${port}`, outDir, { rateLimitMs: 0 }),
    ).rejects.toMatchObject({ reason: 'network_error' });
  });

  it('records optional endpoint failures without saving or aborting', async () => {
    routes['/cart.js'] = { status: 404, body: 'nope' };
    const report = await run();
    const cart = report.entries.find((entry) => entry.path === '/cart.js');
    expect(cart).toMatchObject({ status: 404, saved_to: null, error: null });
    expect(existsSync(join(outDir, 'cart.js'))).toBe(false);
  });

  it('rejects a negative rate limit', async () => {
    await expect(prefetch(baseUrl, outDir, { rateLimitMs: -1 })).rejects.toThrow(/non-negative/);
  });

  it('paginates products.json until a short page and merges the pages', async () => {
    productPages = {
      1: products(PRODUCTS_PAGE_LIMIT),
      2: products(50, PRODUCTS_PAGE_LIMIT),
      3: products(1, 300),
    };
    const report = await run();
    const pages = report.entries.filter((entry) => entry.path.startsWith('/products.json'));
    expect(pages.map((entry) => entry.path)).toEqual([
      `/products.json?page=1&limit=${PRODUCTS_PAGE_LIMIT}`,
      `/products.json?page=2&limit=${PRODUCTS_PAGE_LIMIT}`,
    ]);
    expect(pages.map((entry) => entry.saved_to)).toEqual(['products.json', null]);
    const merged = JSON.parse(readFileSync(join(outDir, 'products.json'), 'utf8'));
    expect(merged.products).toHaveLength(300);
  });

  it('places the products pages right after the sitemap entry', async () => {
    const report = await run();
    expect(report.entries.slice(2, 4).map((entry) => entry.path)).toEqual([
      '/sitemap.xml',
      `/products.json?page=1&limit=${PRODUCTS_PAGE_LIMIT}`,
    ]);
  });
});

describe('normalizeBase', () => {
  it('keeps only scheme and host', () => {
    expect(normalizeBase('https://example-shop.com/collections/all?x=1')).toBe(
      'https://example-shop.com',
    );
  });

  it('rejects URLs without a scheme or host', () => {
    expect(() => normalizeBase('example-shop.com')).toThrow(/invalid storefront URL/);
    expect(() => normalizeBase('mailto:someone@example-shop.com')).toThrow(/invalid/);
  });
});

describe('robotsDisallowsRoot', () => {
  it('detects a root disallow for the wildcard agent', () => {
    expect(robotsDisallowsRoot('User-agent: *\nDisallow: /\n')).toBe(true);
  });

  it('ignores disallows scoped to other agents or other paths', () => {
    expect(
      robotsDisallowsRoot('User-agent: Bot\nDisallow: /\n\nUser-agent: *\nDisallow: /admin\n'),
    ).toBe(false);
  });
});
