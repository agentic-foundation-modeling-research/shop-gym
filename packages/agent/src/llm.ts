/**
 * Single-shot model calls without tools.
 *
 * `LlmClient` is the seam for judges, synthesizers, and graders that want
 * one completion, optionally constrained to a JSON schema. `completeJson`
 * layers schema-validated JSON on top of any client so adapters stay thin.
 */

import type { Usage } from '@shop-gym/core';
import { z } from 'zod';

import type { ModelRef, PromptContent } from './types.js';

/** One completion request. */
export interface CompleteRequest {
  readonly model: ModelRef;
  readonly systemPrompt?: string;
  readonly prompt: string | PromptContent;
  readonly signal?: AbortSignal;
}

/** The model's reply and what it cost. */
export interface Completion {
  readonly text: string;
  readonly model: string;
  readonly stopReason: string;
  readonly usage: Usage;
}

/** Produces single completions for a model. */
export interface LlmClient {
  complete(request: CompleteRequest): Promise<Completion>;
}

/** The provider or SDK reported an error for the call. */
export class LlmError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'LlmError';
  }
}

/** The model replied, but not with JSON matching the requested schema. */
export class LlmJsonError extends Error {
  constructor(
    message: string,
    readonly text: string,
  ) {
    super(message);
    this.name = 'LlmJsonError';
  }
}

/**
 * Complete and parse the reply as JSON matching `schema`.
 *
 * The schema is appended to the prompt as JSON Schema; the reply may be bare
 * JSON or a fenced block. Validation failures raise `LlmJsonError` with the
 * raw text so callers can decide whether to retry.
 */
export async function completeJson<T>(
  client: LlmClient,
  request: CompleteRequest,
  schema: z.ZodType<T>,
): Promise<{ value: T; completion: Completion }> {
  const instruction = `Respond with one JSON value matching this JSON Schema. No prose, no code fence.\n${JSON.stringify(z.toJSONSchema(schema))}`;
  const prompt =
    typeof request.prompt === 'string'
      ? `${request.prompt}\n\n${instruction}`
      : { ...request.prompt, text: `${request.prompt.text}\n\n${instruction}` };
  const completion = await client.complete({ ...request, prompt });
  const parsed = schema.safeParse(extractJson(completion.text));
  if (!parsed.success) {
    throw new LlmJsonError(`reply does not match schema: ${parsed.error.message}`, completion.text);
  }
  return { value: parsed.data, completion };
}

/**
 * Parse the first JSON value in a reply, tolerating a surrounding code fence
 * or prose before the value.
 */
export function extractJson(text: string): unknown {
  const fenced = /```(?:json)?\s*([\s\S]*?)```/.exec(text);
  const body = (fenced?.[1] ?? text).trim();
  const start = body.search(/[[{]/);
  const candidate = start === -1 ? body : body.slice(start);
  try {
    return JSON.parse(candidate);
  } catch (error) {
    throw new LlmJsonError(`reply is not JSON: ${(error as Error).message}`, text);
  }
}
