/**
 * Polite HTTP prefetch of a storefront's public surfaces.
 *
 * Fetches a fixed plan of paths (robots, homepage, sitemap, Shopify JSON
 * endpoints, cart, search, policy and info pages) plus the paginated
 * `products.json` catalog into a directory, and writes `prefetch.json`
 * describing every request. Three gates abort the run before any
 * exploration starts: a `robots.txt` that forbids `/`, an unreachable or
 * blocking homepage, and a Cloudflare challenge page.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

export const DEFAULT_USER_AGENT =
  'ShopExplore/0.1.0 (+https://github.com/agentic-foundation-modeling-research/shop-gym)';
export const DEFAULT_RATE_LIMIT_MS = 500;
export const DEFAULT_TIMEOUT_MS = 30_000;
export const PRODUCTS_PAGE_LIMIT = 250;
export const PRODUCTS_MAX_PAGES = 200;

const BOT_BLOCK_STATUS = new Set([403, 429, 503]);
const CLOUDFLARE_MARKERS = [
  'cf-browser-verification',
  '__cf_chl_',
  'Just a moment...',
  'Checking your browser before accessing',
  'Attention Required! | Cloudflare',
  'cf-challenge-running',
];

/** `[request path, file saved under the prefetch dir]`, fetched in order. */
const FETCH_PLAN: ReadonlyArray<readonly [string, string]> = [
  ['/robots.txt', 'robots.txt'],
  ['/', 'index.html'],
  ['/sitemap.xml', 'sitemap.xml'],
  ['/collections.json?limit=50', 'collections.json'],
  ['/search/suggest.json?q=a&resources[type]=product', 'search_suggest.json'],
  ['/cart.js', 'cart.js'],
  ['/cart', 'cart.html'],
  ['/search', 'search.html'],
  ['/policies/refund-policy', 'policies/refund-policy.html'],
  ['/policies/privacy-policy', 'policies/privacy-policy.html'],
  ['/policies/terms-of-service', 'policies/terms-of-service.html'],
  ['/policies/shipping-policy', 'policies/shipping-policy.html'],
  ['/pages/about', 'pages/about.html'],
  ['/pages/contact', 'pages/contact.html'],
  ['/pages/faq', 'pages/faq.html'],
];

/** Index in `FETCH_PLAN` after which the products pagination runs. */
const PRODUCTS_AFTER_INDEX = 2;

export type UnreachableReason =
  | 'network_error'
  | 'robots_disallow'
  | 'http_status'
  | 'cloudflare_challenge';

/** The storefront cannot be explored; raised before any browser work starts. */
export class ShopUnreachableError extends Error {
  constructor(
    readonly reason: UnreachableReason,
    readonly detail: string,
  ) {
    super(`shop unreachable (${reason}): ${detail}`);
    this.name = 'ShopUnreachableError';
  }
}

/** One request of the prefetch, as recorded in `prefetch.json`. */
export interface PrefetchEntry {
  readonly url: string;
  readonly path: string;
  readonly status: number | null;
  readonly content_type: string | null;
  readonly bytes: number;
  readonly saved_to: string | null;
  readonly error: string | null;
}

/** The `prefetch.json` document. */
export interface PrefetchReport {
  readonly base_url: string;
  readonly user_agent: string;
  readonly started_at: string;
  readonly finished_at: string;
  readonly entries: readonly PrefetchEntry[];
}

export interface PrefetchOptions {
  readonly userAgent?: string;
  readonly rateLimitMs?: number;
  readonly timeoutMs?: number;
}

interface FetchOutcome {
  readonly entry: PrefetchEntry;
  readonly body: Buffer | null;
}

/** Reduces a storefront URL to `scheme://host[:port]`. */
export function normalizeBase(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`invalid storefront URL: ${url}`);
  }
  if (!/^https?:$/.test(parsed.protocol) || parsed.host === '') {
    throw new Error(`invalid storefront URL: ${url}`);
  }
  return `${parsed.protocol}//${parsed.host}`;
}

/** Enforces a minimum gap between consecutive requests. */
class RatePacer {
  private last = Number.NEGATIVE_INFINITY;

  constructor(private readonly minGapMs: number) {}

  async wait(): Promise<void> {
    const due = this.last + this.minGapMs;
    const now = performance.now();
    if (due > now) {
      await sleep(due - now);
    }
    this.last = performance.now();
  }
}

/** True when the parsed robots.txt forbids `/` for user-agent `*`. */
export function robotsDisallowsRoot(robotsTxt: string): boolean {
  let appliesToStar = false;
  let sawAgentLine = false;
  let disallowsRoot = false;
  let allowsRoot = false;
  for (const rawLine of robotsTxt.split(/\r?\n/)) {
    const line = rawLine.split('#')[0]?.trim() ?? '';
    if (line === '') continue;
    const colon = line.indexOf(':');
    if (colon < 0) continue;
    const field = line.slice(0, colon).trim().toLowerCase();
    const value = line.slice(colon + 1).trim();
    if (field === 'user-agent') {
      // A new group starts after a rule line; `*` groups accumulate.
      if (sawAgentLine === false) appliesToStar = false;
      sawAgentLine = true;
      if (value === '*') appliesToStar = true;
      continue;
    }
    sawAgentLine = false;
    if (!appliesToStar) continue;
    if (field === 'disallow' && (value === '/' || value === '/*')) disallowsRoot = true;
    if (field === 'allow' && (value === '/' || value === '/*')) allowsRoot = true;
  }
  return disallowsRoot && !allowsRoot;
}

function errorString(error: unknown): string {
  if (error instanceof Error) {
    const cause = error.cause instanceof Error ? `: ${error.cause.message}` : '';
    return `${error.name}: ${error.message}${cause}`;
  }
  return `Error: ${String(error)}`;
}

async function fetchOne(
  base: string,
  path: string,
  savedTo: string | null,
  outDir: string,
  userAgent: string,
  timeoutMs: number,
): Promise<FetchOutcome> {
  const url = `${base}${path}`;
  const record = (fields: Partial<PrefetchEntry>): PrefetchEntry => ({
    url,
    path,
    status: null,
    content_type: null,
    bytes: 0,
    saved_to: null,
    error: null,
    ...fields,
  });
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { 'user-agent': userAgent },
      redirect: 'follow',
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    return { entry: record({ error: errorString(error) }), body: null };
  }
  let body: Buffer;
  try {
    body = Buffer.from(await response.arrayBuffer());
  } catch (error) {
    return { entry: record({ status: response.status, error: errorString(error) }), body: null };
  }
  const contentType = response.headers.get('content-type');
  if (response.status !== 200 || body.byteLength === 0) {
    return {
      entry: record({ status: response.status, content_type: contentType, bytes: body.byteLength }),
      body,
    };
  }
  if (savedTo !== null) {
    const target = join(outDir, savedTo);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, body);
  }
  return {
    entry: record({
      status: 200,
      content_type: contentType,
      bytes: body.byteLength,
      saved_to: savedTo,
    }),
    body,
  };
}

function parseProductsPage(body: Buffer): unknown[] | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body.toString('utf8'));
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
  const products = (parsed as Record<string, unknown>).products;
  return Array.isArray(products) ? products : null;
}

async function fetchProducts(
  base: string,
  outDir: string,
  userAgent: string,
  timeoutMs: number,
  pacer: RatePacer,
): Promise<PrefetchEntry[]> {
  const entries: PrefetchEntry[] = [];
  const merged: unknown[] = [];
  for (let page = 1; page <= PRODUCTS_MAX_PAGES; page += 1) {
    await pacer.wait();
    const path = `/products.json?page=${page}&limit=${PRODUCTS_PAGE_LIMIT}`;
    const { entry, body } = await fetchOne(base, path, null, outDir, userAgent, timeoutMs);
    const products = entry.status === 200 && body !== null ? parseProductsPage(body) : null;
    if (products === null) {
      entries.push(entry);
      break;
    }
    entries.push(merged.length === 0 ? { ...entry, saved_to: 'products.json' } : entry);
    merged.push(...products);
    if (products.length < PRODUCTS_PAGE_LIMIT) break;
  }
  if (entries.some((entry) => entry.saved_to === 'products.json')) {
    writeFileSync(join(outDir, 'products.json'), `${JSON.stringify({ products: merged })}\n`);
  }
  return entries;
}

function gateIndex(entry: PrefetchEntry, body: Buffer | null): void {
  if (entry.error !== null) {
    throw new ShopUnreachableError('network_error', `/: ${entry.error}`);
  }
  if (entry.status === null || entry.status >= 400 || BOT_BLOCK_STATUS.has(entry.status)) {
    throw new ShopUnreachableError('http_status', `/ returned HTTP ${entry.status}`);
  }
  const text = body?.toString('utf8') ?? '';
  const marker = CLOUDFLARE_MARKERS.find((candidate) => text.includes(candidate));
  if (marker !== undefined) {
    throw new ShopUnreachableError(
      'cloudflare_challenge',
      `/ contains Cloudflare marker '${marker}'`,
    );
  }
}

function sortedJson(value: unknown): string {
  const sortKeys = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(sortKeys);
    if (typeof node === 'object' && node !== null) {
      return Object.fromEntries(
        Object.keys(node as Record<string, unknown>)
          .sort()
          .map((key) => [key, sortKeys((node as Record<string, unknown>)[key])]),
      );
    }
    return node;
  };
  return `${JSON.stringify(sortKeys(value), null, 2)}\n`;
}

/**
 * Prefetches the storefront at `url` into `outDir` and writes `prefetch.json`.
 *
 * @throws ShopUnreachableError when robots.txt, the homepage, or a challenge
 *   page blocks exploration.
 * @throws Error on an invalid URL or a negative rate limit.
 */
export async function prefetch(
  url: string,
  outDir: string,
  options: PrefetchOptions = {},
): Promise<PrefetchReport> {
  const base = normalizeBase(url);
  const userAgent = options.userAgent ?? DEFAULT_USER_AGENT;
  const rateLimitMs = options.rateLimitMs ?? DEFAULT_RATE_LIMIT_MS;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (rateLimitMs < 0) {
    throw new Error(`rateLimitMs must be non-negative, got ${rateLimitMs}`);
  }
  mkdirSync(outDir, { recursive: true });
  const pacer = new RatePacer(rateLimitMs);
  const startedAt = new Date().toISOString();
  const entries: PrefetchEntry[] = [];

  for (const [index, [path, savedTo]] of FETCH_PLAN.entries()) {
    await pacer.wait();
    const { entry, body } = await fetchOne(base, path, savedTo, outDir, userAgent, timeoutMs);
    entries.push(entry);
    if (path === '/robots.txt') {
      if (entry.error !== null) {
        throw new ShopUnreachableError('network_error', `robots.txt: ${entry.error}`);
      }
      if (entry.status === 200 && body !== null && robotsDisallowsRoot(body.toString('utf8'))) {
        throw new ShopUnreachableError('robots_disallow', "robots.txt forbids User-Agent '*' on /");
      }
    } else if (path === '/') {
      gateIndex(entry, body);
    }
    if (index === PRODUCTS_AFTER_INDEX) {
      entries.push(...(await fetchProducts(base, outDir, userAgent, timeoutMs, pacer)));
    }
  }

  const report: PrefetchReport = {
    base_url: base,
    user_agent: userAgent,
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    entries,
  };
  writeFileSync(join(outDir, 'prefetch.json'), sortedJson(report));
  return report;
}
