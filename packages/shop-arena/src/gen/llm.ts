/**
 * LLM plumbing for the gen steps: prompt loading with `{{name}}`
 * placeholders, structured (JSON) completions with one validation retry,
 * and plain text completions. Every call carries the pipeline abort signal
 * and the configured per-call timeout.
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
  let error: string | undefined;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const text = error === undefined ? prompt : RETRY_PREFIX.replace('{{error}}', error) + prompt;
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
      error = err.message;
      continue;
    }
    const problem = validate(value);
    if (problem === undefined) {
      return value;
    }
    error = problem;
  }
  throw new SynthError(`LLM reply rejected after retry: ${error ?? 'unknown error'}`);
}

const TEXT_RETRY_PREFIX =
  'Your previous reply failed validation with this error:\n  {{error}}\n' +
  'Write the reply again from scratch, fixing the specific problem above.\n\n';

/**
 * One plain text completion; the trimmed reply must be non-empty. When
 * `validate` returns a problem, retries once with the problem prepended.
 */
export async function completeText(
  call: LlmCall,
  prompt: string,
  validate: (text: string) => string | undefined = () => undefined,
): Promise<string> {
  let error: string | undefined;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const completion = await call.llm.complete({
      model: call.model,
      prompt: error === undefined ? prompt : TEXT_RETRY_PREFIX.replace('{{error}}', error) + prompt,
      signal: callSignal(call),
    });
    const text = completion.text.trim();
    if (text === '') {
      throw new SynthError('LLM returned an empty reply');
    }
    error = validate(text);
    if (error === undefined) {
      return text;
    }
  }
  throw new SynthError(`LLM reply rejected after retry: ${error ?? 'unknown error'}`);
}
