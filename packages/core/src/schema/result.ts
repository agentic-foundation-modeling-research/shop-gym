/**
 * Benchmark result contracts.
 *
 * An `EpisodeResult` records one agent attempt at one task, including the
 * verdict of every check and the tokens and cost spent. An `Aggregate`
 * rolls a set of episode results up by skill and by shop.
 */

import { z } from 'zod';

import { checkSchema } from './task.js';

const nonNegative = z.number().finite().nonnegative();

/** Token and cost totals, summed over every model call in an episode. */
export const usageSchema = z.object({
  input: nonNegative,
  output: nonNegative,
  cacheRead: nonNegative,
  cacheWrite: nonNegative,
  costUsd: nonNegative,
});

/** Verdict for one check of a task's `eval` list. */
export const checkResultSchema = z.object({
  check: checkSchema,
  passed: z.boolean(),
  /** Human-readable explanation, e.g. the probed value or the judge's reasoning. */
  detail: z.string().optional(),
});

const episodeStatusSchema = z.enum([
  /** The agent called finish with an answer. */
  'completed',
  /** The agent declared the task infeasible. */
  'infeasible',
  /** The episode hit its time or step budget. */
  'aborted',
  /** The runtime or browser failed. */
  'error',
]);

export const episodeResultSchema = z.object({
  taskId: z.string().min(1),
  shop: z.string().min(1),
  skill: z.string().min(1),
  agent: z.object({
    name: z.string().min(1),
    model: z.string().min(1),
  }),
  status: episodeStatusSchema,
  answer: z.string().nullable(),
  finalUrl: z.string().nullable(),
  /** True iff every check passed. */
  passed: z.boolean(),
  checks: z.array(checkResultSchema),
  usage: usageSchema,
  startedAt: z.iso.datetime(),
  durationMs: nonNegative,
  error: z.string().optional(),
  /** Path of the trajectory file, relative to the results directory. */
  trajectoryPath: z.string().optional(),
});

const bucketSchema = z.object({
  total: z.number().int().nonnegative(),
  passed: z.number().int().nonnegative(),
  passRate: z.number().min(0).max(1),
});

/**
 * Roll-up of a results set. The two breakdown keys keep their v1 snake_case
 * names (`by_skill`, `by_shop`) so existing analysis of `aggregate.json`
 * stays comparable.
 */
export const aggregateSchema = z.object({
  total: z.number().int().nonnegative(),
  passed: z.number().int().nonnegative(),
  /** Episodes that did not pass, including `errors`. */
  failed: z.number().int().nonnegative(),
  /** Episodes whose status is `error`. */
  errors: z.number().int().nonnegative(),
  passRate: z.number().min(0).max(1),
  by_skill: z.record(z.string(), bucketSchema),
  by_shop: z.record(z.string(), bucketSchema),
  usage: usageSchema,
});

export type Usage = z.infer<typeof usageSchema>;
export type CheckResult = z.infer<typeof checkResultSchema>;
export type EpisodeStatus = z.infer<typeof episodeStatusSchema>;
export type EpisodeResult = z.infer<typeof episodeResultSchema>;
export type AggregateBucket = z.infer<typeof bucketSchema>;
export type Aggregate = z.infer<typeof aggregateSchema>;
