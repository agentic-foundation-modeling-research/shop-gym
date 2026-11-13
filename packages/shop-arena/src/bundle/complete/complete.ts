/**
 * The complete step: a raw Source bundle in, a complete Source bundle in
 * the same schema out. Rules fill the catalog gaps first (`rules.ts`).
 * Then an LLM names the variants that rules cannot (`variant_options.ts`)
 * and writes one User profile per modeled user from that user's history
 * (`profiles.ts`). Each filled field is marked in `provenance`. Reviews and
 * User events are copied without change.
 *
 * Every LLM reply is cached by its input (`llm_cache.ts`), so a rerun with
 * the same raw bundle and model makes no LLM call and writes the same
 * bytes.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  BUNDLE_FILES,
  type BundleReview,
  bundleManifestSchema,
  bundleProductSchema,
  bundleReviewSchema,
  userEventSchema,
  validateBundle,
} from '@shop-gym/core';

import { readJsonFile } from '../../gen/io.js';
import type { LlmCall } from '../../gen/llm.js';
import { readJsonl, writeJsonl } from '../jsonl.js';
import { writeProfiles } from './profiles.js';
import { type RuleFillCounts, fillByRules } from './rules.js';
import { nameVariants } from './variant_options.js';

export interface CompleteDeps {
  readonly call: LlmCall;
  /** Directory of the LLM reply cache; it should outlive the step. */
  readonly cacheDir: string;
  readonly concurrency: number;
  /** Makes the synthetic inventory repeatable. */
  readonly seed: string;
  readonly log: (line: string) => void;
}

/** What the complete step filled: products, or variants for inventory, or profiles. */
export interface CompleteReport extends RuleFillCounts {
  readonly options_synthetic: number;
  readonly profiles_synthetic: number;
}

/**
 * Complete the raw bundle in `rawDir` into `outDir`.
 *
 * @throws BundleValidationError when the raw bundle is not valid at the `raw` level.
 * @throws SynthError when an LLM reply is still not valid after one repair call.
 */
export async function completeBundle(
  rawDir: string,
  outDir: string,
  deps: CompleteDeps,
): Promise<CompleteReport> {
  await validateBundle(rawDir, 'raw');
  const manifest = await readJsonFile(
    path.join(rawDir, BUNDLE_FILES.manifest),
    bundleManifestSchema,
  );
  const raw = await collect(
    readJsonl(path.join(rawDir, BUNDLE_FILES.products), bundleProductSchema),
  );
  const rules = fillByRules(raw, deps.seed);
  const llm = {
    call: deps.call,
    cacheDir: deps.cacheDir,
    concurrency: deps.concurrency,
    log: deps.log,
  };
  const named = await nameVariants(rules.products, llm);
  const products = named.products.map((product) => bundleProductSchema.parse(product));

  const events = await collect(readJsonl(path.join(rawDir, BUNDLE_FILES.events), userEventSchema));
  const reviews: BundleReview[] = [];
  for await (const review of readJsonl(
    path.join(rawDir, BUNDLE_FILES.reviews),
    bundleReviewSchema,
  )) {
    if (review.user_id !== undefined) reviews.push(review);
  }
  const profiles = await writeProfiles(
    { products, events, reviews, cutoff: manifest.cutoff, currency: manifest.currency },
    llm,
  );

  await fs.mkdir(outDir, { recursive: true });
  await fs.copyFile(
    path.join(rawDir, BUNDLE_FILES.manifest),
    path.join(outDir, BUNDLE_FILES.manifest),
  );
  await writeJsonl(path.join(outDir, BUNDLE_FILES.products), products);
  for (const file of [BUNDLE_FILES.reviews, BUNDLE_FILES.events]) {
    await fs.cp(path.join(rawDir, file), path.join(outDir, file));
  }
  await writeJsonl(path.join(outDir, BUNDLE_FILES.profiles), profiles);
  deps.log(
    `[complete] ${products.length} products (${rules.counts.prices_inferred} prices inferred, ${named.named} named variants), ${profiles.length} profiles`,
  );
  return { ...rules.counts, options_synthetic: named.named, profiles_synthetic: profiles.length };
}

async function collect<T>(records: AsyncIterable<T>): Promise<T[]> {
  const all: T[] = [];
  for await (const record of records) all.push(record);
  return all;
}
