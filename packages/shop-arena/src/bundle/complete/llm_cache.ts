/**
 * A reply cache for the LLM fills of the complete step. Each checked reply
 * is one file, named by the hash of everything that the model gets: the
 * model, the prompt and the reply schema. So a rerun with the same input
 * reads the reply and makes no call, and a changed input makes a new call.
 */

import { createHash } from 'node:crypto';
import * as path from 'node:path';

import { z } from 'zod';

import { readJsonIfExists, writeJsonFile } from '../../gen/io.js';
import { type LlmCall, completeStructured } from '../../gen/llm.js';

export interface CachedReply<T> {
  readonly value: T;
  /** True when the value came from the cache, with no LLM call. */
  readonly cached: boolean;
}

/**
 * The cached reply for this input, or a new one from `completeStructured`
 * (one repair call when the reply fails `schema` or `validate`), which is
 * then cached.
 */
export async function cachedStructured<T>(
  cacheDir: string,
  call: LlmCall,
  prompt: string,
  schema: z.ZodType<T>,
  validate?: (value: T) => string | undefined,
): Promise<CachedReply<T>> {
  const key = createHash('sha256')
    .update(JSON.stringify([call.model, prompt, z.toJSONSchema(schema)]))
    .digest('hex');
  const file = path.join(cacheDir, `${key}.json`);
  const hit = await readJsonIfExists(file, schema);
  if (hit !== undefined) return { value: hit, cached: true };
  const value = await completeStructured(call, prompt, schema, validate);
  await writeJsonFile(file, value);
  return { value, cached: false };
}
