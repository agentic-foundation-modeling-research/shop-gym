/**
 * SandboxShop dataset loader.
 *
 * `loadShopData(dir)` reads the required + optional dataset files from `dir`,
 * validates each one against the zod schemas in `./schema.ts`, builds the
 * `productsByHandle`, `variantsByGid` and `inventoryByVariantId` indices the
 * resolvers depend on, and returns a frozen `SandboxShopData` snapshot.
 *
 * Required files: `store.json`, `products.json`, `collections.json`,
 * `navigation.json`, `pages.json`, `policies.json`.
 *
 * Optional files: `blogs.json` (defaults to `[]`), `metafields.json` (defaults
 * to `{ shop: [], products: {}, collections: {} }`), `inventory.json`
 * (defaults to `{}`), `customers.json` (defaults to `[]`), `orders.json`
 * (defaults to `[]`), `commerce.json` (defaults to `DEFAULT_COMMERCE`),
 * `reviews.json` (defaults to `[]`).
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

import type { z } from 'zod';

import {
  blogsFileSchema,
  collectionsFileSchema,
  commerceSchema,
  customersFileSchema,
  inventoryFileSchema,
  metafieldsFileSchema,
  navigationSchema,
  ordersFileSchema,
  pagesFileSchema,
  policiesFileSchema,
  productsFileSchema,
  reviewsFileSchema,
  storeSchema,
} from './schema.js';
import type {
  Commerce,
  InventoryEntry,
  InventoryFile,
  Product,
  Review,
  SandboxShopData,
  VariantLookup,
} from './types.js';

/**
 * Checkout rules used when `commerce.json` is absent: no tax, one free
 * shipping method, one payment method. Keeps v1.0 datasets checkout-capable.
 */
export const DEFAULT_COMMERCE: Commerce = Object.freeze({
  tax_rate: 0,
  free_shipping_threshold: null,
  shipping_methods: [{ handle: 'standard', title: 'Standard Shipping', price: '0.00' }],
  payment_methods: [{ handle: 'card', title: 'Credit card' }],
  discount_codes: [],
});

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
  /** JSONPath-style pointer to the offending value, e.g. `$.variants[2].price`. */
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

/**
 * Load and validate a SandboxShop dataset.
 *
 * @param dir Absolute or relative path to the dataset directory.
 * @returns Frozen `SandboxShopData` with lookup indices populated.
 * @throws {MissingDatasetFileError} A required file is absent.
 * @throws {InvalidDatasetError} A file fails to parse or fails schema validation.
 */
export function loadShopData(dir: string): SandboxShopData {
  const store = readRequired(dir, 'store.json', storeSchema);
  const products = readRequired(dir, 'products.json', productsFileSchema);
  const collections = readRequired(dir, 'collections.json', collectionsFileSchema);
  const navigation = readRequired(dir, 'navigation.json', navigationSchema);
  const pages = readRequired(dir, 'pages.json', pagesFileSchema);
  const policies = readRequired(dir, 'policies.json', policiesFileSchema);

  const blogs = readOptional(dir, 'blogs.json', blogsFileSchema) ?? [];
  const metafields = readOptional(dir, 'metafields.json', metafieldsFileSchema) ?? {
    shop: [],
    products: {},
    collections: {},
  };
  const inventory = readOptional(dir, 'inventory.json', inventoryFileSchema) ?? {};
  const customers = readOptional(dir, 'customers.json', customersFileSchema) ?? [];
  const orders = readOptional(dir, 'orders.json', ordersFileSchema) ?? [];
  const commerce = readOptional(dir, 'commerce.json', commerceSchema) ?? DEFAULT_COMMERCE;
  const reviews = readOptional(dir, 'reviews.json', reviewsFileSchema) ?? [];

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
    customers,
    orders,
    commerce,
    reviews,
    productsByHandle: buildProductsByHandle(products),
    variantsByGid: buildVariantsByGid(products),
    inventoryByVariantId: buildInventoryByVariantId(inventory),
    reviewsByProductHandle: buildReviewsByProductHandle(reviews),
  };
  return Object.freeze(data);
}

// ── File IO ────────────────────────────────────────────────────────────────

function readRequired<T>(dir: string, fileName: string, schema: z.ZodType<T>): T {
  const fullPath = path.join(dir, fileName);
  if (!fs.existsSync(fullPath)) {
    throw new MissingDatasetFileError(fileName, fullPath);
  }
  return validate(fileName, schema, parseJson(fileName, fullPath));
}

function readOptional<T>(dir: string, fileName: string, schema: z.ZodType<T>): T | null {
  const fullPath = path.join(dir, fileName);
  if (!fs.existsSync(fullPath)) {
    return null;
  }
  return validate(fileName, schema, parseJson(fileName, fullPath));
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

function validate<T>(fileName: string, schema: z.ZodType<T>, raw: unknown): T {
  const result = schema.safeParse(raw);
  if (result.success) {
    return result.data;
  }
  // Report the first issue only: the error is meant to be fixed at the source
  // dataset, and one precise pointer is more actionable than a flood.
  const issue = result.error.issues[0];
  if (issue === undefined) {
    throw new InvalidDatasetError(fileName, '$', 'schema validation failed');
  }
  throw new InvalidDatasetError(fileName, formatPath(issue.path), issue.message);
}

/** Render a zod issue path as `$.a[0].b`, matching the pointer style in error messages. */
function formatPath(segments: ReadonlyArray<PropertyKey>): string {
  let out = '$';
  for (const segment of segments) {
    out += typeof segment === 'number' ? `[${segment}]` : `.${String(segment)}`;
  }
  return out;
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

function buildInventoryByVariantId(inventory: InventoryFile): ReadonlyMap<number, InventoryEntry> {
  const map = new Map<number, InventoryEntry>();
  for (const [variantId, entry] of Object.entries(inventory)) {
    map.set(Number.parseInt(variantId, 10), entry);
  }
  return map;
}

function buildReviewsByProductHandle(
  reviews: readonly Review[],
): ReadonlyMap<string, readonly Review[]> {
  const map = new Map<string, Review[]>();
  for (const review of reviews) {
    const list = map.get(review.product_handle);
    if (list === undefined) {
      map.set(review.product_handle, [review]);
    } else {
      list.push(review);
    }
  }
  return map;
}
