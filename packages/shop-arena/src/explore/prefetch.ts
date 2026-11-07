/**
 * Polite HTTP prefetch of a storefront's public surfaces.
 *
 * Every run fetches `robots.txt`, the homepage, `sitemap.xml` and the
 * first `products.json` page, then decides the platform: `shopify` when
 * the homepage has a Shopify marker or `products.json` returns a product
 * list, `generic` otherwise. The Shopify path then reads the rest of the
 * paginated catalog and a fixed plan of Shopify JSON endpoints, cart,
 * search, policy and info pages. The generic path stops there. The
 * results go into a directory with `prefetch.json`, which records the
 * platform and every request. Three gates abort the run before any
 * exploration starts, on both paths: a `robots.txt` that forbids `/`, an
 * unreachable or blocking homepage, and a Cloudflare challenge page.
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

export const DEFAULT_USER_AGENT =
  'ShopExplore/0.1.0 (+https://github.com/agentic-foundation-modeling-research/shop-gym)';
export const DEFAULT_RATE_LIMIT_MS = 500;
export const DEFAULT_TIMEOUT_MS = 30_000;
export const PRODUCTS_PAGE_LIMIT = 250;
export const PRODUCTS_MAX_PAGES = 200;
/** Bytes of `sitemap.xml` that prefetch keeps; a longer body is cut here. */
export const SITEMAP_MAX_BYTES = 1_048_576;

const BOT_BLOCK_STATUS = new Set([403, 429, 503]);
const CLOUDFLARE_MARKERS = [
  'cf-browser-verification',
  '__cf_chl_',
  'Just a moment...',
  'Checking your browser before accessing',
  'Attention Required! | Cloudflare',
  'cf-challenge-running',
];

/** Homepage substrings that only a Shopify storefront serves. */
const SHOPIFY_MARKERS = ['cdn.shopify.com', 'myshopify.com', 'Shopify.theme', 'shopify-section'];

/**
 * `[request path, file saved under the prefetch dir]` that the Shopify
 * path fetches in order after the products pages.
 */
const SHOPIFY_PLAN: ReadonlyArray<readonly [string, string]> = [
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

/** The prefetch path that a storefront takes. */
export type Platform = 'shopify' | 'generic';

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
  /** Present when the body was longer than the bound and was cut at `bytes`. */
  readonly truncated?: true;
}

/** The `prefetch.json` document. */
export interface PrefetchReport {
  readonly base_url: string;
  readonly platform: Platform;
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

/** One `Allow` or `Disallow` line of a robots.txt group. */
interface RobotsRule {
  readonly allow: boolean;
  readonly pattern: string;
}

/** The `Allow` and `Disallow` rules of the robots.txt groups for user-agent `*`. */
function wildcardRules(robotsTxt: string): RobotsRule[] {
  const rules: RobotsRule[] = [];
  let appliesToStar = false;
  let sawAgentLine = false;
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
    if (appliesToStar && (field === 'allow' || field === 'disallow')) {
      rules.push({ allow: field === 'allow', pattern: value });
    }
  }
  return rules;
}

/** True when the parsed robots.txt forbids `/` for user-agent `*`. */
export function robotsDisallowsRoot(robotsTxt: string): boolean {
  const isRoot = (rule: RobotsRule) => rule.pattern === '/' || rule.pattern === '/*';
  const rules = wildcardRules(robotsTxt);
  return (
    rules.some((rule) => !rule.allow && isRoot(rule)) &&
    !rules.some((rule) => rule.allow && isRoot(rule))
  );
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** True when a robots.txt path pattern (with `*` and a final `$`) matches `path`. */
function patternMatches(pattern: string, path: string): boolean {
  const anchored = pattern.endsWith('$');
  const body = anchored ? pattern.slice(0, -1) : pattern;
  const source = body.split('*').map(escapeRegExp).join('.*');
  return new RegExp(`^${source}${anchored ? '$' : ''}`).test(path);
}

/**
 * True when the parsed robots.txt forbids `path` for user-agent `*`. The
 * longest matching rule wins, and `Allow` wins a tie.
 */
export function robotsDisallowsPath(robotsTxt: string, path: string): boolean {
  let best: RobotsRule | undefined;
  for (const rule of wildcardRules(robotsTxt)) {
    if (rule.pattern === '' || !patternMatches(rule.pattern, path)) continue;
    const longer = best === undefined || rule.pattern.length > best.pattern.length;
    const tieAllow =
      best !== undefined && rule.pattern.length === best.pattern.length && rule.allow;
    if (longer || tieAllow) best = rule;
  }
  return best !== undefined && !best.allow;
}

function errorString(error: unknown): string {
  if (error instanceof Error) {
    const cause = error.cause instanceof Error ? `: ${error.cause.message}` : '';
    return `${error.name}: ${error.message}${cause}`;
  }
  return `Error: ${String(error)}`;
}

/** Reads a response body, stopping after `maxBytes` bytes when it is set. */
async function readBody(
  response: Response,
  maxBytes: number | undefined,
): Promise<{ body: Buffer; truncated: boolean }> {
  if (maxBytes === undefined || response.body === null) {
    return { body: Buffer.from(await response.arrayBuffer()), truncated: false };
  }
  const reader = response.body.getReader();
  const chunks: Buffer[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return { body: Buffer.concat(chunks), truncated: false };
    chunks.push(Buffer.from(value));
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      return { body: Buffer.concat(chunks).subarray(0, maxBytes), truncated: true };
    }
  }
}

async function fetchOne(
  base: string,
  path: string,
  savedTo: string | null,
  outDir: string,
  userAgent: string,
  timeoutMs: number,
  maxBytes?: number,
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
  let truncated: boolean;
  try {
    ({ body, truncated } = await readBody(response, maxBytes));
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
      ...(truncated ? { truncated: true } : {}),
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

function hasShopifyMarker(homepage: Buffer | null): boolean {
  const text = homepage?.toString('utf8') ?? '';
  return SHOPIFY_MARKERS.some((marker) => text.includes(marker));
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
  const fetchAndRecord = async (path: string, savedTo: string, maxBytes?: number) => {
    await pacer.wait();
    const outcome = await fetchOne(base, path, savedTo, outDir, userAgent, timeoutMs, maxBytes);
    entries.push(outcome.entry);
    return outcome;
  };

  const robots = await fetchAndRecord('/robots.txt', 'robots.txt');
  if (robots.entry.error !== null) {
    throw new ShopUnreachableError('network_error', `robots.txt: ${robots.entry.error}`);
  }
  const robotsTxt = robots.entry.status === 200 ? (robots.body?.toString('utf8') ?? '') : '';
  if (robotsDisallowsRoot(robotsTxt)) {
    throw new ShopUnreachableError('robots_disallow', "robots.txt forbids User-Agent '*' on /");
  }
  const home = await fetchAndRecord('/', 'index.html');
  gateIndex(home.entry, home.body);
  if (!robotsDisallowsPath(robotsTxt, '/sitemap.xml')) {
    await fetchAndRecord('/sitemap.xml', 'sitemap.xml', SITEMAP_MAX_BYTES);
  }
  const products = await fetchProducts(base, outDir, userAgent, timeoutMs, pacer);
  entries.push(...products);

  const platform: Platform =
    hasShopifyMarker(home.body) || products.some((entry) => entry.saved_to === 'products.json')
      ? 'shopify'
      : 'generic';
  if (platform === 'shopify') {
    for (const [path, savedTo] of SHOPIFY_PLAN) {
      await fetchAndRecord(path, savedTo);
    }
  }

  const report: PrefetchReport = {
    base_url: base,
    platform,
    user_agent: userAgent,
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    entries,
  };
  writeFileSync(join(outDir, 'prefetch.json'), sortedJson(report));
  return report;
}

/**
 * The platform that `prefetch` recorded in `<prefetchDir>/prefetch.json`.
 * A report with no `platform` field comes from the prefetch that knew only
 * Shopify shops, so it reads as `shopify`; older runs then resume unchanged.
 *
 * @throws Error when the file is not a JSON object or records a platform
 *   that is not known.
 */
export function readPlatform(prefetchDir: string): Platform {
  const path = join(prefetchDir, 'prefetch.json');
  const report: unknown = JSON.parse(readFileSync(path, 'utf8'));
  if (typeof report !== 'object' || report === null || Array.isArray(report)) {
    throw new Error(`${path} is not a prefetch report`);
  }
  if (!('platform' in report)) return 'shopify';
  const { platform } = report;
  if (platform === 'shopify' || platform === 'generic') return platform;
  throw new Error(`${path} records an unknown platform ${JSON.stringify(platform)}`);
}
