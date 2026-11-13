/**
 * Source bundle validation.
 *
 * `validateBundle` streams every bundle file, checks each record against
 * the schema of the level, and checks the joins between the files:
 *
 * - `reviews.product_id`, `events.product_id` -> `products.product_id`
 * - `reviews.variant_id`, `events.variant_id` -> a variant of that product
 * - `products.related.*` -> `products.product_id`
 * - `reviews.user_id`, `events.user_id` -> `profiles.user_id`, when the
 *   bundle has profiles
 *
 * It also checks that ids are unique (variant ids in the whole bundle) and
 * that every price is in the bundle currency.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

import type { z } from 'zod';

import { readJsonlLines } from './jsonl.js';
import {
  BUNDLE_FILES,
  type BundleManifest,
  type BundleProduct,
  type BundleReview,
  COMPLETE_SCHEMAS,
  type Price,
  type UserEvent,
  type UserProfile,
  bundleManifestSchema,
  bundleProductSchema,
  bundleReviewSchema,
  userEventSchema,
  userProfileSchema,
} from './schema.js';

/**
 * `raw` is what an adapter writes: the core fields and valid joins.
 * `complete` also needs the fields that Shop generation reads.
 */
export const VALIDATION_LEVELS = ['raw', 'complete'] as const;

export type ValidationLevel = (typeof VALIDATION_LEVELS)[number];

/** At most this many problems are listed in an error; the total is always given. */
const MAX_LISTED_PROBLEMS = 50;

export interface BundleCounts {
  readonly products: number;
  readonly variants: number;
  readonly reviews: number;
  readonly profiles: number;
  readonly events: number;
}

export interface BundleValidation {
  readonly level: ValidationLevel;
  readonly manifest: BundleManifest;
  readonly counts: BundleCounts;
}

/**
 * A bundle failed validation. Each problem names the file, the line, the
 * record id and the field, for example
 * `catalog/products.jsonl:3 (product_id "P1"): title: required`.
 */
export class BundleValidationError extends Error {
  constructor(
    /** The first problems found, at most fifty. */
    readonly problems: readonly string[],
    /** The number of problems found. */
    readonly total: number,
  ) {
    const more = total > problems.length ? [`- ... and ${total - problems.length} more`] : [];
    super(
      [
        `the Source bundle has ${total} problem(s):`,
        ...problems.map((problem) => `- ${problem}`),
        ...more,
      ].join('\n'),
    );
    this.name = 'BundleValidationError';
  }
}

class Problems {
  readonly listed: string[] = [];
  total = 0;

  add(problem: string): void {
    this.total += 1;
    if (this.listed.length < MAX_LISTED_PROBLEMS) this.listed.push(problem);
  }
}

interface Schemas {
  readonly product: z.ZodType<BundleProduct>;
  readonly review: z.ZodType<BundleReview>;
  readonly profile: z.ZodType<UserProfile>;
  readonly event: z.ZodType<UserEvent>;
}

const RAW_SCHEMAS: Schemas = {
  product: bundleProductSchema,
  review: bundleReviewSchema,
  profile: userProfileSchema,
  event: userEventSchema,
};

const LEVEL_SCHEMAS: Readonly<Record<ValidationLevel, Schemas>> = {
  raw: RAW_SCHEMAS,
  complete: { ...RAW_SCHEMAS, ...COMPLETE_SCHEMAS },
};

/**
 * Validate the Source bundle in `dir` at `level`.
 *
 * Only `bundle.json` is required at the `raw` level. The `complete` level
 * also needs at least one product, and a profile for every user that has
 * User events.
 *
 * @returns The manifest and the record counts.
 * @throws {BundleValidationError} One or more records or joins are invalid.
 */
export async function validateBundle(
  dir: string,
  level: ValidationLevel,
): Promise<BundleValidation> {
  const problems = new Problems();
  const schemas = LEVEL_SCHEMAS[level];
  const manifest = readManifest(dir, problems);
  const checkPrice = (price: Price | undefined, where: string, field: string): void => {
    if (price !== undefined && manifest !== undefined && price.currency !== manifest.currency) {
      problems.add(
        `${where}: ${field}.currency: ${price.currency} is not the bundle currency ${manifest.currency}`,
      );
    }
  };

  const variantsOf = new Map<string, ReadonlySet<string>>();
  const productOfVariant = new Map<string, string>();
  const related: { where: string; field: string; id: string }[] = [];
  const hasProducts = await forEachRecord(
    dir,
    BUNDLE_FILES.products,
    'product_id',
    schemas.product,
    problems,
    (product, where) => {
      if (variantsOf.has(product.product_id)) {
        problems.add(`${where}: product_id: duplicate`);
        return;
      }
      const variants = new Set<string>();
      product.variants.forEach((variant, index) => {
        const field = `variants[${index}]`;
        const owner = productOfVariant.get(variant.variant_id);
        if (owner === undefined) {
          productOfVariant.set(variant.variant_id, product.product_id);
          variants.add(variant.variant_id);
        } else {
          problems.add(`${where}: ${field}.variant_id: duplicate (also in product "${owner}")`);
        }
        checkPrice(variant.price, where, `${field}.price`);
      });
      variantsOf.set(product.product_id, variants);
      for (const [field, ids] of Object.entries(product.related ?? {})) {
        for (const id of ids ?? []) related.push({ where, field: `related.${field}`, id });
      }
    },
  );
  if (level === 'complete' && (!hasProducts || variantsOf.size === 0)) {
    problems.add(`${BUNDLE_FILES.products}: a complete bundle needs at least one product`);
  }
  for (const ref of related) {
    if (!variantsOf.has(ref.id)) problems.add(`${ref.where}: ${ref.field}: no product "${ref.id}"`);
  }

  const profiles = new Set<string>();
  const hasProfiles = await forEachRecord(
    dir,
    BUNDLE_FILES.profiles,
    'user_id',
    schemas.profile,
    problems,
    (profile, where) => {
      if (profiles.has(profile.user_id)) problems.add(`${where}: user_id: duplicate`);
      profiles.add(profile.user_id);
    },
  );
  const checkRefs = (
    record: {
      readonly product_id?: string | undefined;
      readonly variant_id?: string | undefined;
      readonly user_id?: string | undefined;
    },
    where: string,
  ): void => {
    if (record.product_id !== undefined && !variantsOf.has(record.product_id)) {
      problems.add(`${where}: product_id: no product "${record.product_id}"`);
    } else if (record.variant_id !== undefined) {
      const owner = productOfVariant.get(record.variant_id);
      if (owner === undefined) {
        problems.add(`${where}: variant_id: no variant "${record.variant_id}"`);
      } else if (record.product_id !== undefined && owner !== record.product_id) {
        problems.add(
          `${where}: variant_id: "${record.variant_id}" is a variant of product "${owner}", not "${record.product_id}"`,
        );
      }
    }
    if (record.user_id !== undefined && hasProfiles && !profiles.has(record.user_id)) {
      problems.add(`${where}: user_id: no profile "${record.user_id}"`);
    }
  };

  const reviewIds = new Set<string>();
  await forEachRecord(
    dir,
    BUNDLE_FILES.reviews,
    'review_id',
    schemas.review,
    problems,
    (review, where) => {
      if (reviewIds.has(review.review_id)) problems.add(`${where}: review_id: duplicate`);
      reviewIds.add(review.review_id);
      checkRefs(review, where);
    },
  );

  const eventIds = new Set<string>();
  await forEachRecord(
    dir,
    BUNDLE_FILES.events,
    'event_id',
    schemas.event,
    problems,
    (event, where) => {
      if (eventIds.has(event.event_id)) problems.add(`${where}: event_id: duplicate`);
      eventIds.add(event.event_id);
      checkRefs(event, where);
      checkPrice(event.price, where, 'price');
    },
  );
  if (level === 'complete' && eventIds.size > 0 && !hasProfiles) {
    problems.add(`${BUNDLE_FILES.profiles}: a complete bundle with User events needs profiles`);
  }

  if (problems.total > 0 || manifest === undefined) {
    throw new BundleValidationError(problems.listed, problems.total);
  }
  return {
    level,
    manifest,
    counts: {
      products: variantsOf.size,
      variants: productOfVariant.size,
      reviews: reviewIds.size,
      profiles: profiles.size,
      events: eventIds.size,
    },
  };
}

function readManifest(dir: string, problems: Problems): BundleManifest | undefined {
  const file = path.join(dir, BUNDLE_FILES.manifest);
  if (!fs.existsSync(file)) {
    problems.add(`${BUNDLE_FILES.manifest}: missing`);
    return undefined;
  }
  const value = parseJson(fs.readFileSync(file, 'utf-8'));
  if (value instanceof Error) {
    problems.add(`${BUNDLE_FILES.manifest}: invalid JSON (${value.message})`);
    return undefined;
  }
  const result = bundleManifestSchema.safeParse(value, { reportInput: true });
  if (!result.success) {
    for (const issue of result.error.issues) {
      problems.add(`${BUNDLE_FILES.manifest}: ${formatIssue(issue)}`);
    }
    return undefined;
  }
  return result.data;
}

/**
 * Check each line of one JSONL bundle file against `schema` and pass the
 * valid records to `visit`, with the place to name in a problem.
 *
 * @returns False when the file does not exist.
 */
async function forEachRecord<T>(
  dir: string,
  file: string,
  idField: string,
  schema: z.ZodType<T>,
  problems: Problems,
  visit: (record: T, where: string) => void,
): Promise<boolean> {
  const full = path.join(dir, file);
  if (!fs.existsSync(full)) return false;
  for await (const { line, text } of readJsonlLines(full)) {
    const value = parseJson(text);
    if (value instanceof Error) {
      problems.add(`${file}:${line}: invalid JSON (${value.message})`);
      continue;
    }
    const id =
      typeof value === 'object' && value !== null ? Reflect.get(value, idField) : undefined;
    const where =
      typeof id === 'string' ? `${file}:${line} (${idField} "${id}")` : `${file}:${line}`;
    const result = schema.safeParse(value, { reportInput: true });
    if (result.success) {
      visit(result.data, where);
    } else {
      for (const issue of result.error.issues) problems.add(`${where}: ${formatIssue(issue)}`);
    }
  }
  return true;
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch (err) {
    return err instanceof Error ? err : new Error(String(err));
  }
}

/** `variants[0].price` for the path `['variants', 0, 'price']`, and `record` for the root. */
function formatPath(issuePath: readonly PropertyKey[]): string {
  if (issuePath.length === 0) return 'record';
  return issuePath
    .map((key, index) =>
      typeof key === 'number' ? `[${key}]` : `${index === 0 ? '' : '.'}${String(key)}`,
    )
    .join('');
}

/** A missing field shows as `required`; a refused string, number or boolean is shown. */
function formatIssue(issue: z.core.$ZodIssue): string {
  const input: unknown = issue.input;
  if (issue.code === 'invalid_type' && input === undefined) {
    return `${formatPath(issue.path)}: required`;
  }
  const got = ['string', 'number', 'boolean'].includes(typeof input)
    ? ` (got ${JSON.stringify(input)})`
    : '';
  return `${formatPath(issue.path)}: ${issue.message}${got}`;
}
