/**
 * Typed configuration for one shop's benchmark run. Paths are resolved
 * relative to the config file when loaded with `loadGuruConfig`.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { ModelRef } from '@shop-gym/agent';
import { z } from 'zod';

import { DEFAULT_SKILL_CAPS } from './seed/index.js';

const modelRefSchema = z
  .object({
    provider: z.string().min(1),
    id: z.string().min(1),
    thinking: z.enum(['off', 'low', 'medium', 'high']).optional(),
  })
  .transform(
    ({ provider, id, thinking }): ModelRef =>
      thinking === undefined ? { provider, id } : { provider, id, thinking },
  );

export const guruConfigSchema = z.object({
  /** Shop identifier used in task ids and output paths. */
  shop: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/),
  /** Storefront origin the agents browse. */
  shopUrl: z.url(),
  /** Sandbox backend origin (GraphQL at `/graphql`, control API at `/__shopgym`). */
  backendUrl: z.url(),
  /** SandboxShop dataset directory (`products.json`, `customers.json`, ...). */
  dataDir: z.string().min(1),
  /** Root receiving `<shop>/benchmarks`, `<shop>/explore`, `<shop>/runs`. */
  outDir: z.string().min(1),
  /** Model for the solver agent and the explorer. */
  model: modelRefSchema,
  /** Model for `llm_judge` and `fuzzyMatch`; defaults to `model`. */
  judgeModel: modelRefSchema.optional(),
  /** Seed for deterministic generators. */
  seed: z.string().min(1).default('shopgym'),
  /** Maximum tasks kept per skill. */
  caps: z.record(z.string(), z.number().int().nonnegative()).default(DEFAULT_SKILL_CAPS),
  /** Episodes in flight at once. */
  concurrency: z.number().int().positive().default(1),
  episodeTimeoutMs: z.number().int().positive().default(600_000),
  /** Upper bound on tasks accepted from one explore run. */
  exploreMaxTasks: z.number().int().positive().default(10),
  headless: z.boolean().default(true),
});

export type GuruConfigInput = z.input<typeof guruConfigSchema>;
export type GuruConfig = z.output<typeof guruConfigSchema>;

/** Parse a config object, applying defaults. */
export function parseGuruConfig(input: unknown): GuruConfig {
  return guruConfigSchema.parse(input);
}

/** Read and parse a JSON config file; `dataDir` and `outDir` resolve against its directory. */
export async function loadGuruConfig(file: string): Promise<GuruConfig> {
  const config = parseGuruConfig(JSON.parse(await fs.readFile(file, 'utf-8')));
  const dir = path.dirname(path.resolve(file));
  return {
    ...config,
    dataDir: path.resolve(dir, config.dataDir),
    outDir: path.resolve(dir, config.outDir),
  };
}

/** `<outDir>/<shop>`. */
export function shopOutDir(config: GuruConfig): string {
  return path.join(config.outDir, config.shop);
}
