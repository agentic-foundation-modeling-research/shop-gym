/**
 * Options of one `buildBundle` run. `bundleOptionsSchema` validates what a
 * caller (library or the `shopgym bundle` CLI) passes in and fills in the
 * defaults.
 */

import { z } from 'zod';

import { DEFAULT_CONCURRENCY, DEFAULT_MODEL } from '../gen/config.js';

/** Source datasets that have an adapter. */
export const BUNDLE_ADAPTERS = ['amazon_reviews_2023'] as const;

export type BundleAdapter = (typeof BUNDLE_ADAPTERS)[number];

/** Pipeline step ids in execution order. */
export const BUNDLE_STEPS = ['sample', 'complete', 'publish'] as const;

export type BundleStepName = (typeof BUNDLE_STEPS)[number];

export const DEFAULT_MIN_EVENTS_BEFORE = 5;

export const bundleOptionsSchema = z.strictObject({
  adapter: z.enum(BUNDLE_ADAPTERS),
  /** Source directory in the layout of the dataset download. */
  sourceDir: z.string().min(1),
  /** Dataset category to read, for example `Video_Games`. */
  category: z.string().regex(/^[A-Za-z0-9_]+$/, 'category must be a dataset category name'),
  /** Bundle directory; its base name is the bundle name. */
  outDir: z.string().min(1),
  /** A date (midnight UTC) or a UTC time; stored as an ISO 8601 time. */
  cutoff: z
    .union([z.iso.date(), z.iso.datetime()])
    .transform((value) => new Date(value).toISOString()),
  /** Product count to fill up to; the histories of modeled users can pass it. */
  products: z.number().int().positive(),
  /** Modeled users to pick. */
  users: z.number().int().positive(),
  seed: z.string().min(1),
  minEventsBefore: z.number().int().nonnegative().default(DEFAULT_MIN_EVENTS_BEFORE),
  /** Keep at most this many reviews of one product, plus the reviews of modeled users. */
  reviewsPerProduct: z.number().int().positive().optional(),
  /** `provider/model-id` for the LLM fills of the complete step. */
  model: z.string().min(1).default(DEFAULT_MODEL),
  /** Parallel LLM calls in the complete step. */
  concurrency: z.number().int().positive().default(DEFAULT_CONCURRENCY),
  /** Force this step and everything after it. */
  from: z.enum(BUNDLE_STEPS).optional(),
});

export type BundleOptionsInput = z.input<typeof bundleOptionsSchema>;
export type BundleOptions = z.infer<typeof bundleOptionsSchema>;
