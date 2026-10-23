/**
 * Shared state of the synthesis sub-steps: resolved directories, the LLM
 * call settings, the brand allowlist, and the stage cache under
 * `<shopDir>/.shop_gen/stage_cache/` that makes every sub-step resumable.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { StepContext } from '@shop-gym/core';
import type { z } from 'zod';

import { type Allowlist, brandSafetyBlock, loadAllowlist } from '../brands/allowlist.js';
import type { GenConfig } from '../config.js';
import type { GenContext } from '../context.js';
import { readJsonIfExists, writeJsonFile } from '../io.js';
import { type LlmCall, loadPrompt } from '../llm.js';
import type { ImageBackend } from './images/backend.js';

export const STAGE_CACHE_DIR = path.join('.shop_gen', 'stage_cache');
export const IDENTITY_FILE = 'identity.json';
const PROMPTS_DIR = fileURLToPath(new URL('./prompts/', import.meta.url));

export interface SynthContext {
  readonly config: GenConfig;
  readonly shopDir: string;
  readonly manualDir: string;
  readonly dataDir: string;
  readonly cacheDir: string;
  readonly call: LlmCall;
  readonly allowlist: Allowlist;
  readonly images: ImageBackend;
  readonly signal: AbortSignal;
  readonly log: (line: string) => void;
}

export function createSynthContext(ctx: StepContext<GenContext>): SynthContext {
  return {
    config: ctx.context.config,
    shopDir: ctx.outDir,
    manualDir: path.join(ctx.outDir, 'manual'),
    dataDir: path.join(ctx.outDir, 'data'),
    cacheDir: path.join(ctx.outDir, STAGE_CACHE_DIR),
    call: {
      llm: ctx.context.llm,
      model: ctx.context.model,
      timeoutMs: ctx.context.config.llmTimeoutMs,
      signal: ctx.signal,
    },
    allowlist: loadAllowlist(),
    images: ctx.context.images,
    signal: ctx.signal,
    log: ctx.log,
  };
}

/** Returns the cached value at `<cacheDir>/<name>` or produces, stores, and returns it. */
export async function cached<T>(
  sc: SynthContext,
  name: string,
  schema: z.ZodType<T>,
  produce: () => Promise<T>,
): Promise<T> {
  const file = path.join(sc.cacheDir, name);
  const hit = await readJsonIfExists(file, schema);
  if (hit !== undefined) {
    sc.log(`[data_synth] ${name}: cached`);
    return hit;
  }
  const value = await produce();
  await writeJsonFile(file, value);
  return value;
}

/** Renders `prompts/<name>.md`; `brand_safety` is always supplied. */
export function synthPrompt(
  sc: SynthContext,
  name: string,
  values: Readonly<Record<string, string>>,
): string {
  return loadPrompt(PROMPTS_DIR, name, { ...values, brand_safety: brandSafetyBlock(sc.allowlist) });
}

export function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function duplicates(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const dupes = new Set<string>();
  for (const v of values) {
    if (seen.has(v)) dupes.add(v);
    seen.add(v);
  }
  return [...dupes];
}
