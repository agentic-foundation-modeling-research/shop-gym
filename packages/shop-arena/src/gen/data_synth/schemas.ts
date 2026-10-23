/**
 * Zod schemas for what the LLM returns in each synthesis step and for the
 * stage-cache files under `.shop_gen/stage_cache/`. Dataset files use the
 * backend schema (`@shop-gym/shop-backend`) instead.
 */

import { z } from 'zod';

const HANDLE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const PRICE = /^\d+(?:\.\d{1,2})?$/;

export const handleSchema = z.string().regex(HANDLE, 'handle must be a lowercase slug');
export const priceSchema = z.string().regex(PRICE, 'price must be a decimal string like 29.99');

/** `identity.json` at the shop root. */
export const identitySchema = z.object({
  name: z.string().min(1),
  descriptor: z.string().min(1),
  tone: z.array(z.string().min(1)).min(1).max(3),
  currency: z.string().regex(/^[A-Z]{3}$/),
  country: z.string().regex(/^[A-Z]{2}$/),
});
export type Identity = z.infer<typeof identitySchema>;

/** LLM reply for `synth_identity` (the name is picked from the allowlist). */
export const identityDraftSchema = identitySchema.omit({ name: true });

export const storeDraftSchema = z.object({
  domain: z.string().regex(/^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:example|test|invalid)$/),
  description: z.string().min(1).max(320),
  payment_settings: z.object({ accepted_card_brands: z.array(z.string().min(1)).min(1).max(4) }),
  brand: z.object({
    logo_url: z.string().nullable(),
    colors: z.object({
      primary: z.string().regex(/^#[0-9a-fA-F]{6}$/),
      secondary: z.string().regex(/^#[0-9a-fA-F]{6}$/),
    }),
  }),
});
export type StoreDraft = z.infer<typeof storeDraftSchema>;

export const collectionDraftSchema = z.object({
  title: z.string().min(1),
  handle: handleSchema,
  description: z.string().min(1).max(240),
  sort_order: z.enum([
    'manual',
    'best-selling',
    'created-desc',
    'price-asc',
    'price-desc',
    'alpha-asc',
  ]),
  target_product_count: z.number().int().min(1),
});
export type CollectionDraft = z.infer<typeof collectionDraftSchema>;
export const collectionDraftsSchema = z.array(collectionDraftSchema);

export const productSkeletonSchema = z.object({
  title: z.string().min(1),
  handle: handleSchema,
  price: priceSchema,
  collection_handle: handleSchema,
});
export type ProductSkeleton = z.infer<typeof productSkeletonSchema>;
export const productSkeletonsSchema = z.array(productSkeletonSchema);

export const variantDraftSchema = z.object({
  title: z.string().min(1),
  sku: z.string().nullable(),
  price: priceSchema,
  compare_at_price: priceSchema.nullable(),
  available: z.boolean(),
  option1: z.string().nullable(),
  option2: z.string().nullable(),
  option3: z.string().nullable(),
  position: z.number().int().min(1),
  requires_shipping: z.boolean(),
});

export const productDetailSchema = z.object({
  handle: z.string().min(1),
  description_html: z.string().min(1).max(1500),
  vendor: z.string().min(1),
  product_type: z.string().min(1),
  tags: z.array(z.string().min(1)).min(1).max(8),
  options: z
    .array(
      z.object({
        name: z.string().min(1),
        position: z.number().int().min(1),
        values: z.array(z.string().min(1)).min(1),
      }),
    )
    .min(1)
    .max(3),
  variants: z.array(variantDraftSchema).min(1).max(12),
});
export type ProductDetail = z.infer<typeof productDetailSchema>;
export const productDetailsSchema = z.array(productDetailSchema);

/** `.shop_gen/stage_cache/details/_manifest.json`. */
export const detailsManifestSchema = z.object({
  collections: z.array(
    z.object({
      handle: z.string(),
      file: z.string(),
      detailsCount: z.number(),
      droppedCount: z.number(),
    }),
  ),
  totalProducts: z.number(),
  totalDropped: z.number(),
});
export type DetailsManifest = z.infer<typeof detailsManifestSchema>;

export const pageDraftSchema = z.object({
  handle: handleSchema,
  title: z.string().min(1),
  body_html: z.string().min(1),
});
export type PageDraft = z.infer<typeof pageDraftSchema>;
export const pageDraftsSchema = z.array(pageDraftSchema);

export const altTextEntriesSchema = z.array(
  z.object({ handle: z.string().min(1), alts: z.array(z.string()) }),
);
/** `.shop_gen/stage_cache/alt_text.json`: handle -> alt per image index. */
export const altTextMapSchema = z.record(z.string(), z.array(z.string()));
export type AltTextMap = z.infer<typeof altTextMapSchema>;

const navigationTypeSchema = z.enum(['COLLECTION', 'PRODUCT', 'PAGE', 'BLOG', 'HTTP']);
const navigationLeafSchema = z.object({
  title: z.string().min(1),
  url: z.string().min(1),
  type: navigationTypeSchema,
  children: z.array(z.never()).max(0),
});
export const navigationItemSchema = z.object({
  title: z.string().min(1),
  url: z.string().min(1),
  type: navigationTypeSchema,
  children: z.array(navigationLeafSchema),
});
export type NavigationItem = z.infer<typeof navigationItemSchema>;
export const navigationDraftSchema = z.object({
  'main-menu': z.array(navigationItemSchema).min(1),
  footer: z.array(navigationItemSchema).min(1),
});
export type NavigationDraft = z.infer<typeof navigationDraftSchema>;

export const commerceDraftSchema = z.object({
  tax_rate: z.number().min(0).max(0.3),
  free_shipping_threshold: priceSchema.nullable(),
  shipping_methods: z
    .array(z.object({ handle: handleSchema, title: z.string().min(1), price: priceSchema }))
    .min(1)
    .max(4),
  payment_methods: z
    .array(z.object({ handle: handleSchema, title: z.string().min(1) }))
    .min(1)
    .max(4),
});
export type CommerceDraft = z.infer<typeof commerceDraftSchema>;

export const personaSchema = z.object({
  first_name: z.string().min(1),
  last_name: z.string().min(1),
  phone: z.string().nullable(),
  accepts_marketing: z.boolean(),
  address: z.object({
    address1: z.string().min(1),
    address2: z.string().nullable(),
    city: z.string().min(1),
    province: z.string().nullable(),
    province_code: z.string().nullable(),
    zip: z.string().min(1),
  }),
});
export type Persona = z.infer<typeof personaSchema>;
export const personasSchema = z.array(personaSchema);

/** `.shop_gen/stage_cache/images_manifest.json`. */
export const imagesManifestSchema = z.object({
  backend: z.string(),
  extension: z.string(),
  imagesPerProduct: z.number(),
  entries: z.array(
    z.object({
      handle: z.string(),
      index: z.number(),
      file: z.string(),
      width: z.number(),
      height: z.number(),
    }),
  ),
});
export type ImagesManifest = z.infer<typeof imagesManifestSchema>;
