/**
 * Task id -> page buckets -> concrete storefront routes.
 *
 * Layer 1 is the static `TASK_BUCKETS` table; layer 2 reads the dataset
 * (`collections.json`, `products.json`, `pages.json`, `policies.json`) so
 * routes carry real handles. Sampling is deterministic (first N entries in
 * file order) and capped per bucket, so reruns judge the same evidence.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { isBackendTask } from './tasks.js';

export type PageBucket =
  | 'homepage'
  | 'navigation'
  | 'collections'
  | 'product'
  | 'cart_search'
  | 'info_pages';

export const ALL_BUCKETS: readonly PageBucket[] = [
  'homepage',
  'navigation',
  'collections',
  'product',
  'cart_search',
  'info_pages',
];

/**
 * Task id -> page buckets. `gen_theme` has no bucket: it only lays down
 * tokens and styles, so its pages are judged once the page tasks fill them.
 */
export const TASK_BUCKETS: Readonly<Record<string, readonly PageBucket[]>> = {
  gen_homepage: ['homepage'],
  gen_navigation: ['navigation'],
  gen_collections: ['collections'],
  gen_product: ['product'],
  gen_cart_search: ['cart_search'],
  gen_info_pages: ['info_pages'],
  visual_fix: ALL_BUCKETS,
};

export interface BucketCaps {
  readonly maxCollections: number;
  readonly productsPerCollection: number;
  readonly maxPages: number;
}

/** Tight caps for the per-iteration visual judge. */
export const DEFAULT_CAPS: BucketCaps = {
  maxCollections: 1,
  productsPerCollection: 1,
  maxPages: 1,
};
/** Wider caps for HTTP-only checks and the final sweep. */
export const SWEEP_CAPS: BucketCaps = { maxCollections: 8, productsPerCollection: 1, maxPages: 6 };

/** Handles the route resolvers need, read once per verifier run. */
export interface DatasetHandles {
  readonly collections: readonly {
    readonly handle: string;
    readonly productHandles: readonly string[];
  }[];
  readonly products: readonly { readonly handle: string; readonly title: string }[];
  readonly pages: readonly string[];
  readonly policies: readonly string[];
}

/** Every task that is not a backend task edits the storefront. */
export function isStorefrontTask(taskId: string): boolean {
  return !isBackendTask(taskId);
}

/** Buckets for a task; empty for tasks outside the table. */
export function bucketsForTask(taskId: string): readonly PageBucket[] {
  return TASK_BUCKETS[taskId] ?? [];
}

/** Read the handle lists from the dataset directory. */
export async function readDatasetHandles(dataDir: string): Promise<DatasetHandles> {
  const [collections, products, pages, policies] = await Promise.all([
    readJsonArray(path.join(dataDir, 'collections.json')),
    readJsonArray(path.join(dataDir, 'products.json')),
    readJsonArray(path.join(dataDir, 'pages.json')),
    readJsonArray(path.join(dataDir, 'policies.json')),
  ]);
  return {
    collections: collections.map((c) => ({
      handle: stringField(c, 'handle'),
      productHandles: stringArrayField(c, 'product_handles'),
    })),
    products: products.map((p) => ({
      handle: stringField(p, 'handle'),
      title: stringField(p, 'title'),
    })),
    pages: pages.map((p) => stringField(p, 'handle')),
    policies: policies.map((p) => stringField(p, 'handle')),
  };
}

/** Routes for one bucket, in deterministic dataset order. */
export function bucketRoutes(
  bucket: PageBucket,
  handles: DatasetHandles,
  caps: BucketCaps = DEFAULT_CAPS,
): string[] {
  switch (bucket) {
    case 'homepage':
      return ['/'];
    case 'navigation':
      return ['/', '/collections'];
    case 'collections':
      return [
        '/collections',
        ...handles.collections.slice(0, caps.maxCollections).map((c) => `/collections/${c.handle}`),
      ];
    case 'product':
      return sampleProductHandles(handles, caps).map((h) => `/products/${h}`);
    case 'cart_search':
      return ['/cart', `/search?q=${encodeURIComponent(searchToken(handles))}`];
    case 'info_pages':
      return [
        ...handles.pages.slice(0, caps.maxPages).map((h) => `/pages/${h}`),
        ...handles.policies.slice(0, caps.maxPages).map((h) => `/policies/${h}`),
      ];
  }
}

/** Union of routes over `buckets`, deduplicated, in first-seen order. */
export function routesForBuckets(
  buckets: readonly PageBucket[],
  handles: DatasetHandles,
  caps: BucketCaps = DEFAULT_CAPS,
): string[] {
  return [...new Set(buckets.flatMap((bucket) => bucketRoutes(bucket, handles, caps)))];
}

/** First N product handles per sampled collection; falls back to `products.json`. */
export function sampleProductHandles(handles: DatasetHandles, caps: BucketCaps): string[] {
  const fromCollections = handles.collections
    .slice(0, caps.maxCollections)
    .flatMap((c) => c.productHandles.slice(0, caps.productsPerCollection));
  const sampled =
    fromCollections.length > 0 ? fromCollections : handles.products.map((p) => p.handle);
  return [...new Set(sampled)].slice(0, caps.maxCollections * caps.productsPerCollection);
}

/** The first word of the first product title, or `shop` for an empty catalog. */
export function searchToken(handles: DatasetHandles): string {
  const title = handles.products[0]?.title ?? '';
  return title.split(/\s+/).find((word) => word.length > 0) ?? 'shop';
}

async function readJsonArray(file: string): Promise<Record<string, unknown>[]> {
  const parsed: unknown = JSON.parse(await fs.readFile(file, 'utf-8'));
  if (!Array.isArray(parsed)) {
    throw new Error(`${file}: expected a JSON array`);
  }
  return parsed.filter(
    (item): item is Record<string, unknown> => typeof item === 'object' && item !== null,
  );
}

function stringField(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value : '';
}

function stringArrayField(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}
