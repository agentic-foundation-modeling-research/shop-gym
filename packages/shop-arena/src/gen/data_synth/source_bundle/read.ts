/** Reading a complete Source bundle into memory for Shop generation. */

import * as fs from 'node:fs';
import * as path from 'node:path';

import {
  BUNDLE_FILES,
  type BundleManifest,
  COMPLETE_SCHEMAS,
  type UserEvent,
  readJsonlLines,
  userEventSchema,
  validateBundle,
} from '@shop-gym/core';
import type { z } from 'zod';

import { type BundleClock, bundleClock, isBeforeCutoff } from './clock.js';

/** The bundle entries that Shop generation reads. `users/` and `events/` can be absent. */
const READ_ENTRIES = [
  BUNDLE_FILES.manifest,
  path.dirname(BUNDLE_FILES.products),
  path.dirname(BUNDLE_FILES.profiles),
  path.dirname(BUNDLE_FILES.events),
] as const;

/** A product of a complete bundle: it has a description, a brand, a category path, and a price and an inventory on each variant. */
export type CompleteProduct = z.infer<typeof COMPLETE_SCHEMAS.product>;
/** A review of a complete bundle: it names its variant. */
export type CompleteReview = z.infer<typeof COMPLETE_SCHEMAS.review>;
/** A profile of a complete bundle: it has preferences and a narrative. */
export type CompleteProfile = z.infer<typeof COMPLETE_SCHEMAS.profile>;

export interface SourceBundle {
  /** Absolute bundle directory. */
  readonly dir: string;
  readonly manifest: BundleManifest;
  readonly clock: BundleClock;
  readonly products: readonly CompleteProduct[];
  /** The reviews created before the cutoff, in file order. Later reviews stay hidden. */
  readonly reviews: readonly CompleteReview[];
  readonly profiles: readonly CompleteProfile[];
  /** Every User event, in file order. */
  readonly events: readonly UserEvent[];
}

/**
 * The entries of the bundle in `dir` that exist and that Shop generation
 * reads: `bundle.json`, `catalog/`, `users/` and `events/`. The work files
 * of `shopgym bundle` are not among them.
 */
export function sourceBundleInputs(dir: string): string[] {
  return READ_ENTRIES.map((entry) => path.join(dir, entry)).filter((entry) => fs.existsSync(entry));
}

async function readRecords<T>(
  dir: string,
  file: string,
  schema: z.ZodType<T>,
  keep: (record: T) => boolean = () => true,
): Promise<T[]> {
  const full = path.join(dir, file);
  if (!fs.existsSync(full)) return [];
  const records: T[] = [];
  for await (const { text } of readJsonlLines(full)) {
    const record = schema.parse(JSON.parse(text));
    if (keep(record)) records.push(record);
  }
  return records;
}

/**
 * Validates the bundle in `dir` at the `complete` level and reads it.
 *
 * @throws BundleValidationError when the bundle is not complete.
 */
export async function readSourceBundle(dir: string): Promise<SourceBundle> {
  const { manifest } = await validateBundle(dir, 'complete');
  const clock = bundleClock(manifest.cutoff);
  return {
    dir,
    manifest,
    clock,
    products: await readRecords(dir, BUNDLE_FILES.products, COMPLETE_SCHEMAS.product),
    reviews: await readRecords(dir, BUNDLE_FILES.reviews, COMPLETE_SCHEMAS.review, (review) =>
      isBeforeCutoff(clock, review.created_at),
    ),
    profiles: await readRecords(dir, BUNDLE_FILES.profiles, COMPLETE_SCHEMAS.profile),
    events: await readRecords(dir, BUNDLE_FILES.events, userEventSchema),
  };
}
