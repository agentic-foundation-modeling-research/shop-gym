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
 * Optional files: `blogs.json`, `metafields.json`, `inventory.json`,
 * `customers.json`, `orders.json`, `commerce.json`.
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

// ── customers.json ─────────────────────────────────────────────────────────

/** Postal address attached to a customer or an order. */
export const addressSchema = z
  .object({
    id: z.number(),
    first_name: nullableString,
    last_name: nullableString,
    company: nullableString,
    address1: z.string(),
    address2: nullableString,
    city: z.string(),
    province: nullableString,
    /** Subdivision code, e.g. "ON". */
    province_code: nullableString,
    country: z.string(),
    /** ISO 3166-1 alpha-2. */
    country_code: z.string(),
    zip: z.string(),
    phone: nullableString,
  })
  .readonly();

/** Element of `customers.json`: a seeded account the sandbox accepts logins for. */
export const customerSchema = z
  .object({
    id: z.number(),
    email: z.string(),
    /** Plain text; the sandbox has no real credential store. */
    password: z.string(),
    first_name: nullableString,
    last_name: nullableString,
    phone: nullableString,
    accepts_marketing: z.boolean(),
    /** ISO 8601. */
    created_at: z.string(),
    addresses: z.array(addressSchema).readonly(),
    /** Must reference one of `addresses[].id` when set. */
    default_address_id: z.number().nullable(),
  })
  .readonly();

export const customersFileSchema = z.array(customerSchema).readonly();

// ── orders.json ────────────────────────────────────────────────────────────

export const orderFinancialStatusSchema = z.enum([
  'AUTHORIZED',
  'PAID',
  'PARTIALLY_PAID',
  'PARTIALLY_REFUNDED',
  'PENDING',
  'REFUNDED',
  'VOIDED',
]);

export const orderFulfillmentStatusSchema = z.enum([
  'FULFILLED',
  'IN_PROGRESS',
  'ON_HOLD',
  'OPEN',
  'PARTIALLY_FULFILLED',
  'PENDING_FULFILLMENT',
  'RESTOCKED',
  'SCHEDULED',
  'UNFULFILLED',
]);

export const orderLineItemSchema = z
  .object({
    /** Numeric variant id; may point at a variant no longer in `products.json`. */
    variant_id: z.number(),
    title: z.string(),
    quantity: z.number().int().positive(),
    /** Unit price at order time, decimal as string. */
    price: z.string(),
  })
  .readonly();

/** Element of `orders.json`: a historical order seeded into every episode. */
export const orderSchema = z
  .object({
    /** Also the order number; rendered as `#<id>` in `Order.name`. */
    id: z.number(),
    /** References `customers.json[].id`; `null` for guest orders. */
    customer_id: z.number().nullable(),
    email: nullableString,
    /** ISO 8601. */
    processed_at: z.string(),
    financial_status: orderFinancialStatusSchema,
    fulfillment_status: orderFulfillmentStatusSchema,
    currency_code: z.string(),
    line_items: z.array(orderLineItemSchema).readonly(),
    shipping_address: addressSchema.nullable(),
    /** Handle of a `commerce.json` shipping method; free-form for seeds. */
    shipping_method: nullableString,
    payment_method: nullableString,
    subtotal_price: z.string(),
    total_shipping_price: z.string(),
    total_tax: z.string(),
    total_price: z.string(),
    /** Discount code applied at checkout, in its `commerce.json` spelling; `null` when none. */
    discount_code: nullableString.default(null),
    /**
     * Amount the code removed, decimal as string: merchandise discount for
     * percent and fixed codes, the shipping charge waived for free shipping.
     */
    discount_amount: z.string().default('0.00'),
  })
  .readonly();

export const ordersFileSchema = z.array(orderSchema).readonly();

// ── commerce.json ──────────────────────────────────────────────────────────

export const shippingMethodSchema = z
  .object({
    handle: z.string(),
    title: z.string(),
    /** Flat rate, decimal as string. */
    price: z.string(),
  })
  .readonly();

/**
 * What a Discount code takes off: a percent of the merchandise subtotal, a
 * fixed amount off the merchandise subtotal, or the whole shipping charge.
 */
export const discountCodeKindSchema = z.enum(['percentage', 'fixed_amount', 'free_shipping']);

/** One Discount code a shopper can type at checkout. */
export const discountCodeSchema = z
  .object({
    /** Matched in any case; unique within the file ignoring case. */
    code: z.string().min(1),
    kind: discountCodeKindSchema,
    /**
     * Decimal as string: the percent for `percentage` ("10" is 10%), the
     * money off for `fixed_amount`. Not used for `free_shipping`.
     */
    amount: z.string(),
    /** Merchandise subtotal before the discount that the cart must reach; `null` for none. */
    minimum_subtotal: nullableString.default(null),
    /** Short shopper-facing text that tells what the code does. */
    hint: z.string(),
  })
  .readonly();

export const paymentMethodSchema = z
  .object({
    handle: z.string(),
    title: z.string(),
  })
  .readonly();

/**
 * `commerce.json`: checkout rules. Every field has a default so the file can
 * be partial or absent (see `DEFAULT_COMMERCE` in the loader).
 */
export const commerceSchema = z
  .object({
    /** Fraction applied to the merchandise subtotal, e.g. 0.13. */
    tax_rate: z.number().min(0).default(0),
    /** Subtotal at or above which shipping is free; `null` disables. */
    free_shipping_threshold: nullableString.default(null),
    shipping_methods: z.array(shippingMethodSchema).readonly().default([]),
    payment_methods: z.array(paymentMethodSchema).readonly().default([]),
    discount_codes: z.array(discountCodeSchema).readonly().default([]),
  })
  .readonly();
