/**
 * SandboxShop dataset loader.
 *
 * `loadShopData(dir)` reads the required + optional dataset files from `dir`,
 * validates each one against the v0.1 schema (`docs/specs/shop_backend/storefront_api.md`
 * §8.1) with hand-rolled type guards, builds the `productsByHandle` and
 * `variantsByGid` indices the resolvers depend on, and returns a frozen
 * `SandboxShopData` snapshot.
 *
 * Required files: `store.json`, `products.json`, `collections.json`,
 * `navigation.json`, `pages.json`, `policies.json`.
 *
 * Optional files: `blogs.json` (defaults to `[]`), `metafields.json` (defaults
 * to `{ shop: [], products: {}, collections: {} }`), `inventory.json` (since
 * v0.2; defaults to `{}`).
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

import type {
  Article,
  Blog,
  Collection,
  InventoryEntry,
  InventoryFile,
  Metafield,
  MetafieldsFile,
  Navigation,
  NavigationItem,
  NavigationItemType,
  Page,
  Policy,
  Product,
  ProductImage,
  ProductOption,
  ProductVariant,
  SandboxShopData,
  Store,
  StoreBrand,
  StoreBrandColors,
  StorePaymentSettings,
  VariantLookup,
} from './types.js';

/** Thrown when a required dataset file is not present in the directory. */
export class MissingDatasetFileError extends Error {
  readonly fileName: string;
  readonly fullPath: string;

  constructor(fileName: string, fullPath: string) {
    super(`Missing required dataset file '${fileName}' (looked at ${fullPath})`);
    this.name = 'MissingDatasetFileError';
    this.fileName = fileName;
    this.fullPath = fullPath;
  }
}

/** Thrown when a dataset file is malformed JSON or fails schema validation. */
export class InvalidDatasetError extends Error {
  readonly fileName: string;
  readonly path: string;
  readonly reason: string;

  constructor(fileName: string, dataPath: string, reason: string) {
    super(`Invalid dataset (${fileName} at ${dataPath}): ${reason}`);
    this.name = 'InvalidDatasetError';
    this.fileName = fileName;
    this.path = dataPath;
    this.reason = reason;
  }
}

const REQUIRED_FILES = {
  store: 'store.json',
  products: 'products.json',
  collections: 'collections.json',
  navigation: 'navigation.json',
  pages: 'pages.json',
  policies: 'policies.json',
} as const;

const OPTIONAL_FILES = {
  blogs: 'blogs.json',
  metafields: 'metafields.json',
  inventory: 'inventory.json',
} as const;

const NAVIGATION_TYPES: ReadonlySet<NavigationItemType> = new Set([
  'COLLECTION',
  'PRODUCT',
  'PAGE',
  'BLOG',
  'HTTP',
]);

/**
 * Load and validate a SandboxShop dataset.
 *
 * @param dir Absolute or relative path to the dataset directory.
 * @returns Frozen `SandboxShopData` with `productsByHandle` and `variantsByGid` indices.
 * @throws {MissingDatasetFileError} A required file is absent.
 * @throws {InvalidDatasetError} A file fails to parse or fails schema validation.
 */
export function loadShopData(dir: string): SandboxShopData {
  const store = validateStore(REQUIRED_FILES.store, readRequired(dir, REQUIRED_FILES.store));
  const products = validateProducts(
    REQUIRED_FILES.products,
    readRequired(dir, REQUIRED_FILES.products),
  );
  const collections = validateCollections(
    REQUIRED_FILES.collections,
    readRequired(dir, REQUIRED_FILES.collections),
  );
  const navigation = validateNavigation(
    REQUIRED_FILES.navigation,
    readRequired(dir, REQUIRED_FILES.navigation),
  );
  const pages = validatePages(REQUIRED_FILES.pages, readRequired(dir, REQUIRED_FILES.pages));
  const policies = validatePolicies(
    REQUIRED_FILES.policies,
    readRequired(dir, REQUIRED_FILES.policies),
  );

  const blogsRaw = readOptional(dir, OPTIONAL_FILES.blogs);
  const blogs = blogsRaw === null ? [] : validateBlogs(OPTIONAL_FILES.blogs, blogsRaw);

  const metafieldsRaw = readOptional(dir, OPTIONAL_FILES.metafields);
  const metafields =
    metafieldsRaw === null
      ? defaultMetafields()
      : validateMetafields(OPTIONAL_FILES.metafields, metafieldsRaw);

  const inventoryRaw = readOptional(dir, OPTIONAL_FILES.inventory);
  const inventory =
    inventoryRaw === null ? {} : validateInventory(OPTIONAL_FILES.inventory, inventoryRaw);

  const productsByHandle = buildProductsByHandle(products);
  const variantsByGid = buildVariantsByGid(products);
  const inventoryByVariantId = buildInventoryByVariantId(OPTIONAL_FILES.inventory, inventory);

  const data: SandboxShopData = {
    store,
    products,
    collections,
    navigation,
    pages,
    policies,
    blogs,
    metafields,
    inventory,
    productsByHandle,
    variantsByGid,
    inventoryByVariantId,
  };
  return Object.freeze(data);
}

// ── File IO ────────────────────────────────────────────────────────────────

function readRequired(dir: string, fileName: string): unknown {
  const fullPath = path.join(dir, fileName);
  if (!fs.existsSync(fullPath)) {
    throw new MissingDatasetFileError(fileName, fullPath);
  }
  return parseJson(fileName, fullPath);
}

function readOptional(dir: string, fileName: string): unknown | null {
  const fullPath = path.join(dir, fileName);
  if (!fs.existsSync(fullPath)) {
    return null;
  }
  return parseJson(fileName, fullPath);
}

function parseJson(fileName: string, fullPath: string): unknown {
  const text = fs.readFileSync(fullPath, 'utf-8');
  try {
    return JSON.parse(text) as unknown;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new InvalidDatasetError(fileName, '$', `JSON parse error: ${message}`);
  }
}

// ── Type-guard primitives ──────────────────────────────────────────────────

function typeName(value: unknown): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return typeof value;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function expectString(file: string, p: string, v: unknown): string {
  if (typeof v !== 'string') {
    throw new InvalidDatasetError(file, p, `expected string, got ${typeName(v)}`);
  }
  return v;
}

function expectNumber(file: string, p: string, v: unknown): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) {
    throw new InvalidDatasetError(file, p, `expected finite number, got ${typeName(v)}`);
  }
  return v;
}

function expectBoolean(file: string, p: string, v: unknown): boolean {
  if (typeof v !== 'boolean') {
    throw new InvalidDatasetError(file, p, `expected boolean, got ${typeName(v)}`);
  }
  return v;
}

function expectStringOrNull(file: string, p: string, v: unknown): string | null {
  if (v === null) return null;
  if (typeof v !== 'string') {
    throw new InvalidDatasetError(file, p, `expected string|null, got ${typeName(v)}`);
  }
  return v;
}

function expectObject(file: string, p: string, v: unknown): Record<string, unknown> {
  if (!isPlainObject(v)) {
    throw new InvalidDatasetError(file, p, `expected object, got ${typeName(v)}`);
  }
  return v;
}

function expectArray(file: string, p: string, v: unknown): unknown[] {
  if (!Array.isArray(v)) {
    throw new InvalidDatasetError(file, p, `expected array, got ${typeName(v)}`);
  }
  return v;
}

function expectStringArray(file: string, p: string, v: unknown): string[] {
  return expectArray(file, p, v).map((item, i) => expectString(file, `${p}[${i}]`, item));
}

// ── Per-file validators ────────────────────────────────────────────────────

function validateStore(file: string, raw: unknown): Store {
  const obj = expectObject(file, '$', raw);
  const base = {
    shop_id: expectNumber(file, '$.shop_id', obj.shop_id),
    name: expectString(file, '$.name', obj.name),
    domain: expectString(file, '$.domain', obj.domain),
    description: expectString(file, '$.description', obj.description),
    currency_code: expectString(file, '$.currency_code', obj.currency_code),
    country_code: expectString(file, '$.country_code', obj.country_code),
    payment_settings: validatePaymentSettings(file, '$.payment_settings', obj.payment_settings),
    brand: validateBrand(file, '$.brand', obj.brand),
  };
  // Treat both ``undefined`` (key absent) and ``null`` (key present, no
  // value) as "not provided". Some producers — notably the shop_arena
  // pydantic dump — serialise unset optional fields as JSON ``null``.
  if (obj.dataset_version === undefined || obj.dataset_version === null) {
    return base;
  }
  return {
    ...base,
    dataset_version: expectString(file, '$.dataset_version', obj.dataset_version),
  };
}

function validatePaymentSettings(file: string, p: string, raw: unknown): StorePaymentSettings {
  const obj = expectObject(file, p, raw);
  return {
    accepted_card_brands: expectStringArray(
      file,
      `${p}.accepted_card_brands`,
      obj.accepted_card_brands,
    ),
  };
}

function validateBrand(file: string, p: string, raw: unknown): StoreBrand {
  const obj = expectObject(file, p, raw);
  return {
    logo_url: expectStringOrNull(file, `${p}.logo_url`, obj.logo_url),
    colors: validateBrandColors(file, `${p}.colors`, obj.colors),
  };
}

function validateBrandColors(file: string, p: string, raw: unknown): StoreBrandColors {
  const obj = expectObject(file, p, raw);
  return {
    primary: expectString(file, `${p}.primary`, obj.primary),
    secondary: expectString(file, `${p}.secondary`, obj.secondary),
  };
}

function validateProducts(file: string, raw: unknown): readonly Product[] {
  return expectArray(file, '$', raw).map((item, i) => validateProduct(file, `$[${i}]`, item));
}

function validateProduct(file: string, p: string, raw: unknown): Product {
  const obj = expectObject(file, p, raw);
  return {
    id: expectNumber(file, `${p}.id`, obj.id),
    title: expectString(file, `${p}.title`, obj.title),
    handle: expectString(file, `${p}.handle`, obj.handle),
    description_html: expectString(file, `${p}.description_html`, obj.description_html),
    vendor: expectString(file, `${p}.vendor`, obj.vendor),
    product_type: expectString(file, `${p}.product_type`, obj.product_type),
    tags: expectStringArray(file, `${p}.tags`, obj.tags),
    published_at: expectString(file, `${p}.published_at`, obj.published_at),
    created_at: expectString(file, `${p}.created_at`, obj.created_at),
    updated_at: expectString(file, `${p}.updated_at`, obj.updated_at),
    options: expectArray(file, `${p}.options`, obj.options).map((v, i) =>
      validateProductOption(file, `${p}.options[${i}]`, v),
    ),
    variants: expectArray(file, `${p}.variants`, obj.variants).map((v, i) =>
      validateProductVariant(file, `${p}.variants[${i}]`, v),
    ),
    images: expectArray(file, `${p}.images`, obj.images).map((v, i) =>
      validateProductImage(file, `${p}.images[${i}]`, v),
    ),
  };
}

function validateProductOption(file: string, p: string, raw: unknown): ProductOption {
  const obj = expectObject(file, p, raw);
  return {
    name: expectString(file, `${p}.name`, obj.name),
    position: expectNumber(file, `${p}.position`, obj.position),
    values: expectStringArray(file, `${p}.values`, obj.values),
  };
}

function validateProductVariant(file: string, p: string, raw: unknown): ProductVariant {
  const obj = expectObject(file, p, raw);
  return {
    id: expectNumber(file, `${p}.id`, obj.id),
    title: expectString(file, `${p}.title`, obj.title),
    sku: expectStringOrNull(file, `${p}.sku`, obj.sku),
    price: expectString(file, `${p}.price`, obj.price),
    compare_at_price: expectStringOrNull(file, `${p}.compare_at_price`, obj.compare_at_price),
    available: expectBoolean(file, `${p}.available`, obj.available),
    option1: expectStringOrNull(file, `${p}.option1`, obj.option1),
    option2: expectStringOrNull(file, `${p}.option2`, obj.option2),
    option3: expectStringOrNull(file, `${p}.option3`, obj.option3),
    position: expectNumber(file, `${p}.position`, obj.position),
    requires_shipping: expectBoolean(file, `${p}.requires_shipping`, obj.requires_shipping),
  };
}

function validateProductImage(file: string, p: string, raw: unknown): ProductImage {
  const obj = expectObject(file, p, raw);
  return {
    id: expectNumber(file, `${p}.id`, obj.id),
    src: expectString(file, `${p}.src`, obj.src),
    alt: expectStringOrNull(file, `${p}.alt`, obj.alt),
    width: expectNumber(file, `${p}.width`, obj.width),
    height: expectNumber(file, `${p}.height`, obj.height),
    position: expectNumber(file, `${p}.position`, obj.position),
  };
}

function validateCollections(file: string, raw: unknown): readonly Collection[] {
  return expectArray(file, '$', raw).map((item, i) => validateCollection(file, `$[${i}]`, item));
}

function validateCollection(file: string, p: string, raw: unknown): Collection {
  const obj = expectObject(file, p, raw);
  const imageRaw = obj.image;
  return {
    id: expectNumber(file, `${p}.id`, obj.id),
    title: expectString(file, `${p}.title`, obj.title),
    handle: expectString(file, `${p}.handle`, obj.handle),
    description: expectStringOrNull(file, `${p}.description`, obj.description),
    description_html: expectStringOrNull(file, `${p}.description_html`, obj.description_html),
    image: imageRaw === null ? null : validateProductImage(file, `${p}.image`, imageRaw),
    published_at: expectStringOrNull(file, `${p}.published_at`, obj.published_at),
    updated_at: expectStringOrNull(file, `${p}.updated_at`, obj.updated_at),
    sort_order: expectStringOrNull(file, `${p}.sort_order`, obj.sort_order),
    product_handles: expectStringArray(file, `${p}.product_handles`, obj.product_handles),
  };
}

function validateNavigation(file: string, raw: unknown): Navigation {
  const obj = expectObject(file, '$', raw);
  const result: Record<string, readonly NavigationItem[]> = {};
  for (const [handle, value] of Object.entries(obj)) {
    const items = expectArray(file, `$.${handle}`, value);
    result[handle] = items.map((v, i) => validateNavigationItem(file, `$.${handle}[${i}]`, v));
  }
  return result;
}

function validateNavigationItem(file: string, p: string, raw: unknown): NavigationItem {
  const obj = expectObject(file, p, raw);
  const type = expectString(file, `${p}.type`, obj.type);
  if (!NAVIGATION_TYPES.has(type as NavigationItemType)) {
    throw new InvalidDatasetError(
      file,
      `${p}.type`,
      `expected one of ${[...NAVIGATION_TYPES].join('|')}, got '${type}'`,
    );
  }
  return {
    title: expectString(file, `${p}.title`, obj.title),
    url: expectString(file, `${p}.url`, obj.url),
    type: type as NavigationItemType,
    children: expectArray(file, `${p}.children`, obj.children).map((v, i) =>
      validateNavigationItem(file, `${p}.children[${i}]`, v),
    ),
  };
}

function validatePages(file: string, raw: unknown): readonly Page[] {
  return expectArray(file, '$', raw).map((item, i) => validatePage(file, `$[${i}]`, item));
}

function validatePage(file: string, p: string, raw: unknown): Page {
  const obj = expectObject(file, p, raw);
  return {
    handle: expectString(file, `${p}.handle`, obj.handle),
    title: expectString(file, `${p}.title`, obj.title),
    body_html: expectString(file, `${p}.body_html`, obj.body_html),
  };
}

function validatePolicies(file: string, raw: unknown): readonly Policy[] {
  return expectArray(file, '$', raw).map((item, i) => validatePolicy(file, `$[${i}]`, item));
}

function validatePolicy(file: string, p: string, raw: unknown): Policy {
  const obj = expectObject(file, p, raw);
  return {
    handle: expectString(file, `${p}.handle`, obj.handle),
    title: expectString(file, `${p}.title`, obj.title),
    body_html: expectString(file, `${p}.body_html`, obj.body_html),
  };
}

function validateBlogs(file: string, raw: unknown): readonly Blog[] {
  return expectArray(file, '$', raw).map((item, i) => validateBlog(file, `$[${i}]`, item));
}

function validateBlog(file: string, p: string, raw: unknown): Blog {
  const obj = expectObject(file, p, raw);
  return {
    handle: expectString(file, `${p}.handle`, obj.handle),
    title: expectString(file, `${p}.title`, obj.title),
    articles: expectArray(file, `${p}.articles`, obj.articles).map((v, i) =>
      validateArticle(file, `${p}.articles[${i}]`, v),
    ),
  };
}

function validateArticle(file: string, p: string, raw: unknown): Article {
  const obj = expectObject(file, p, raw);
  return {
    handle: expectString(file, `${p}.handle`, obj.handle),
    title: expectString(file, `${p}.title`, obj.title),
    content_html: expectString(file, `${p}.content_html`, obj.content_html),
    author: expectStringOrNull(file, `${p}.author`, obj.author),
    published_at: expectStringOrNull(file, `${p}.published_at`, obj.published_at),
  };
}

function validateMetafields(file: string, raw: unknown): MetafieldsFile {
  const obj = expectObject(file, '$', raw);
  return {
    shop: expectArray(file, '$.shop', obj.shop).map((v, i) =>
      validateMetafield(file, `$.shop[${i}]`, v),
    ),
    products: validateMetafieldMap(file, '$.products', obj.products),
    collections: validateMetafieldMap(file, '$.collections', obj.collections),
  };
}

function validateMetafieldMap(
  file: string,
  p: string,
  raw: unknown,
): Readonly<Record<string, readonly Metafield[]>> {
  const obj = expectObject(file, p, raw);
  const result: Record<string, readonly Metafield[]> = {};
  for (const [handle, value] of Object.entries(obj)) {
    const items = expectArray(file, `${p}.${handle}`, value);
    result[handle] = items.map((v, i) => validateMetafield(file, `${p}.${handle}[${i}]`, v));
  }
  return result;
}

function validateMetafield(file: string, p: string, raw: unknown): Metafield {
  const obj = expectObject(file, p, raw);
  return {
    namespace: expectString(file, `${p}.namespace`, obj.namespace),
    key: expectString(file, `${p}.key`, obj.key),
    value: expectString(file, `${p}.value`, obj.value),
    type: expectString(file, `${p}.type`, obj.type),
  };
}

function defaultMetafields(): MetafieldsFile {
  return { shop: [], products: {}, collections: {} };
}

function validateInventory(file: string, raw: unknown): InventoryFile {
  const obj = expectObject(file, '$', raw);
  const result: Record<string, InventoryEntry> = {};
  for (const [variantId, value] of Object.entries(obj)) {
    const entryRaw = expectObject(file, `$.${variantId}`, value);
    const quantity =
      entryRaw.quantity_available === null
        ? null
        : expectNumber(file, `$.${variantId}.quantity_available`, entryRaw.quantity_available);
    result[variantId] = { quantity_available: quantity };
  }
  return result;
}

// ── Indices ────────────────────────────────────────────────────────────────

function buildProductsByHandle(products: readonly Product[]): ReadonlyMap<string, Product> {
  const map = new Map<string, Product>();
  for (const product of products) {
    map.set(product.handle, product);
  }
  return map;
}

function buildVariantsByGid(products: readonly Product[]): ReadonlyMap<string, VariantLookup> {
  const map = new Map<string, VariantLookup>();
  for (const product of products) {
    for (const variant of product.variants) {
      map.set(`gid://shopify/ProductVariant/${variant.id}`, { product, variant });
    }
  }
  return map;
}

function buildInventoryByVariantId(
  file: string,
  inventory: InventoryFile,
): ReadonlyMap<number, InventoryEntry> {
  const map = new Map<number, InventoryEntry>();
  for (const [variantIdStr, entry] of Object.entries(inventory)) {
    const variantId = Number.parseInt(variantIdStr, 10);
    if (!Number.isFinite(variantId) || String(variantId) !== variantIdStr) {
      throw new InvalidDatasetError(
        file,
        `$.${variantIdStr}`,
        `expected variant id key to parse as an integer, got '${variantIdStr}'`,
      );
    }
    map.set(variantId, entry);
  }
  return map;
}
