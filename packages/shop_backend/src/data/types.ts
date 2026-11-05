/**
 * SandboxShop dataset types.
 *
 * Inferred from the zod schemas in `./schema.ts`, which are the authoritative
 * description of the on-disk shape produced by ShopArena and consumed by
 * `shop_backend`. Every field is `readonly`: once `loadShopData` returns, the
 * dataset is a frozen snapshot for the lifetime of the server instance.
 */

import type { z } from 'zod';

import type {
  addressSchema,
  articleSchema,
  blogSchema,
  collectionSchema,
  commerceSchema,
  customerSchema,
  discountCodeKindSchema,
  discountCodeSchema,
  inventoryEntrySchema,
  inventoryFileSchema,
  metafieldSchema,
  metafieldsFileSchema,
  navigationItemTypeSchema,
  navigationSchema,
  orderFinancialStatusSchema,
  orderFulfillmentStatusSchema,
  orderLineItemSchema,
  orderSchema,
  pageSchema,
  paymentMethodSchema,
  policySchema,
  productImageSchema,
  productOptionSchema,
  productSchema,
  productVariantSchema,
  reviewSchema,
  shippingMethodSchema,
  storeBrandColorsSchema,
  storeBrandSchema,
  storePaymentSettingsSchema,
  storeSchema,
} from './schema.js';

export type { NavigationItem } from './schema.js';

export type Store = z.infer<typeof storeSchema>;
export type StorePaymentSettings = z.infer<typeof storePaymentSettingsSchema>;
export type StoreBrand = z.infer<typeof storeBrandSchema>;
export type StoreBrandColors = z.infer<typeof storeBrandColorsSchema>;

export type Product = z.infer<typeof productSchema>;
export type ProductOption = z.infer<typeof productOptionSchema>;
export type ProductVariant = z.infer<typeof productVariantSchema>;
export type ProductImage = z.infer<typeof productImageSchema>;

export type Collection = z.infer<typeof collectionSchema>;

export type Navigation = z.infer<typeof navigationSchema>;
export type NavigationItemType = z.infer<typeof navigationItemTypeSchema>;

export type Page = z.infer<typeof pageSchema>;
export type Policy = z.infer<typeof policySchema>;

export type Blog = z.infer<typeof blogSchema>;
export type Article = z.infer<typeof articleSchema>;

export type MetafieldsFile = z.infer<typeof metafieldsFileSchema>;
export type Metafield = z.infer<typeof metafieldSchema>;

export type InventoryFile = z.infer<typeof inventoryFileSchema>;
export type InventoryEntry = z.infer<typeof inventoryEntrySchema>;

export type Address = z.infer<typeof addressSchema>;
export type Customer = z.infer<typeof customerSchema>;

export type Order = z.infer<typeof orderSchema>;
export type OrderLineItem = z.infer<typeof orderLineItemSchema>;
export type OrderFinancialStatus = z.infer<typeof orderFinancialStatusSchema>;
export type OrderFulfillmentStatus = z.infer<typeof orderFulfillmentStatusSchema>;

export type Commerce = z.infer<typeof commerceSchema>;
export type ShippingMethod = z.infer<typeof shippingMethodSchema>;
export type DiscountCode = z.infer<typeof discountCodeSchema>;
export type DiscountCodeKind = z.infer<typeof discountCodeKindSchema>;
export type PaymentMethod = z.infer<typeof paymentMethodSchema>;

export type Review = z.infer<typeof reviewSchema>;

/**
 * Lookup entry for `variantsByGid`: the variant plus the product it belongs to,
 * so cart resolvers can materialize merchandise without a second pass.
 */
export interface VariantLookup {
  readonly product: Product;
  readonly variant: ProductVariant;
}

/**
 * Aggregate of one loaded SandboxShop dataset plus the indices the resolvers
 * need. Returned (frozen) by `loadShopData`.
 */
export interface SandboxShopData {
  readonly store: Store;
  readonly products: readonly Product[];
  readonly collections: readonly Collection[];
  readonly navigation: Navigation;
  readonly pages: readonly Page[];
  readonly policies: readonly Policy[];
  readonly blogs: readonly Blog[];
  readonly metafields: MetafieldsFile;
  readonly inventory: InventoryFile;
  /** Seeded accounts; empty when `customers.json` is absent. */
  readonly customers: readonly Customer[];
  /** Seeded order history; empty when `orders.json` is absent. */
  readonly orders: readonly Order[];
  /** Checkout rules; defaults when `commerce.json` is absent. */
  readonly commerce: Commerce;
  /** Product Reviews in file order; empty when `reviews.json` is absent. */
  readonly reviews: readonly Review[];
  /** `handle` → product. */
  readonly productsByHandle: ReadonlyMap<string, Product>;
  /** `gid://shopify/ProductVariant/<id>` → owning product + variant. */
  readonly variantsByGid: ReadonlyMap<string, VariantLookup>;
  /** Numeric variant id → inventory entry. Empty when `inventory.json` is absent. */
  readonly inventoryByVariantId: ReadonlyMap<number, InventoryEntry>;
  /** Product handle → its Reviews in file order. Products with no Reviews have no entry. */
  readonly reviewsByProductHandle: ReadonlyMap<string, readonly Review[]>;
}
