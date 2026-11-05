/**
 * Dataset invariants the backend zod schema cannot express: referential
 * integrity between files, the presence of referenced image files, valid
 * Discount codes, and seeded order totals that follow the backend pricing
 * rules.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  type Commerce,
  DEFAULT_COMMERCE,
  type Order,
  computeOrderTotals,
  datasetSchema,
} from '@shop-gym/shop-backend';
import type { z } from 'zod';

import { checkDiscountCodes } from '../discount_codes.js';
import { readJsonFile, readJsonIfExists } from '../io.js';

type Navigation = z.infer<typeof datasetSchema.navigationSchema>;
type NavigationItem = Navigation[string][number];

function flatten(items: readonly NavigationItem[]): NavigationItem[] {
  return items.flatMap((item) => [item, ...flatten(item.children)]);
}

async function fileExists(file: string): Promise<boolean> {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

/**
 * Money fields of `order` that differ from what the backend pricing rules
 * give for its lines, shipping method and Discount code under `commerce`.
 */
function checkOrderTotals(order: Order, commerce: Commerce): string[] {
  const method = commerce.shipping_methods.find((m) => m.handle === order.shipping_method);
  if (method === undefined) {
    return [
      `orders.json: order ${order.id} shipping method ${order.shipping_method} is not in commerce.json`,
    ];
  }
  const totals = computeOrderTotals(order.line_items, method, commerce, order.discount_code);
  const fields: readonly (readonly [string, string | null, string | null])[] = [
    ['subtotal_price', order.subtotal_price, totals.subtotalPrice],
    ['total_shipping_price', order.total_shipping_price, totals.totalShippingPrice],
    ['total_tax', order.total_tax, totals.totalTax],
    ['total_price', order.total_price, totals.totalPrice],
    ['discount_code', order.discount_code, totals.discountCode],
    ['discount_amount', order.discount_amount, totals.discountAmount],
  ];
  return fields
    .filter(([, actual, expected]) => actual !== expected)
    .map(
      ([field, actual, expected]) =>
        `orders.json: order ${order.id} ${field} is ${actual}, the pricing rules give ${expected}`,
    );
}

/**
 * Loads every dataset file under `dataDir` with the backend schema and
 * checks cross-file references. Returns a readable problem per violation;
 * an empty list means the dataset is consistent.
 */
export async function checkDataset(dataDir: string): Promise<string[]> {
  const file = (name: string) => path.join(dataDir, `${name}.json`);
  const problems: string[] = [];
  const load = async <T>(
    name: string,
    schema: z.ZodType<T>,
    required: boolean,
  ): Promise<T | undefined> => {
    try {
      return required
        ? await readJsonFile(file(name), schema)
        : await readJsonIfExists(file(name), schema);
    } catch (err) {
      problems.push(
        `${name}.json: ${err instanceof Error ? err.message.split('\n')[0] : String(err)}`,
      );
      return undefined;
    }
  };
  const store = await load('store', datasetSchema.storeSchema, true);
  const products = await load('products', datasetSchema.productsFileSchema, true);
  const collections = await load('collections', datasetSchema.collectionsFileSchema, true);
  const navigation = await load('navigation', datasetSchema.navigationSchema, true);
  const pages = await load('pages', datasetSchema.pagesFileSchema, true);
  const policies = await load('policies', datasetSchema.policiesFileSchema, true);
  const inventory = await load('inventory', datasetSchema.inventoryFileSchema, false);
  const customers = await load('customers', datasetSchema.customersFileSchema, false);
  const orders = await load('orders', datasetSchema.ordersFileSchema, false);
  const commerce =
    (await load('commerce', datasetSchema.commerceSchema, false)) ?? DEFAULT_COMMERCE;
  if (
    store === undefined ||
    products === undefined ||
    collections === undefined ||
    navigation === undefined
  ) {
    return problems;
  }

  const productHandles = new Set<string>();
  const variantIds = new Set<number>();
  for (const p of products) {
    if (productHandles.has(p.handle)) problems.push(`products.json: duplicate handle ${p.handle}`);
    productHandles.add(p.handle);
    if (p.variants.length === 0) problems.push(`products.json: ${p.handle} has no variants`);
    for (const v of p.variants) {
      if (variantIds.has(v.id))
        problems.push(`products.json: duplicate variant id ${v.id} (${p.handle})`);
      variantIds.add(v.id);
    }
    for (const image of p.images) {
      if (/^https?:\/\//.test(image.src)) continue;
      const rel = image.src.replace(/^\/?images\//, '');
      if (!(await fileExists(path.join(dataDir, 'images', rel)))) {
        problems.push(`products.json: ${p.handle} image ${image.src} not found under data/images/`);
      }
    }
  }
  if (products.length === 0) problems.push('products.json: no products');

  const collectionHandles = new Set<string>();
  for (const c of collections) {
    if (collectionHandles.has(c.handle))
      problems.push(`collections.json: duplicate handle ${c.handle}`);
    collectionHandles.add(c.handle);
    for (const h of c.product_handles) {
      if (!productHandles.has(h))
        problems.push(`collections.json: ${c.handle} lists unknown product ${h}`);
    }
  }

  const pageHandles = new Set([...(pages ?? []), ...(policies ?? [])].map((p) => p.handle));
  for (const [menu, items] of Object.entries(navigation)) {
    for (const item of flatten(items)) {
      const handle =
        item.url
          .split('/')
          .filter((s) => s !== '')
          .at(-1) ?? '';
      const target =
        item.type === 'COLLECTION'
          ? collectionHandles
          : item.type === 'PRODUCT'
            ? productHandles
            : item.type === 'PAGE'
              ? pageHandles
              : undefined;
      if (target !== undefined && !target.has(handle)) {
        problems.push(
          `navigation.json: ${menu} item ${JSON.stringify(item.title)} targets unknown ${item.type} ${item.url}`,
        );
      }
    }
  }
  if (!('main-menu' in navigation)) problems.push('navigation.json: missing main-menu');

  for (const key of Object.keys(inventory ?? {})) {
    if (!variantIds.has(Number(key))) problems.push(`inventory.json: unknown variant id ${key}`);
  }

  problems.push(...checkDiscountCodes(commerce.discount_codes).map((p) => `commerce.json: ${p}`));

  const customerIds = new Set<number>();
  for (const c of customers ?? []) {
    customerIds.add(c.id);
    if (c.default_address_id !== null && !c.addresses.some((a) => a.id === c.default_address_id)) {
      problems.push(
        `customers.json: ${c.email} default_address_id ${c.default_address_id} is not one of its addresses`,
      );
    }
  }
  for (const o of orders ?? []) {
    if (o.customer_id !== null && !customerIds.has(o.customer_id)) {
      problems.push(`orders.json: order ${o.id} references unknown customer ${o.customer_id}`);
    }
    for (const li of o.line_items) {
      if (!variantIds.has(li.variant_id)) {
        problems.push(
          `orders.json: order ${o.id} line ${JSON.stringify(li.title)} references unknown variant ${li.variant_id}`,
        );
      }
    }
    problems.push(...checkOrderTotals(o, commerce));
  }
  return problems;
}
