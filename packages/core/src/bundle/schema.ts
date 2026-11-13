/**
 * Source bundle contract.
 *
 * A Source bundle is one directory with the catalog, the reviews, the User
 * profiles and the User events that Shop generation reads, in one standard
 * shape for every source dataset:
 *
 * ```text
 * <bundle>/
 *   bundle.json            sources, licenses, locale, currency, cutoff, sample options
 *   catalog/products.jsonl one product with its variants per line
 *   catalog/reviews.jsonl  one review per line
 *   users/profiles.jsonl   one User profile per modeled user
 *   events/events.jsonl    one User event per line
 * ```
 *
 * Every record is snake_case JSON. An optional field is absent, never
 * `null`. Ids are the source's own strings and are unique in the bundle.
 * The schemas here are the `raw` level: what an adapter writes from its
 * source. The `complete` level adds the fields that Shop generation needs
 * (see `COMPLETE_SCHEMAS`).
 */

import { z } from 'zod';

import { PAGE_TYPES } from '../schema/site-graph.js';

export const BUNDLE_VERSION = '0.1';

/** Paths of the bundle files, relative to the bundle directory. */
export const BUNDLE_FILES = {
  manifest: 'bundle.json',
  products: 'catalog/products.jsonl',
  reviews: 'catalog/reviews.jsonl',
  profiles: 'users/profiles.jsonl',
  events: 'events/events.jsonl',
} as const;

/** The closed list of User event types. A source type that does not map to one is dropped. */
export const EVENT_TYPES = [
  'page_view',
  'product_view',
  'search',
  'search_result_click',
  'add_to_cart',
  'remove_from_cart',
  'wishlist_add',
  'checkout_start',
  'purchase',
  'review',
  'return',
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

/** How exact an event timestamp is. `order` means the time of an order, not of a click. */
export const TIMESTAMP_PRECISIONS = ['ms', 'second', 'day', 'order'] as const;

export type TimestampPrecision = (typeof TIMESTAMP_PRECISIONS)[number];

/**
 * Where a value comes from: copied from the `source`, `inferred` from other
 * source values by a rule, `synthetic` (written by a model), or `rewritten`
 * from a source value.
 */
export const PROVENANCE_KINDS = ['source', 'inferred', 'synthetic', 'rewritten'] as const;

export type ProvenanceKind = (typeof PROVENANCE_KINDS)[number];

export const PRICE_SENSITIVITIES = ['budget', 'mid', 'premium'] as const;

const idSchema = z.string().min(1);
const textSchema = z.string().min(1);

/**
 * Field path to provenance, for example `{"variants[].price": "inferred"}`
 * or `{"*": "synthetic"}` for the whole record. A field that is not named
 * comes from the source.
 */
export const provenanceSchema = z.record(textSchema, z.enum(PROVENANCE_KINDS));

export const priceSchema = z.strictObject({
  amount: z.number().nonnegative(),
  /** ISO 4217 code; equal to the bundle currency. */
  currency: z.string().regex(/^[A-Z]{3}$/, 'expected an ISO 4217 currency code'),
});

export const bundleSourceSchema = z.strictObject({
  /** Dataset id, for example `amazon_reviews_2023`. */
  dataset: idSchema,
  version: textSchema.optional(),
  /** The license or terms of use, in words. */
  license: textSchema,
  url: z.url().optional(),
  /** The parts of the dataset that were read, for example its categories. */
  subsets: z.array(textSchema).min(1).optional(),
});

/** The options of a seeded sample, so that the same options give the same bundle. */
export const bundleSampleSchema = z.strictObject({
  seed: textSchema,
  products: z.number().int().positive(),
  users: z.number().int().positive(),
  /** A modeled user has at least this many User events before the cutoff. */
  min_events_before: z.number().int().nonnegative(),
  /** At most this many reviews of one product, plus the reviews of modeled users. */
  reviews_per_product: z.number().int().positive().optional(),
});

export const bundleManifestSchema = z.strictObject({
  version: z.literal(BUNDLE_VERSION),
  name: idSchema,
  sources: z.array(bundleSourceSchema).min(1),
  /** BCP 47 locale of all text, for example `en-US`. */
  locale: textSchema,
  currency: z.string().regex(/^[A-Z]{3}$/, 'expected an ISO 4217 currency code'),
  /** One global time: events before it are history, events after it are Task targets. */
  cutoff: z.iso.datetime(),
  sample: bundleSampleSchema.optional(),
});

export const bundleVariantSchema = z.strictObject({
  variant_id: idSchema,
  /** Option name to value, for example `{"Color": "Black"}`. */
  option_values: z.record(textSchema, textSchema).optional(),
  price: priceSchema.optional(),
  inventory: z.number().int().nonnegative().optional(),
});

/** A relative path with `/` separators that stays inside its directory. */
function isInnerPath(value: string): boolean {
  return (
    !value.includes('\\') &&
    value.split('/').every((part) => part !== '' && part !== '.' && part !== '..')
  );
}

export const bundleImageSchema = z
  .strictObject({
    source_url: z.url().optional(),
    /** Local copy, relative to the `catalog/` directory, for example `images/1f3a9c0b7d2e4f60.jpg`. */
    path: textSchema.refine(isInnerPath, 'must be a relative path inside catalog/').optional(),
    alt: textSchema.optional(),
  })
  .refine((image) => image.source_url !== undefined || image.path !== undefined, {
    message: 'an image needs a source_url or a path',
  });

export const bundleProductSchema = z.strictObject({
  product_id: idSchema,
  title: textSchema,
  description: textSchema.optional(),
  bullets: z.array(textSchema).min(1).optional(),
  brand: textSchema.optional(),
  seller: textSchema.optional(),
  /** Most general first, for example `["Video Games", "PC", "Accessories"]`. */
  category_path: z.array(textSchema).min(1).optional(),
  attributes: z.record(textSchema, textSchema).optional(),
  options: z
    .array(z.strictObject({ name: textSchema, values: z.array(textSchema).min(1) }))
    .min(1)
    .optional(),
  variants: z.array(bundleVariantSchema).min(1),
  images: z.array(bundleImageSchema).min(1).optional(),
  /** A rating the source shows. Shop generation recomputes ratings from reviews. */
  rating: z
    .strictObject({
      average: z.number().min(0).max(5),
      count: z.number().int().nonnegative(),
      as_of: z.iso.date().optional(),
    })
    .optional(),
  /** Product ids in this bundle. */
  related: z
    .strictObject({
      bought_together: z.array(idSchema).min(1).optional(),
      also_bought: z.array(idSchema).min(1).optional(),
    })
    .optional(),
  source: z.strictObject({ dataset: idSchema, id: idSchema }).optional(),
  provenance: provenanceSchema.optional(),
});

export const bundleReviewSchema = z.strictObject({
  review_id: idSchema,
  product_id: idSchema,
  variant_id: idSchema.optional(),
  /** Set only when the reviewer is a modeled user. */
  user_id: idSchema.optional(),
  rating: z.number().int().min(1).max(5),
  title: z.string(),
  body: z.string(),
  created_at: z.iso.datetime(),
  verified_purchase: z.boolean(),
  helpful_votes: z.number().int().nonnegative(),
});

/** A modeled user. There are no account fields: Shop generation makes those. */
export const userProfileSchema = z.strictObject({
  user_id: idSchema,
  demographics: z
    .strictObject({
      age_range: textSchema.optional(),
      gender: textSchema.optional(),
      location: z
        .strictObject({ country: textSchema.optional(), region: textSchema.optional() })
        .optional(),
      household: z.array(textSchema).optional(),
    })
    .optional(),
  preferences: z
    .strictObject({
      price_sensitivity: z.enum(PRICE_SENSITIVITIES).optional(),
      /** Each interest is a category path, most general first. */
      category_interests: z.array(z.array(textSchema).min(1)).optional(),
      brand_preferences: z.array(textSchema).optional(),
      focus_aspects: z.array(textSchema).optional(),
    })
    .optional(),
  sizes: z.record(textSchema, textSchema).optional(),
  habits: z.record(textSchema, textSchema).optional(),
  narrative: textSchema.optional(),
  provenance: provenanceSchema.optional(),
});

/** One thing a modeled user did. `raw_type` keeps the source's own name for it. */
export const userEventSchema = z.strictObject({
  event_id: idSchema,
  user_id: idSchema,
  session_id: idSchema.optional(),
  /** Position in the session. */
  seq: z.number().int().nonnegative().optional(),
  timestamp: z.iso.datetime(),
  timestamp_precision: z.enum(TIMESTAMP_PRECISIONS),
  event_type: z.enum(EVENT_TYPES),
  raw_type: textSchema.optional(),
  product_id: idSchema.optional(),
  variant_id: idSchema.optional(),
  quantity: z.number().int().positive().optional(),
  price: priceSchema.optional(),
  order_id: idSchema.optional(),
  /** The search text of a `search` event. */
  query: textSchema.optional(),
  page_type: z.enum(PAGE_TYPES).optional(),
  channel: textSchema.optional(),
  provenance: provenanceSchema.optional(),
});

export type BundleSource = z.infer<typeof bundleSourceSchema>;
export type BundleSample = z.infer<typeof bundleSampleSchema>;
export type BundleManifest = z.infer<typeof bundleManifestSchema>;
export type BundleVariant = z.infer<typeof bundleVariantSchema>;
export type BundleImage = z.infer<typeof bundleImageSchema>;
export type BundleProduct = z.infer<typeof bundleProductSchema>;
export type BundleReview = z.infer<typeof bundleReviewSchema>;
export type UserProfile = z.infer<typeof userProfileSchema>;
export type UserEvent = z.infer<typeof userEventSchema>;
export type Price = z.infer<typeof priceSchema>;

const completeVariantSchema = bundleVariantSchema.required({ price: true, inventory: true });

/**
 * The `complete` level: every product has a description, a brand, a
 * category path, and a price and an inventory on each variant. A product
 * with more than one variant names its options, and each variant has a
 * value for each option. Every review names its variant. Every profile
 * has preferences and a narrative.
 */
export const COMPLETE_SCHEMAS = {
  product: bundleProductSchema
    .required({ description: true, brand: true, category_path: true })
    .extend({ variants: z.array(completeVariantSchema).min(1) })
    .superRefine((product, ctx) => {
      if (product.variants.length < 2) return;
      const names = (product.options ?? []).map((option) => option.name);
      if (names.length === 0) {
        ctx.addIssue({
          code: 'custom',
          path: ['options'],
          message: 'required when there is more than one variant',
        });
        return;
      }
      product.variants.forEach((variant, index) => {
        const missing = names.filter((name) => variant.option_values?.[name] === undefined);
        if (missing.length > 0) {
          ctx.addIssue({
            code: 'custom',
            path: ['variants', index, 'option_values'],
            message: `missing a value for ${missing.join(', ')}`,
          });
        }
      });
    }),
  review: bundleReviewSchema.required({ variant_id: true }),
  profile: userProfileSchema.required({ preferences: true, narrative: true }),
} as const;
