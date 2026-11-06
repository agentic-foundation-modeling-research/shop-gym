/**
 * Anonymization verifier: a deterministic scan of the fragment
 * `parts/<task_id>.md` that the current Plan task wrote, for anything that
 * identifies the source storefront. Fragments of other tasks are not read,
 * so one bad fragment cannot reopen another task.
 *
 * Leak markers are derived from the storefront URL and the prefetched
 * homepage: the host (with and without `www.`), absolute URLs on the host,
 * brand tokens from `<title>` and `og:site_name`, hostname labels, and any
 * email address. A hit fails the task with the offending `file:line` list
 * so the executor can rewrite the fragment. A task is reopened at most
 * `MAX_ANONYMIZATION_REOPENS` times; the next hit blocks it with a note
 * that names the fragment. The count per task is kept under
 * `<runDir>/checks/anonymization_reopens.json`, so a resumed run keeps it.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

import type { Verifier, VerifierResult } from '@shop-gym/harness';

/** Hostname labels shorter than this are too generic to be brand tokens. */
const MIN_LABEL_LENGTH = 4;
/** Title/site-name words shorter than this are ignored. */
const MIN_TOKEN_LENGTH = 3;
/** Separators that split a `<title>` into "brand | tagline" segments. */
const TITLE_SEPARATORS = /\s+[|\-–—:·]\s+/;
const STOP_WORDS = new Set([
  'the',
  'and',
  'for',
  'shop',
  'store',
  'official',
  'online',
  'home',
  'www',
  'com',
  'net',
  'org',
]);
const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
/** Reopens one Plan task can get from this verifier; the next leak blocks the task. */
const MAX_ANONYMIZATION_REOPENS = 2;
/** Run-dir-relative file with the reopen count of each Plan task. */
const REOPENS_FILE = join('checks', 'anonymization_reopens.json');

export interface Leak {
  readonly file: string;
  readonly line: number;
  readonly marker: string;
  readonly text: string;
}

function decodeEntities(text: string): string {
  return text
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

function titleOf(html: string): string | null {
  const match = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
  return match?.[1] === undefined ? null : decodeEntities(match[1]).trim();
}

function siteNameOf(html: string): string | null {
  const match =
    /<meta[^>]+property=["']og:site_name["'][^>]+content=["']([^"']*)["']/i.exec(html) ??
    /<meta[^>]+content=["']([^"']*)["'][^>]+property=["']og:site_name["']/i.exec(html);
  return match?.[1] === undefined ? null : decodeEntities(match[1]).trim();
}

function brandPhrases(html: string): string[] {
  const phrases: string[] = [];
  const title = titleOf(html);
  if (title !== null) {
    phrases.push(...title.split(TITLE_SEPARATORS));
  }
  const siteName = siteNameOf(html);
  if (siteName !== null) phrases.push(siteName);
  return phrases.map((phrase) => phrase.trim()).filter((phrase) => phrase !== '');
}

/**
 * Brand markers for `hostname` and the homepage `html`: hostname labels and
 * the words of the page title and `og:site_name`, lowercased and deduped.
 */
export function brandTokens(hostname: string, html: string): string[] {
  const tokens = new Set<string>();
  const labels = hostname.toLowerCase().split('.');
  for (const label of labels.slice(0, -1)) {
    if (label !== 'www' && label.length >= MIN_LABEL_LENGTH) tokens.add(label);
  }
  for (const phrase of brandPhrases(html)) {
    const words = phrase.toLowerCase().split(/[^a-z0-9]+/);
    for (const word of words) {
      if (word.length >= MIN_TOKEN_LENGTH && !STOP_WORDS.has(word)) tokens.add(word);
    }
    const compact = phrase.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if (compact.length >= MIN_LABEL_LENGTH) tokens.add(compact);
  }
  return [...tokens].sort();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** A compiled scanner for one storefront. */
export type LeakScanner = (file: string, text: string) => Leak[];

/** Builds a scanner from the storefront host and its homepage HTML. */
export function leakScanner(hostname: string, html: string): LeakScanner {
  const host = hostname.toLowerCase().replace(/^www\./, '');
  const patterns: Array<readonly [string, RegExp]> = [
    [host, new RegExp(`(?:^|[^a-z0-9])(?:www\\.)?${escapeRegExp(host)}(?![a-z0-9])`, 'i')],
    ['email', EMAIL_RE],
  ];
  for (const token of brandTokens(hostname, html)) {
    patterns.push([token, new RegExp(`(?<![a-z0-9])${escapeRegExp(token)}(?![a-z0-9])`, 'i')]);
  }
  return (file, text) => {
    const leaks: Leak[] = [];
    text.split(/\r?\n/).forEach((line, index) => {
      const hit = patterns.find(([, pattern]) => pattern.test(line));
      if (hit !== undefined) {
        leaks.push({ file, line: index + 1, marker: hit[0], text: line.trim() });
      }
    });
    return leaks;
  };
}

/** Formats leaks as verifier feedback. */
export function formatLeaks(leaks: readonly Leak[]): string {
  const lines = leaks.map((leak) => `- ${leak.file}:${leak.line} [${leak.marker}]: ${leak.text}`);
  return [
    'Anonymization check failed. These lines identify the source storefront',
    '(store name, brand token, domain, absolute URL, or email). Rewrite them',
    'with generic descriptors and paths only, then mark the task done again.',
    '',
    ...lines,
  ].join('\n');
}

function readReopens(runDir: string): Record<string, number> {
  const path = join(runDir, REOPENS_FILE);
  return existsSync(path) ? (JSON.parse(readFileSync(path, 'utf8')) as Record<string, number>) : {};
}

function writeReopens(runDir: string, reopens: Readonly<Record<string, number>>): void {
  const path = join(runDir, REOPENS_FILE);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(reopens, null, 2)}\n`);
}

/**
 * The harness verifier. Reads brand markers from
 * `<artifactDir>/prefetch/index.html` and scans the current task's
 * `<artifactDir>/parts/<task_id>.md` after every executor iteration.
 */
export function anonymizationVerifier(storefrontUrl: string): Verifier {
  const hostname = new URL(storefrontUrl).hostname;
  return {
    name: 'anonymization',
    appliesTo: () => true,
    async run(ctx): Promise<VerifierResult> {
      const indexPath = join(ctx.artifactDir, 'prefetch', 'index.html');
      const html = existsSync(indexPath) ? readFileSync(indexPath, 'utf8') : '';
      const fragment = `parts/${ctx.selectedTaskId}.md`;
      const fragmentPath = join(ctx.artifactDir, fragment);
      const leaks = existsSync(fragmentPath)
        ? leakScanner(hostname, html)(fragment, readFileSync(fragmentPath, 'utf8'))
        : [];
      if (leaks.length === 0) return { verdict: 'pass' };
      const reopens = readReopens(ctx.runDir);
      const prior = reopens[ctx.selectedTaskId] ?? 0;
      const markers = [...new Set(leaks.map((leak) => leak.marker))];
      if (prior >= MAX_ANONYMIZATION_REOPENS) {
        return {
          verdict: 'fail',
          feedback: formatLeaks(leaks),
          details: { leaks: leaks.length, markers, reopens: prior },
          blockNote: `${fragment} still identifies the storefront after ${prior} reopens`,
        };
      }
      writeReopens(ctx.runDir, { ...reopens, [ctx.selectedTaskId]: prior + 1 });
      return {
        verdict: 'fail',
        feedback: [
          formatLeaks(leaks),
          '',
          `This task has used ${prior + 1} of ${MAX_ANONYMIZATION_REOPENS} reopens. A leak after the last reopen fails the task.`,
        ].join('\n'),
        details: { leaks: leaks.length, markers, reopens: prior + 1 },
      };
    },
  };
}
