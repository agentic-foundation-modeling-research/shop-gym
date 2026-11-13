/**
 * Manual synthesis: one LLM completion that turns the merged capabilities
 * and the per-task parts into the anonymized `manual.md`.
 *
 * A manual line with run words tells about the exploration run, not about
 * the storefront: what the run captured, tested or planned, its
 * snapshots, tasks, Iterations, bot checks or browser session. When the
 * manual has such lines, one more completion rewrites only those lines.
 * A rewritten line that still has a run word fails the synthesis.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import type { LlmClient, ModelRef } from '@shop-gym/agent';
import { z } from 'zod';

import type { Capabilities } from './capabilities.js';

/** A response shorter than this is treated as a failed synthesis. */
export const MANUAL_MIN_CHARS = 200;

export class ManualRenderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ManualRenderError';
  }
}

/** The rewrite of the run-note lines failed: a line still has run words, or the reply is malformed. */
export class ManualRunNoteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ManualRunNoteError';
  }
}

/** The synthesis prompt, and the prompt of the one rewrite call for the run-note lines. */
export interface ManualPrompts {
  readonly manual: string;
  /** Has the `{{LINES}}` placeholder. */
  readonly runNoteRewrite: string;
}

/**
 * The run words: words that tell about the exploration run and that
 * storefront prose does not need. The list is narrow on purpose, so that
 * a storefront sentence such as "once per session" does not match.
 */
const RUN_WORD_RE = new RegExp(
  `\\b(?:${[
    'captured',
    '(?:this|the) (?:run|task|iteration)',
    'executors?',
    'harness',
    'iterations?',
    'bot checks?',
    'snapshots?',
    '(?:this|observed|browser) session',
    'originally planned',
    '(?:was|were) not (?:opened|exercised|tested|clicked|dragged|expanded|visited|explored|reached|submitted|scrolled|hovered)',
  ].join('|')})\\b`,
  'gi',
);

/** A reply that is one fenced block, optionally tagged `json`. */
const FENCED_RE = /^```(?:json)?[ \t]*\n([\s\S]*)\n```$/;

/** A manual line with run words. */
interface RunNoteLine {
  /** The 1-based line number in the manual. */
  readonly line: number;
  readonly text: string;
  /** The run words of the line, lowercased, without repeats, in line order. */
  readonly runWords: readonly string[];
}

/** The lines of `manual` that have run words. */
function runNoteLines(manual: string): RunNoteLine[] {
  return manual.split('\n').flatMap((text, index) => {
    const words = [...text.matchAll(RUN_WORD_RE)].map((match) => match[0].toLowerCase());
    return words.length === 0 ? [] : [{ line: index + 1, text, runWords: [...new Set(words)] }];
  });
}

/**
 * The rewritten lines of a rewrite reply: one JSON array of `count`
 * strings, bare or in one fenced block.
 *
 * @throws ManualRunNoteError when the reply is not such an array.
 */
function parseRewrites(reply: string, count: number): string[] {
  const trimmed = reply.trim();
  const body = FENCED_RE.exec(trimmed)?.[1] ?? trimmed;
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    value = undefined;
  }
  const parsed = z.array(z.string()).length(count).safeParse(value);
  if (!parsed.success) {
    throw new ManualRunNoteError(
      `the run-note rewrite reply is not one JSON array of ${count} strings, bare or in one fenced block`,
    );
  }
  return parsed.data;
}

/** Concatenates `parts/*.md` in filename order, one blank line apart. */
export function concatParts(partsDir: string): string {
  const bodies = readdirSync(partsDir)
    .filter((name) => name.endsWith('.md'))
    .sort()
    .map((name) => readFileSync(join(partsDir, name), 'utf8').replace(/\n+$/, ''));
  return bodies.length === 0 ? '' : `${bodies.join('\n\n')}\n`;
}

/** The synthesis prompt: instructions, capabilities JSON, then the parts. */
export function buildManualPrompt(
  manualPrompt: string,
  capabilities: Capabilities,
  partsConcat: string,
): string {
  return [
    manualPrompt.replace(/\n+$/, ''),
    '',
    '## Capabilities',
    '',
    '```json',
    JSON.stringify(capabilities, null, 2),
    '```',
    '',
    '## Per-task parts',
    '',
    partsConcat,
  ].join('\n');
}

/**
 * Renders the manual with one completion. When the manual has lines with
 * run words, one rewrite completion gets only those lines and their run
 * words, and its reply replaces them in place; an empty rewritten line is
 * removed. There is no second rewrite.
 *
 * @throws ManualRenderError when the response is shorter than
 *   `MANUAL_MIN_CHARS`.
 * @throws ManualRunNoteError when the rewrite reply is malformed, or when
 *   a line of the rewritten manual still has run words.
 */
export async function renderManual(
  llm: LlmClient,
  model: ModelRef,
  prompts: ManualPrompts,
  capabilities: Capabilities,
  partsDir: string,
  log: (line: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  const complete = async (prompt: string): Promise<string> => {
    const completion = await llm.complete(signal ? { model, prompt, signal } : { model, prompt });
    return completion.text;
  };
  const text = (
    await complete(buildManualPrompt(prompts.manual, capabilities, concatParts(partsDir)))
  ).trim();
  if (text.length < MANUAL_MIN_CHARS) {
    throw new ManualRenderError(
      `manual response too short (${text.length} chars, need >= ${MANUAL_MIN_CHARS})`,
    );
  }
  const manual = `${text}\n`;
  const flagged = runNoteLines(manual);
  if (flagged.length === 0) return manual;

  log(`the manual has ${flagged.length} run-note lines; asking once for a rewrite`);
  const items = flagged.map(({ text, runWords }) => ({ text, run_words: runWords }));
  // A replacer function, because a manual line can contain `$`.
  const prompt = prompts.runNoteRewrite.replace('{{LINES}}', () => JSON.stringify(items, null, 2));
  const rewrites = parseRewrites(await complete(prompt), flagged.length);
  // `parseRewrites` gives one rewrite for each flagged line.
  const byLine = new Map(flagged.map(({ line }, i) => [line, rewrites[i] as string]));
  const rewritten = manual
    .split('\n')
    .flatMap((line, index) => {
      const rewrite = byLine.get(index + 1);
      if (rewrite === undefined) return [line];
      return rewrite === '' ? [] : [rewrite];
    })
    .join('\n');
  const left = runNoteLines(rewritten);
  if (left.length > 0) {
    throw new ManualRunNoteError(
      `the rewritten manual still has run words: ${left
        .map(({ line, runWords }) => `line ${line}: ${runWords.join(', ')}`)
        .join('; ')}`,
    );
  }
  return rewritten;
}
