/**
 * `llm_judge` and `fuzzyMatch` grading through an `LlmClient`.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { type LlmClient, type ModelRef, completeJson } from '@shop-gym/agent';
import type { CheckResult, Usage } from '@shop-gym/core';
import { z } from 'zod';

import { fillPlaceholders } from '../placeholders.js';

/** Prompts live outside `src` so the same relative path works from `dist`. */
const PROMPT_PATH = fileURLToPath(new URL('../../prompts/judge.md', import.meta.url));

const verdictSchema = z.object({ passed: z.boolean(), reason: z.string() });

export interface JudgeInput {
  readonly goal: string;
  readonly rubric: string;
  readonly answer: string | null;
  readonly finalUrl: string | null;
  readonly priorChecks: readonly CheckResult[];
  /** PNG bytes of the final page, when a screenshot was captured. */
  readonly screenshot?: Buffer;
  readonly signal?: AbortSignal;
}

/** A judge verdict and what the call cost. */
export interface Verdict {
  readonly passed: boolean;
  readonly reason: string;
  readonly usage: Usage;
}

/** Ask `client` for a pass/fail verdict on `input`. */
export async function judge(
  client: LlmClient,
  model: ModelRef,
  input: JudgeInput,
): Promise<Verdict> {
  const template = await fs.readFile(PROMPT_PATH, 'utf-8');
  const text = fillPlaceholders(template, {
    goal: input.goal,
    rubric: input.rubric,
    answer: input.answer ?? '(no answer)',
    final_url: input.finalUrl ?? '(unknown)',
    check_results:
      input.priorChecks.length === 0
        ? '(none)'
        : input.priorChecks
            .map(
              (c) =>
                `- ${c.check.type}: ${c.passed ? 'pass' : 'fail'}${c.detail ? ` (${c.detail})` : ''}`,
            )
            .join('\n'),
  });
  const images =
    input.screenshot === undefined
      ? []
      : [{ data: input.screenshot.toString('base64'), mimeType: 'image/png' as const }];
  const request = {
    model,
    prompt: { text, images },
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
  const { value, completion } = await completeJson(client, request, verdictSchema);
  return { ...value, usage: completion.usage };
}
