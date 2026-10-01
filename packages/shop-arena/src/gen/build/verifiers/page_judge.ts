/**
 * The single visual judge: screenshot one route at the desktop and mobile
 * viewports, show both images to the model with the page's slice of the
 * capabilities document and manual, and parse a structured verdict. The
 * build-loop `visual_judge` verifier and `final_eval` both call this, so
 * one rubric (`prompts/visual_judge.md`) governs every visual verdict.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { type LlmClient, type ModelRef, completeJson } from '@shop-gym/agent';
import type { BrowserSession } from '@shop-gym/browser';
import { z } from 'zod';

import { globToRegExp } from '../owned_files.js';
import type { PageBucket } from './task_routes.js';

export const RUBRIC_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'prompts',
  'visual_judge.md',
);
/** Pages scoring below this fail even when the model says `pass`. */
export const PASS_SCORE = 7;
/** Captures are capped at this many viewport heights to keep images bounded. */
const MAX_CAPTURE_SCREENS = 3;
const SETTLE_MS = 300;
const DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000;
const MANUAL_EXCERPT_CHARS = 6000;
const CAPABILITIES_CHARS = 6000;

export type ViewportName = 'desktop' | 'mobile';

export interface Viewport {
  readonly name: ViewportName;
  readonly width: number;
  readonly height: number;
}

export const JUDGE_VIEWPORTS: readonly Viewport[] = [
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'mobile', width: 375, height: 667 },
];

export const pageVerdictSchema = z.object({
  verdict: z.enum(['pass', 'fail']),
  score: z.number().min(0).max(10),
  categoryScores: z.object({
    structure: z.number().min(0).max(10),
    components: z.number().min(0).max(10),
    visualTone: z.number().min(0).max(10),
  }),
  feedback: z.string(),
  issues: z.array(
    z.object({
      viewport: z.enum(['desktop', 'mobile', 'both']),
      severity: z.enum(['critical', 'major', 'minor']),
      summary: z.string(),
      capability: z.string().nullable(),
    }),
  ),
});
export type PageVerdict = z.infer<typeof pageVerdictSchema>;

export interface PageScreenshot {
  readonly viewport: ViewportName;
  readonly path: string;
}

export interface PageCapture {
  readonly route: string;
  readonly slug: string;
  /** HTTP status of the navigation, `null` when it did not complete. */
  readonly status: number | null;
  readonly screenshots: readonly PageScreenshot[];
  /** Navigation error, when the page could not be loaded. */
  readonly error?: string;
}

export interface CapturePageOptions {
  readonly session: BrowserSession;
  readonly baseUrl: string;
  readonly route: string;
  /** Screenshots are written as `<outDir>/<slug>__<viewport>.png`. */
  readonly outDir: string;
  readonly slug?: string;
  readonly timeoutMs?: number;
}

/** Load `route` at every judge viewport and write one PNG per viewport. */
export async function capturePage(options: CapturePageOptions): Promise<PageCapture> {
  const slug = options.slug ?? routeSlug(options.route);
  const timeout = options.timeoutMs ?? DEFAULT_NAVIGATION_TIMEOUT_MS;
  const page = options.session.page;
  await fs.mkdir(options.outDir, { recursive: true });
  const screenshots: PageScreenshot[] = [];
  let status: number | null = null;
  for (const viewport of JUDGE_VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    try {
      const response = await page.goto(`${options.baseUrl}${options.route}`, {
        waitUntil: 'load',
        timeout,
      });
      status = response?.status() ?? status;
    } catch (error) {
      return { route: options.route, slug, status, screenshots, error: errorMessage(error) };
    }
    await page.waitForTimeout(SETTLE_MS);
    const documentHeight = Number(await page.evaluate('document.documentElement.scrollHeight'));
    const file = path.join(options.outDir, `${slug}__${viewport.name}.png`);
    await page.screenshot({
      path: file,
      type: 'png',
      fullPage: true,
      clip: {
        x: 0,
        y: 0,
        width: viewport.width,
        height: Math.max(
          viewport.height,
          Math.min(documentHeight, viewport.height * MAX_CAPTURE_SCREENS),
        ),
      },
    });
    screenshots.push({ viewport: viewport.name, path: file });
  }
  return { route: options.route, slug, status, screenshots };
}

/** Filesystem-safe name for a route: `/` -> `home`, `/collections/x` -> `collections-x`. */
export function routeSlug(route: string): string {
  const pathname = route.split('?')[0] ?? route;
  const slug = pathname.replace(/^\/+|\/+$/g, '').replace(/[^a-zA-Z0-9]+/g, '-');
  return slug === '' ? 'home' : slug.toLowerCase();
}

export interface JudgeContext {
  /** JSON text of the capabilities slice, or an empty string. */
  readonly capabilities: string;
  /** Manual excerpt relevant to the page, or an empty string. */
  readonly manual: string;
}

export interface JudgePageOptions {
  readonly llm: LlmClient;
  readonly model: ModelRef;
  readonly rubric: string;
  readonly capture: PageCapture;
  readonly context: JudgeContext;
  readonly signal?: AbortSignal;
}

export interface PageJudgement {
  readonly route: string;
  readonly slug: string;
  readonly status: number | null;
  readonly screenshots: readonly PageScreenshot[];
  readonly verdict: PageVerdict;
  /** `verdict` after score and critical-issue coercion. */
  readonly effective: 'pass' | 'fail';
}

/** One model call for one captured page; a capture that failed to load fails without a call. */
export async function judgePage(options: JudgePageOptions): Promise<PageJudgement> {
  const { capture } = options;
  if (capture.error !== undefined || capture.screenshots.length === 0) {
    const summary = `page did not load (status ${capture.status ?? 'none'}): ${capture.error ?? 'no screenshot'}`;
    const verdict: PageVerdict = {
      verdict: 'fail',
      score: 0,
      categoryScores: { structure: 0, components: 0, visualTone: 0 },
      feedback: `${capture.route}: ${summary}`,
      issues: [{ viewport: 'both', severity: 'critical', summary, capability: null }],
    };
    return { ...capture, verdict, effective: 'fail' };
  }
  const images = await Promise.all(
    capture.screenshots.map(async (shot) => ({
      data: (await fs.readFile(shot.path)).toString('base64'),
      mimeType: 'image/png',
    })),
  );
  const text = [
    options.rubric.trim(),
    '',
    '## Page under review',
    '',
    `Route: \`${capture.route}\``,
    `HTTP status: ${capture.status ?? 'unknown'}`,
    `Screenshots, in order: ${capture.screenshots.map((s) => s.viewport).join(', ')}`,
    '',
    '## Capabilities slice',
    '',
    '```json',
    options.context.capabilities === '' ? '{}' : options.context.capabilities,
    '```',
    '',
    '## Manual excerpt',
    '',
    options.context.manual === '' ? '(none)' : options.context.manual,
  ].join('\n');
  const { value } = await completeJson(
    options.llm,
    {
      model: options.model,
      prompt: { text, images },
      ...(options.signal !== undefined ? { signal: options.signal } : {}),
    },
    pageVerdictSchema,
  );
  return { ...capture, verdict: value, effective: coerceVerdict(value) };
}

/** `fail` when the model failed it, scored below `PASS_SCORE`, or found a critical issue. */
export function coerceVerdict(verdict: PageVerdict): 'pass' | 'fail' {
  if (verdict.verdict === 'fail' || verdict.score < PASS_SCORE) {
    return 'fail';
  }
  return verdict.issues.some((issue) => issue.severity === 'critical') ? 'fail' : 'pass';
}

export function loadJudgeRubric(): Promise<string> {
  return fs.readFile(RUBRIC_PATH, 'utf-8');
}

/** Capability key globs per bucket; the union over a page's buckets filters `capabilities.json`. */
const BUCKET_CAPABILITY_GLOBS: Readonly<Record<PageBucket, readonly string[]>> = {
  homepage: ['homepage', 'home.*', 'navigation.header', 'footer'],
  navigation: ['site_shell', 'navigation', 'navigation.*', 'footer', 'intl'],
  collections: ['collection', 'collection.*'],
  product: ['product', 'product.*'],
  cart_search: [
    'cart',
    'cart.*',
    'search',
    'search.*',
    'checkout',
    'checkout.*',
    'account',
    'account.*',
  ],
  info_pages: ['info_pages_present', 'page', 'page.*', 'policies', 'policies.*'],
};

/** Manual part file names containing one of these words are shown to the judge. */
const BUCKET_MANUAL_WORDS: Readonly<Record<PageBucket, readonly string[]>> = {
  homepage: ['home', 'brand', 'theme'],
  navigation: ['nav', 'header', 'footer', 'menu', 'theme'],
  collections: ['collection', 'catalog', 'category'],
  product: ['product', 'variant'],
  cart_search: ['cart', 'search', 'checkout', 'account', 'order'],
  info_pages: ['page', 'policy', 'policies', 'faq', 'contact', 'about'],
};

/**
 * The capabilities slice and manual excerpt for `buckets`.
 *
 * Reads `<manualDir>/capabilities.json` (top-level keys filtered by the
 * bucket globs; the whole document when no key matches) and
 * `<manualDir>/parts/*.md` whose names mention the buckets. Both are
 * optional: missing files yield empty strings.
 */
export async function judgeContext(
  manualDir: string | undefined,
  buckets: readonly PageBucket[],
): Promise<JudgeContext> {
  if (manualDir === undefined) {
    return { capabilities: '', manual: '' };
  }
  return {
    capabilities: await capabilitiesSlice(path.join(manualDir, 'capabilities.json'), buckets),
    manual: await manualExcerpt(path.join(manualDir, 'parts'), buckets),
  };
}

async function capabilitiesSlice(file: string, buckets: readonly PageBucket[]): Promise<string> {
  const raw = await fs.readFile(file, 'utf-8').catch(() => undefined);
  if (raw === undefined) {
    return '';
  }
  const parsed: unknown = JSON.parse(raw);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return truncate(raw, CAPABILITIES_CHARS);
  }
  const patterns = buckets.flatMap((b) => BUCKET_CAPABILITY_GLOBS[b]).map(globToRegExp);
  const entries = Object.entries(parsed as Record<string, unknown>).filter(([key]) =>
    patterns.some((re) => re.test(key)),
  );
  const slice = entries.length > 0 ? Object.fromEntries(entries) : parsed;
  return truncate(JSON.stringify(slice, null, 2), CAPABILITIES_CHARS);
}

async function manualExcerpt(partsDir: string, buckets: readonly PageBucket[]): Promise<string> {
  const names = await fs.readdir(partsDir).catch(() => [] as string[]);
  const words = buckets.flatMap((b) => BUCKET_MANUAL_WORDS[b]);
  const chosen = names
    .filter((name) => name.endsWith('.md') && words.some((w) => name.toLowerCase().includes(w)))
    .sort();
  const parts = await Promise.all(
    chosen.map(
      async (name) => `### ${name}\n\n${await fs.readFile(path.join(partsDir, name), 'utf-8')}`,
    ),
  );
  return truncate(parts.join('\n\n'), MANUAL_EXCERPT_CHARS);
}

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}\n[...truncated]`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Run `fn` over `items` with at most `limit` in flight; results keep input order. */
export async function mapConcurrent<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array<R>(items.length);
  let next = 0;
  async function worker(): Promise<void> {
    while (next < items.length) {
      const index = next;
      next += 1;
      const item = items[index] as T;
      results[index] = await fn(item, index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}
