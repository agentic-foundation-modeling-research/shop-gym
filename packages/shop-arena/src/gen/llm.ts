/**
 * LLM plumbing for the gen steps: prompt loading with `{{name}}`
 * placeholders, and structured (JSON) and plain text completions, each with
 * one validation retry. Every call carries the pipeline abort signal and the
 * configured per-call timeout.
 */

import { readFileSync } from 'node:fs';
import * as path from 'node:path';

import { type LlmClient, LlmJsonError, type ModelRef, completeJson } from '@shop-gym/agent';
import type { z } from 'zod';

import { renderPlaceholders } from './build/prompts.js';

export interface LlmCall {
  readonly llm: LlmClient;
  readonly model: ModelRef;
  readonly timeoutMs: number;
  readonly signal: AbortSignal;
}

/** The reply failed validation after the retry. */
export class SynthError extends Error {
  readonly reply: string | undefined;

  constructor(message: string, reply?: string) {
    super(message);
    this.name = 'SynthError';
    this.reply = reply;
  }
}

/** Reads `<dir>/<name>.md` and fills its `{{name}}` placeholders. */
export function loadPrompt(
  dir: string,
  name: string,
  values: Readonly<Record<string, string>>,
): string {
  return renderPlaceholders(readFileSync(path.join(dir, `${name}.md`), 'utf-8'), values);
}

function callSignal(call: LlmCall): AbortSignal {
  return AbortSignal.any([call.signal, AbortSignal.timeout(call.timeoutMs)]);
}

const RETRY_PREFIX =
  'Your previous attempt failed validation with this error:\n  {{error}}\n' +
  'Re-emit the JSON value from scratch, fixing the specific problem above. ' +
  'Output JSON only - no commentary, no code fences, no trailing prose.\n\n';

const TEXT_RETRY_PREFIX =
  'Your previous reply failed validation with this error:\n  {{error}}\n' +
  'Write the reply again from scratch, fixing the specific problem above.\n\n';

/** One attempt's accepted value, or the problem that rejects it. */
type Attempt<T> = { readonly value: T } | { readonly problem: string };

/**
 * Runs `attempt` on `prompt`. When it reports a problem, runs it once more
 * on `prompt` with the problem put before it by `retryPrefix`.
 */
async function withOneRetry<T>(
  prompt: string,
  retryPrefix: string,
  attempt: (text: string) => Promise<Attempt<T>>,
): Promise<T> {
  let problem: string | undefined;
  for (let i = 0; i < 2; i += 1) {
    const result = await attempt(
      problem === undefined ? prompt : retryPrefix.replace('{{error}}', problem) + prompt,
    );
    if ('value' in result) {
      return result.value;
    }
    problem = result.problem;
  }
  throw new SynthError(`LLM reply rejected after retry: ${problem ?? 'unknown error'}`);
}

/**
 * Asks for one JSON value matching `schema`, retrying once with the error
 * message prepended when the reply does not parse, does not match the
 * schema, or `validate` returns a problem.
 */
export async function completeStructured<T>(
  call: LlmCall,
  prompt: string,
  schema: z.ZodType<T>,
  validate: (value: T) => string | undefined = () => undefined,
): Promise<T> {
  return withOneRetry(prompt, RETRY_PREFIX, async (text) => {
    let value: T;
    try {
      ({ value } = await completeJson(
        call.llm,
        { model: call.model, prompt: text, signal: callSignal(call) },
        schema,
      ));
    } catch (err) {
      if (!(err instanceof LlmJsonError)) {
        throw err;
      }
      return { problem: err.message };
    }
    const problem = validate(value);
    return problem === undefined ? { value } : { problem };
  });
}

/**
 * One plain text completion; the trimmed reply must be non-empty. When
 * `validate` returns a problem, retries once with the problem prepended.
 */
export async function completeText(
  call: LlmCall,
  prompt: string,
  validate: (text: string) => string | undefined = () => undefined,
): Promise<string> {
  return withOneRetry(prompt, TEXT_RETRY_PREFIX, async (text) => {
    const completion = await call.llm.complete({
      model: call.model,
      prompt: text,
      signal: callSignal(call),
    });
    const reply = completion.text.trim();
    if (reply === '') {
      throw new SynthError('LLM returned an empty reply');
    }
    const problem = validate(reply);
    return problem === undefined ? { value: reply } : { problem };
  });
}
