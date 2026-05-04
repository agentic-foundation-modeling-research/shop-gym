/**
 * SandboxShop dataset schema types (v0.1).
 *
 * Mirrors the on-disk shape produced by ShopArena `shop_gen` and consumed by
 * `shop_backend`. The authoritative description lives in
 * `docs/specs/shop_backend/storefront_api.md` §8.1.
 *
 * Every field is `readonly` — once `loadShopData` returns, the dataset is a
 * frozen snapshot for the lifetime of the server instance.
 */

/** Single object in `store.json`. */
export interface Store {
  readonly shop_id: number;
  readonly name: string;
  readonly domain: string;
  readonly description: string;
  /** ISO 4217 (USD, CAD, EUR, ...). */
  readonly currency_code: string;
  /** ISO 3166-1 alpha-2. */
  readonly country_code: string;
  readonly payment_settings: StorePaymentSettings;
  readonly brand: StoreBrand;
  /** Optional; reserved for future dataset-version gating. */
  readonly dataset_version?: string;
}

export interface StorePaymentSettings {
  /** VISA, MASTER, AMERICAN_EXPRESS, ... */
  readonly accepted_card_brands: readonly string[];
}

export interface StoreBrand {
  readonly logo_url: string | null;
  readonly colors: StoreBrandColors;
}

export interface StoreBrandColors {
  readonly primary: string;
  readonly secondary: string;
}

/** Element of `products.json`. */
export interface Product {
  readonly id: number;
  readonly title: string;
  readonly handle: string;
  readonly description_html: string;
  readonly vendor: string;
  readonly product_type: string;
  readonly tags: readonly string[];
  /** ISO 8601. */
  readonly published_at: string;
  readonly created_at: string;
  readonly updated_at: string;
  readonly options: readonly ProductOption[];
  readonly variants: readonly ProductVariant[];
  readonly images: readonly ProductImage[];
}

export interface ProductOption {
  readonly name: string;
  /** 1-indexed. */
  readonly position: number;
  readonly values: readonly string[];
}

export interface ProductVariant {
  readonly id: number;
  readonly title: string;
  readonly sku: string | null;
  /** Decimal as string, e.g. "12.99". */
  readonly price: string;
  readonly compare_at_price: string | null;
  readonly available: boolean;
  readonly option1: string | null;
  readonly option2: string | null;
  readonly option3: string | null;
  readonly position: number;
  readonly requires_shipping: boolean;
}

export interface ProductImage {
  readonly id: number;
  /** Absolute URL or path under `/images/`. */
  readonly src: string;
  readonly alt: string | null;
  readonly width: number;
  readonly height: number;
  readonly position: number;
}

/** Element of `collections.json`. */
export interface Collection {
  readonly id: number;
  readonly title: string;
  readonly handle: string;
  readonly description: string | null;
  readonly description_html: string | null;
  readonly image: ProductImage | null;
  readonly published_at: string | null;
  readonly updated_at: string | null;
  /** e.g. "manual", "best-selling". */
  readonly sort_order: string | null;
  /** Member product handles. */
  readonly product_handles: readonly string[];
}

/** `navigation.json`: keyed map of menu handle → root nav items. */
export interface Navigation {
  readonly [menuHandle: string]: readonly NavigationItem[];
}

export type NavigationItemType = 'COLLECTION' | 'PRODUCT' | 'PAGE' | 'BLOG' | 'HTTP';

export interface NavigationItem {
  readonly title: string;
  /** Absolute URL or relative path. */
  readonly url: string;
  readonly type: NavigationItemType;
  readonly children: readonly NavigationItem[];
}

/** Element of `pages.json`. */
export interface Page {
  readonly handle: string;
  readonly title: string;
  readonly body_html: string;
}

/** Element of `policies.json`. */
export interface Policy {
  /**
   * privacy-policy | shipping-policy | terms-of-service | refund-policy |
   * subscription-policy.
   */
  readonly handle: string;
  readonly title: string;
  readonly body_html: string;
}

/** Element of `blogs.json`. Optional file; defaults to `[]`. */
export interface Blog {
  readonly handle: string;
  readonly title: string;
  readonly articles: readonly Article[];
}

export interface Article {
  readonly handle: string;
  readonly title: string;
  /** Body. */
  readonly content_html: string;
  /** Resolved as `ArticleAuthor.name`. */
  readonly author: string | null;
  readonly published_at: string | null;
}

/** `metafields.json`. Optional file; defaults to `{ shop: [], products: {}, collections: {} }`. */
export interface MetafieldsFile {
  readonly shop: readonly Metafield[];
  /** Keyed by product handle. */
  readonly products: Readonly<Record<string, readonly Metafield[]>>;
  /** Keyed by collection handle. */
  readonly collections: Readonly<Record<string, readonly Metafield[]>>;
}

export interface Metafield {
  readonly namespace: string;
  readonly key: string;
  readonly value: string;
  /** "single_line_text_field", "json", ... */
  readonly type: string;
}

/** Per-variant inventory entry (since v0.2). */
export interface InventoryEntry {
  /**
   * Stock quantity for this variant. `null` means tracked-but-unknown
   * (returns `null` to GraphQL); a number is read verbatim.
   */
  readonly quantity_available: number | null;
}

/**
 * `inventory.json` (since v0.2). Optional file; defaults to `{}`.
 * Variants without a matching entry are treated as untracked (per spec §5.3).
 */
export interface InventoryFile {
  /** Variant id (numeric) as a string key. */
  readonly [variantId: string]: InventoryEntry;
}

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
  /** `handle` → product. */
  readonly productsByHandle: ReadonlyMap<string, Product>;
  /** `gid://shopgym/ProductVariant/<id>` → owning product + variant. */
  readonly variantsByGid: ReadonlyMap<string, VariantLookup>;
  /** Numeric variant id → inventory entry. Empty when `inventory.json` is absent. */
  readonly inventoryByVariantId: ReadonlyMap<number, InventoryEntry>;
}
