/**
 * Configuration of one `generateShop` run.
 *
 * `genConfigSchema` validates the raw options a caller (library or the
 * `shopgym gen` CLI) passes in and fills in the defaults; `GenConfig` is
 * the resolved shape every step sees through `GenContext`.
 */

import { join } from 'node:path';

import { z } from 'zod';

export const DEFAULT_MODEL = 'anthropic/claude-opus-4-7';
export const DEFAULT_OUTPUT_ROOT = join('outputs', 'shops');
export const DEFAULT_MAX_ITERS = 30;
/** Per-iteration wall clock budget of the build loop. */
export const DEFAULT_BUILD_TIMEOUT_MS = 3_600_000;
/** Wall clock budget of one LLM completion in the synthesis steps. */
export const DEFAULT_LLM_TIMEOUT_MS = 600_000;
export const DEFAULT_CONCURRENCY = 5;

/** Pipeline step ids in execution order. */
export const GEN_STEPS = [
  'manual_merge',
  'data_synth',
  'data_validation',
  'build',
  'final_eval',
  'publish',
] as const;

export type GenStepName = (typeof GEN_STEPS)[number];

export const genStepNameSchema = z.enum(GEN_STEPS);

/** Catalog size targets for data synthesis. */
export const catalogSizeSchema = z.object({
  collections: z.number().int().positive().default(10),
  productsPerCollection: z.number().int().positive().default(20),
  imagesPerProduct: z.number().int().min(0).max(4).default(2),
});

export type CatalogSize = z.infer<typeof catalogSizeSchema>;

export const genConfigSchema = z.object({
  /** Shop slug; also the default output directory name. */
  name: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/, 'name must be a lowercase slug'),
  /** One or more Shop Manual directories (each with `manual.md`, `capabilities.json`, `stats.json`). */
  manualDirs: z.array(z.string().min(1)).min(1),
  /**
   * Dataset directory whose products, collections and images the shop
   * copies instead of synthesizing a catalog. `catalog` and
   * `imageBackend` do not apply when it is set.
   */
  sourceDataDir: z.string().min(1).optional(),
  /** Shop directory. Defaults to `outputs/shops/<name>` under the cwd. */
  outDir: z.string().min(1).optional(),
  /** `provider/model-id` for the LLM-backed synthesis steps. */
  model: z.string().min(1).default(DEFAULT_MODEL),
  /** `provider/model-id` for the build agent. Defaults to `model`. */
  buildModel: z.string().min(1).optional(),
  /** Let the build agent extend the backend copy. */
  genBackend: z.boolean().default(false),
  imageBackend: z.enum(['placeholder', 'openai']).default('placeholder'),
  catalog: catalogSizeSchema.prefault({}),
  /** Executor iterations granted to the build loop. */
  maxIters: z.number().int().positive().default(DEFAULT_MAX_ITERS),
  buildTimeoutMs: z.number().int().positive().default(DEFAULT_BUILD_TIMEOUT_MS),
  llmTimeoutMs: z.number().int().positive().default(DEFAULT_LLM_TIMEOUT_MS),
  /** Force this step and everything after it. */
  from: genStepNameSchema.optional(),
  /** Parallel LLM calls in the per-collection synthesis steps. */
  concurrency: z.number().int().positive().default(DEFAULT_CONCURRENCY),
  /** Resume a build-loop run that ended in a refused status. */
  forceResume: z.boolean().default(false),
});

export type GenConfigInput = z.input<typeof genConfigSchema>;
export type GenConfig = z.infer<typeof genConfigSchema>;

/**
 * Validates `input` and applies defaults.
 *
 * @throws z.ZodError when a field is invalid.
 */
export function parseGenConfig(input: GenConfigInput): GenConfig {
  return genConfigSchema.parse(input);
}
