/**
 * SandboxShop dataset schema (zod).
 *
 * One schema per dataset file under `outputs/shops/<name>/data/`. The TypeScript
 * types in `./types.ts` are inferred from these schemas, so the schema is the
 * single source of truth for the on-disk contract. Every schema is `readonly`:
 * parsed values are frozen snapshots for the lifetime of the server instance.
 *
 * Required files: `store.json`, `products.json`, `collections.json`,
 * `navigation.json`, `pages.json`, `policies.json`.
 * Optional files: `blogs.json`, `metafields.json`, `inventory.json`.
 */

import { z } from 'zod';

const nullableString = z.string().nullable();
const stringList = z.array(z.string()).readonly();

// ── store.json ─────────────────────────────────────────────────────────────

export const storeBrandColorsSchema = z
  .object({
    primary: z.string(),
    secondary: z.string(),
  })
  .readonly();

export const storeBrandSchema = z
  .object({
    logo_url: nullableString,
    colors: storeBrandColorsSchema,
  })
  .readonly();

export const storePaymentSettingsSchema = z
  .object({
    /** VISA, MASTER, AMERICAN_EXPRESS, ... */
    accepted_card_brands: stringList,
  })
  .readonly();

/** Single object in `store.json`. */
export const storeSchema = z
  .object({
    shop_id: z.number(),
    name: z.string(),
    domain: z.string(),
    description: z.string(),
    /** ISO 4217 (USD, CAD, EUR, ...). */
    currency_code: z.string(),
    /** ISO 3166-1 alpha-2. */
    country_code: z.string(),
    payment_settings: storePaymentSettingsSchema,
    brand: storeBrandSchema,
    /**
     * Optional; reserved for dataset-version gating. Producers that dump
     * pydantic models serialise an unset value as JSON `null`, which is
     * treated the same as an absent key.
     */
    dataset_version: z.preprocess((value) => value ?? undefined, z.string().optional()),
  })
  .readonly();

// ── products.json ──────────────────────────────────────────────────────────

export const productOptionSchema = z
  .object({
    name: z.string(),
    /** 1-indexed. */
    position: z.number(),
    values: stringList,
  })
  .readonly();

export const productVariantSchema = z
  .object({
    id: z.number(),
    title: z.string(),
    sku: nullableString,
    /** Decimal as string, e.g. "12.99". */
    price: z.string(),
    compare_at_price: nullableString,
    available: z.boolean(),
    option1: nullableString,
    option2: nullableString,
    option3: nullableString,
    position: z.number(),
    requires_shipping: z.boolean(),
  })
  .readonly();

export const productImageSchema = z
  .object({
    id: z.number(),
    /** Absolute URL or path under `/images/`. */
    src: z.string(),
    alt: nullableString,
    width: z.number(),
    height: z.number(),
    position: z.number(),
  })
  .readonly();

/** Element of `products.json`. */
export const productSchema = z
  .object({
    id: z.number(),
    title: z.string(),
    handle: z.string(),
    description_html: z.string(),
    vendor: z.string(),
    product_type: z.string(),
    tags: stringList,
    /** ISO 8601. */
    published_at: z.string(),
    created_at: z.string(),
    updated_at: z.string(),
    options: z.array(productOptionSchema).readonly(),
    variants: z.array(productVariantSchema).readonly(),
    images: z.array(productImageSchema).readonly(),
  })
  .readonly();

export const productsFileSchema = z.array(productSchema).readonly();

// ── collections.json ───────────────────────────────────────────────────────

/** Element of `collections.json`. */
export const collectionSchema = z
  .object({
    id: z.number(),
    title: z.string(),
    handle: z.string(),
    description: nullableString,
    description_html: nullableString,
    image: productImageSchema.nullable(),
    published_at: nullableString,
    updated_at: nullableString,
    /** e.g. "manual", "best-selling". */
    sort_order: nullableString,
    /** Member product handles. */
    product_handles: stringList,
  })
  .readonly();

export const collectionsFileSchema = z.array(collectionSchema).readonly();

// ── navigation.json ────────────────────────────────────────────────────────

export const navigationItemTypeSchema = z.enum(['COLLECTION', 'PRODUCT', 'PAGE', 'BLOG', 'HTTP']);

/** Menu entry; `children` nests arbitrarily deep. */
export interface NavigationItem {
  readonly title: string;
  /** Absolute URL or relative path. */
  readonly url: string;
  readonly type: z.infer<typeof navigationItemTypeSchema>;
  readonly children: readonly NavigationItem[];
}

export const navigationItemSchema: z.ZodType<NavigationItem> = z
  .object({
    title: z.string(),
    url: z.string(),
    type: navigationItemTypeSchema,
    children: z.lazy(() => z.array(navigationItemSchema).readonly()),
  })
  .readonly();

/** `navigation.json`: keyed map of menu handle to root nav items. */
export const navigationSchema = z
  .record(z.string(), z.array(navigationItemSchema).readonly())
  .readonly();

// ── pages.json / policies.json ─────────────────────────────────────────────

/** Element of `pages.json`. */
export const pageSchema = z
  .object({
    handle: z.string(),
    title: z.string(),
    body_html: z.string(),
  })
  .readonly();

export const pagesFileSchema = z.array(pageSchema).readonly();

/**
 * Element of `policies.json`. Handle is one of privacy-policy,
 * shipping-policy, terms-of-service, refund-policy, subscription-policy.
 */
export const policySchema = pageSchema;

export const policiesFileSchema = z.array(policySchema).readonly();

// ── blogs.json ─────────────────────────────────────────────────────────────

export const articleSchema = z
  .object({
    handle: z.string(),
    title: z.string(),
    content_html: z.string(),
    /** Resolved as `ArticleAuthor.name`. */
    author: nullableString,
    published_at: nullableString,
  })
  .readonly();

/** Element of `blogs.json`. */
export const blogSchema = z
  .object({
    handle: z.string(),
    title: z.string(),
    articles: z.array(articleSchema).readonly(),
  })
  .readonly();

export const blogsFileSchema = z.array(blogSchema).readonly();

// ── metafields.json ────────────────────────────────────────────────────────

export const metafieldSchema = z
  .object({
    namespace: z.string(),
    key: z.string(),
    value: z.string(),
    /** "single_line_text_field", "json", ... */
    type: z.string(),
  })
  .readonly();

const metafieldMapSchema = z.record(z.string(), z.array(metafieldSchema).readonly()).readonly();

/** `metafields.json`; maps are keyed by product / collection handle. */
export const metafieldsFileSchema = z
  .object({
    shop: z.array(metafieldSchema).readonly(),
    products: metafieldMapSchema,
    collections: metafieldMapSchema,
  })
  .readonly();

// ── inventory.json ─────────────────────────────────────────────────────────

/** Per-variant inventory entry. */
export const inventoryEntrySchema = z
  .object({
    /**
     * Stock quantity for this variant. `null` means tracked-but-unknown
     * (returned as `null` to GraphQL); a number is read verbatim.
     */
    quantity_available: z.number().nullable(),
  })
  .readonly();

/**
 * `inventory.json`, keyed by numeric variant id rendered as a string.
 * Variants without a matching entry are treated as untracked.
 */
export const inventoryFileSchema = z
  .record(
    z.string().regex(/^-?(0|[1-9]\d*)$/, 'expected variant id key to be an integer'),
    inventoryEntrySchema,
  )
  .readonly();
