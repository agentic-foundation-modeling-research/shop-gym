/**
 * Manual synthesis: one LLM completion that turns the merged capabilities
 * and the per-task parts into the anonymized `manual.md`.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import type { LlmClient, ModelRef } from '@shop-gym/agent';

import type { Capabilities } from './capabilities.js';

/** A response shorter than this is treated as a failed synthesis. */
export const MANUAL_MIN_CHARS = 200;

export class ManualRenderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ManualRenderError';
  }
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
 * Renders the manual with one completion.
 *
 * @throws ManualRenderError when the response is shorter than
 *   `MANUAL_MIN_CHARS`.
 */
export async function renderManual(
  llm: LlmClient,
  model: ModelRef,
  manualPrompt: string,
  capabilities: Capabilities,
  partsDir: string,
  signal?: AbortSignal,
): Promise<string> {
  const prompt = buildManualPrompt(manualPrompt, capabilities, concatParts(partsDir));
  const completion = await llm.complete(signal ? { model, prompt, signal } : { model, prompt });
  const text = completion.text.trim();
  if (text.length < MANUAL_MIN_CHARS) {
    throw new ManualRenderError(
      `manual response too short (${text.length} chars, need >= ${MANUAL_MIN_CHARS})`,
    );
  }
  return `${text}\n`;
}
