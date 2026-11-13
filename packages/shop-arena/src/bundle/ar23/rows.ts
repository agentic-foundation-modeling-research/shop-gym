/**
 * The rows of the Amazon Reviews 2023 JSONL files, as far as the adapter
 * reads them. Fields that the adapter does not read are not checked.
 */

import { z } from 'zod';

/** One line of `review_categories/<category>.jsonl`. */
export const reviewRowSchema = z.object({
  /** A whole number of stars, 1 to 5 (the file writes it as `5.0`). */
  rating: z.number().int().min(1).max(5),
  title: z.string(),
  text: z.string(),
  /** The bought variant. */
  asin: z.string().min(1),
  /** The product. */
  parent_asin: z.string().min(1),
  user_id: z.string().min(1),
  /** Milliseconds since the epoch. */
  timestamp: z.number().int().nonnegative(),
  /** A few rows have a negative count; the adapter keeps zero for them. */
  helpful_vote: z.number().int(),
  verified_purchase: z.boolean(),
});

export type ReviewRow = z.infer<typeof reviewRowSchema>;

/** One line of `meta_categories/meta_<category>.jsonl`. */
export const metaRowSchema = z.object({
  parent_asin: z.string().min(1),
  title: z.string().nullish(),
  features: z.array(z.string()).nullish(),
  description: z.array(z.string()).nullish(),
  /** Mostly a number; sometimes text such as `from 29.99`. */
  price: z.union([z.number(), z.string()]).nullish(),
  images: z.array(z.object({ large: z.string().nullish() })).nullish(),
  store: z.string().nullish(),
  categories: z.array(z.string()).nullish(),
  /** Text values, and some nested objects that the adapter skips. */
  details: z.record(z.string(), z.unknown()).nullish(),
  bought_together: z.array(z.string()).nullish(),
});

export type MetaRow = z.infer<typeof metaRowSchema>;

/**
 * Parse one source line.
 *
 * @throws Error naming the file and the line when the line is not a valid row.
 */
export function parseRow<T>(schema: z.ZodType<T>, text: string, file: string, line: number): T {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (err) {
    throw new Error(
      `${file}:${line}: invalid JSON (${err instanceof Error ? err.message : String(err)})`,
    );
  }
  const result = schema.safeParse(value);
  if (!result.success) {
    const issues = result.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`);
    throw new Error(`${file}:${line}: ${issues.join('; ')}`);
  }
  return result.data;
}
