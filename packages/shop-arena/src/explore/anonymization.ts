/**
 * Anonymization verifier: a deterministic scan of the fragment
 * `parts/<task_id>.md` that the current Plan task wrote, for anything that
 * identifies the source storefront. Fragments of other tasks are not read,
 * so one bad fragment cannot reopen another task. The verifier finds the
 * fragment by this name only, so a file that the executor writes under
 * another name is not scanned.
 *
 * Leak markers are derived from the storefront URL and the prefetched
 * homepage: the host (with and without `www.`), absolute URLs on the host,
 * brand tokens from the brand segment of `<title>` and from
 * `og:site_name`, hostname labels, and any email address. The person who
 * runs exploration can add brand terms, such as sub-brands that the title
 * does not name. A hit fails the task with the offending `file:line` list
 * so the executor can rewrite the fragment. A task is reopened at most
 * `MAX_ANONYMIZATION_REOPENS` times; the next hit blocks it with a note
 * that names the fragment. The count per task is kept under
 * `<runDir>/checks/anonymization_reopens.json`, so a resumed run keeps it.
 *
 * The same markers drive the final scan of the published Shop Manual
 * files (`publishedLeaks`), which catches a leak that a blocked task left
 * behind or that synthesis wrote.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

import type { Verifier, VerifierResult } from '@shop-gym/harness';
import { z } from 'zod';

/** Hostname labels shorter than this are too generic to be brand tokens. */
const MIN_LABEL_LENGTH = 4;
/** Title/site-name words shorter than this are ignored. */
const MIN_TOKEN_LENGTH = 3;
/**
 * Splits a `<title>` into "brand | tagline" segments: at a separator with
 * spaces around it, and after a period, an exclamation mark or a question
 * mark that a space follows.
 */
const TITLE_SEPARATORS = /\s+[|\-–—:·]\s+|[.!?]\s+/;
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
/** Shape of `REOPENS_FILE`: the reopen count of each Plan task id. */
const REOPENS_SCHEMA = z.record(z.string(), z.number().int().nonnegative());

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

/** `text` lowercased, with every character that is not a letter or a digit removed. */
function compact(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

/**
 * The compact names that the brand segment of a title can have: each
 * brand label of `labels`, alone and joined with the labels after it. So
 * "Fixture Mart" matches `fixturemart.localhost`, and
 * "FixtureMart.example" matches `www.fixturemart.example`.
 */
function hostnameNames(labels: readonly string[]): Set<string> {
  const names = new Set<string>();
  labels.slice(0, -1).forEach((label, index) => {
    if (label === 'www' || label.length < MIN_LABEL_LENGTH) return;
    names.add(compact(label));
    names.add(compact(labels.slice(index).join('')));
  });
  return names;
}

/**
 * The phrases that give brand tokens: the brand segment of the title and
 * `og:site_name`. The brand segment is the title segment whose compact text
 * matches a hostname label. When no segment matches, every title segment
 * is a phrase, because a false alarm is safer than a missed brand.
 */
function brandPhrases(labels: readonly string[], html: string): string[] {
  const phrases: string[] = [];
  const title = titleOf(html);
  if (title !== null) {
    const segments = title.split(TITLE_SEPARATORS);
    const names = hostnameNames(labels);
    const brand = segments.filter((segment) => names.has(compact(segment)));
    phrases.push(...(brand.length > 0 ? brand : segments));
  }
  const siteName = siteNameOf(html);
  if (siteName !== null) phrases.push(siteName);
  return phrases.map((phrase) => phrase.trim()).filter((phrase) => phrase !== '');
}

/**
 * Brand markers for `hostname` and the homepage `html`: hostname labels and
 * the words of the title's brand segment and `og:site_name`, lowercased and
 * deduped.
 */
export function brandTokens(hostname: string, html: string): string[] {
  const tokens = new Set<string>();
  const labels = hostname.toLowerCase().split('.');
  for (const label of labels.slice(0, -1)) {
    if (label !== 'www' && label.length >= MIN_LABEL_LENGTH) tokens.add(label);
  }
  for (const phrase of brandPhrases(labels, html)) {
    const words = phrase.toLowerCase().split(/[^a-z0-9]+/);
    for (const word of words) {
      if (word.length >= MIN_TOKEN_LENGTH && !STOP_WORDS.has(word)) tokens.add(word);
    }
    const phraseCompact = compact(phrase);
    if (phraseCompact.length >= MIN_LABEL_LENGTH && !STOP_WORDS.has(phraseCompact)) {
      tokens.add(phraseCompact);
    }
  }
  return [...tokens].sort();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * The lowercased words of a brand term: its runs of letters and digits, as
 * for the title tokens.
 *
 * @throws Error when the term has no letter or digit, because it would
 *   then match every line.
 */
function termWords(term: string): string[] {
  const words = term
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((word) => word !== '');
  if (words.length === 0) {
    throw new Error(`brand term ${JSON.stringify(term)} must contain a letter or a digit`);
  }
  return words;
}

/**
 * Checks the brand terms that the person who runs exploration adds.
 *
 * @throws Error when a term has no letter or digit.
 */
export function checkBrandTerms(terms: readonly string[]): void {
  for (const term of terms) termWords(term);
}

/** A compiled scanner for one storefront. */
export type LeakScanner = (file: string, text: string) => Leak[];

/**
 * Builds a scanner from the storefront host, its homepage HTML, and the
 * brand terms of the run. A term matches as a whole word; a term of more
 * than one word matches as a phrase, its words in order with only spaces
 * or punctuation between them, so "Nova Pass" does not match "nova" alone.
 *
 * @throws Error when a brand term has no letter or digit.
 */
export function leakScanner(
  hostname: string,
  html: string,
  brandTerms: readonly string[] = [],
): LeakScanner {
  const host = hostname.toLowerCase().replace(/^www\./, '');
  const patterns: Array<readonly [string, RegExp]> = [
    [host, new RegExp(`(?:^|[^a-z0-9])(?:www\\.)?${escapeRegExp(host)}(?![a-z0-9])`, 'i')],
    ['email', EMAIL_RE],
  ];
  for (const token of brandTokens(hostname, html)) {
    patterns.push([token, new RegExp(`(?<![a-z0-9])${escapeRegExp(token)}(?![a-z0-9])`, 'i')]);
  }
  for (const term of brandTerms) {
    // The words hold only letters and digits, so they need no escaping.
    const words = termWords(term);
    const phrase = words.join('[^a-z0-9]+');
    patterns.push([words.join(' '), new RegExp(`(?<![a-z0-9])${phrase}(?![a-z0-9])`, 'i')]);
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

function formatLeak(leak: Leak): string {
  return `- ${leak.file}:${leak.line} [${leak.marker}]: ${leak.text}`;
}

/** Formats leaks as verifier feedback. */
export function formatLeaks(leaks: readonly Leak[]): string {
  return [
    'Anonymization check failed. These lines identify the source storefront',
    '(store name, brand token, domain, absolute URL, or email). Rewrite them',
    'with generic descriptors and paths only, then mark the task done again.',
    '',
    ...leaks.map(formatLeak),
  ].join('\n');
}

/** The object key at the start of a line that `JSON.stringify(value, null, 2)` wrote. */
const JSON_KEY = /^\s*"(?:[^"\\]|\\.)*":/;

/**
 * The final Anonymization scan: the leaks in the published Shop Manual
 * files, given as file name to text. In a `.json` file the scan reads only
 * the values, because the object keys are schema names and not storefront
 * text; a leak still shows its full line. The scan expects one key per
 * line, as `JSON.stringify(value, null, 2)` writes them.
 */
export function publishedLeaks(
  scanner: LeakScanner,
  files: Readonly<Record<string, string>>,
): Leak[] {
  return Object.entries(files).flatMap(([file, text]) => {
    if (!file.endsWith('.json')) return scanner(file, text);
    const lines = text.split(/\r?\n/);
    const values = lines.map((line) => line.replace(JSON_KEY, '')).join('\n');
    return scanner(file, values).map((leak) => ({
      ...leak,
      text: lines[leak.line - 1]?.trim() ?? leak.text,
    }));
  });
}

/** The final Anonymization scan found a leak in a published file. */
export class AnonymizationLeakError extends Error {
  constructor(readonly leaks: readonly Leak[]) {
    super(
      [
        `the final anonymization scan found ${leaks.length} leak(s) in the published files:`,
        ...leaks.map(formatLeak),
      ].join('\n'),
    );
    this.name = 'AnonymizationLeakError';
  }
}

function readReopens(runDir: string): Record<string, number> {
  const path = join(runDir, REOPENS_FILE);
  return existsSync(path) ? REOPENS_SCHEMA.parse(JSON.parse(readFileSync(path, 'utf8'))) : {};
}

function writeReopens(runDir: string, reopens: Readonly<Record<string, number>>): void {
  const path = join(runDir, REOPENS_FILE);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(reopens, null, 2)}\n`);
}

/**
 * The harness verifier. Reads brand markers from
 * `<artifactDir>/prefetch/index.html` and `brandTerms`, and scans the
 * current task's `<artifactDir>/parts/<task_id>.md` after every executor
 * iteration.
 *
 * @throws Error when a brand term has no letter or digit.
 */
export function anonymizationVerifier(
  storefrontUrl: string,
  brandTerms: readonly string[] = [],
): Verifier {
  const hostname = new URL(storefrontUrl).hostname;
  checkBrandTerms(brandTerms);
  return {
    name: 'anonymization',
    appliesTo: () => true,
    async run(ctx): Promise<VerifierResult> {
      const indexPath = join(ctx.artifactDir, 'prefetch', 'index.html');
      const html = existsSync(indexPath) ? readFileSync(indexPath, 'utf8') : '';
      const fragment = `parts/${ctx.selectedTaskId}.md`;
      const fragmentPath = join(ctx.artifactDir, fragment);
      const leaks = existsSync(fragmentPath)
        ? leakScanner(hostname, html, brandTerms)(fragment, readFileSync(fragmentPath, 'utf8'))
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
          `This task has used ${prior + 1} of ${MAX_ANONYMIZATION_REOPENS} reopens. A leak after the last reopen blocks the task.`,
        ].join('\n'),
        details: { leaks: leaks.length, markers, reopens: prior + 1 },
      };
    },
  };
}
