/**
 * `assemble`: turns the cached drafts into the dataset files under
 * `<shopDir>/data/`, each validated against the backend schema before it
 * is written. Ids are stable hashes of handles so re-assembly never
 * changes them; timestamps are a fixed epoch so the dataset is
 * reproducible byte for byte.
 */

import * as path from 'node:path';

import { datasetSchema } from '@shop-gym/shop-backend';
import type { z } from 'zod';

import { scanBrandLeaks } from '../brands/allowlist.js';
import { writeJsonFile } from '../io.js';
import { SynthError } from '../llm.js';
import type { SynthContext } from './context.js';
import { stableId } from './ids.js';
import { imageFileName } from './images/step.js';
import { type Order, synthOrders } from './orders.js';
import type {
  AltTextMap,
  CollectionDraft,
  CommerceDraft,
  Identity,
  ImagesManifest,
  NavigationDraft,
  PageDraft,
  Persona,
  ProductDetail,
  ProductSkeleton,
  StoreDraft,
} from './schemas.js';

export const TIMESTAMP = '2024-01-01T00:00:00Z';
const MAX_STOCK = 50;

type Product = z.infer<typeof datasetSchema.productSchema>;
type Collection = z.infer<typeof datasetSchema.collectionSchema>;
type Customer = z.infer<typeof datasetSchema.customerSchema>;
type Inventory = z.infer<typeof datasetSchema.inventoryFileSchema>;

export interface Drafts {
  readonly identity: Identity;
  readonly store: StoreDraft;
  readonly pages: readonly PageDraft[];
  readonly policies: readonly PageDraft[];
  readonly commerce: CommerceDraft;
  readonly collections: readonly CollectionDraft[];
  readonly skeletons: readonly ProductSkeleton[];
  readonly details: ReadonlyMap<string, ProductDetail>;
  readonly altText: AltTextMap;
  readonly images: ImagesManifest;
  readonly navigation: NavigationDraft;
  readonly personas: readonly Persona[];
}

export interface Dataset {
  readonly store: z.infer<typeof datasetSchema.storeSchema>;
  readonly products: readonly Product[];
  readonly collections: readonly Collection[];
  readonly navigation: z.infer<typeof datasetSchema.navigationSchema>;
  readonly pages: readonly PageDraft[];
  readonly policies: readonly PageDraft[];
  readonly inventory: Inventory;
  readonly customers: readonly Customer[];
  readonly orders: readonly Order[];
  readonly commerce: z.infer<typeof datasetSchema.commerceSchema>;
}

function buildProduct(
  skeleton: ProductSkeleton,
  detail: ProductDetail,
  alts: readonly string[],
  images: ImagesManifest,
): Product {
  const files = images.entries
    .filter((e) => e.handle === skeleton.handle)
    .sort((a, b) => a.index - b.index);
  return {
    id: stableId('product', skeleton.handle),
    title: skeleton.title,
    handle: skeleton.handle,
    description_html: detail.description_html,
    vendor: detail.vendor,
    product_type: detail.product_type,
    tags: detail.tags,
    published_at: TIMESTAMP,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    options: detail.options,
    variants: detail.variants.map((v) => ({
      ...v,
      id: stableId('variant', `${skeleton.handle}/${v.position}`),
    })),
    images: files.map((e) => ({
      id: stableId('image', `${skeleton.handle}/${e.index}`),
      src: imageFileName(skeleton.handle, e.index, images.extension),
      alt: alts[e.index] ?? null,
      width: e.width,
      height: e.height,
      position: e.index + 1,
    })),
  };
}

function regionName(code: string): string {
  return new Intl.DisplayNames(['en'], { type: 'region' }).of(code) ?? code;
}

function buildCustomer(persona: Persona, country: string): Customer {
  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '');
  const email = `${slug(persona.first_name)}.${slug(persona.last_name)}@example.com`;
  const address = {
    id: stableId('address', email),
    first_name: persona.first_name,
    last_name: persona.last_name,
    company: null,
    ...persona.address,
    country: regionName(country),
    country_code: country,
    phone: persona.phone,
  };
  return {
    id: stableId('customer', email),
    email,
    password: `pw-${stableId('password', email).toString(36)}`,
    first_name: persona.first_name,
    last_name: persona.last_name,
    phone: persona.phone,
    accepts_marketing: persona.accepts_marketing,
    created_at: TIMESTAMP,
    addresses: [address],
    default_address_id: address.id,
  };
}

/** Pure assembly of the dataset from drafts; throws `SynthError` when a file would not validate. */
export function assembleDataset(d: Drafts): Dataset {
  const products = d.skeletons.flatMap((s) => {
    const detail = d.details.get(s.handle);
    return detail === undefined
      ? []
      : [buildProduct(s, detail, d.altText[s.handle] ?? [], d.images)];
  });
  const kept = new Set(products.map((p) => p.handle));
  const collections: Collection[] = d.collections.map((c) => ({
    id: stableId('collection', c.handle),
    title: c.title,
    handle: c.handle,
    description: c.description,
    description_html: `<p>${c.description}</p>`,
    image: null,
    published_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    sort_order: c.sort_order,
    product_handles: d.skeletons
      .filter((s) => s.collection_handle === c.handle && kept.has(s.handle))
      .map((s) => s.handle),
  }));
  const inventory: Record<string, { quantity_available: number }> = {};
  for (const p of products) {
    for (const v of p.variants) {
      inventory[String(v.id)] = {
        quantity_available: v.available ? (stableId('stock', String(v.id)) % MAX_STOCK) + 1 : 0,
      };
    }
  }
  const customers = d.personas.map((p) => buildCustomer(p, d.identity.country));
  const commerce = { ...d.commerce };
  const store = {
    shop_id: stableId('shop', d.identity.name),
    name: d.identity.name,
    domain: d.store.domain,
    description: d.store.description,
    currency_code: d.identity.currency,
    country_code: d.identity.country,
    payment_settings: d.store.payment_settings,
    brand: d.store.brand,
  };
  const dataset = {
    store,
    products,
    collections,
    navigation: d.navigation,
    pages: d.pages,
    policies: d.policies,
    inventory,
    customers,
    orders: synthOrders(customers, products, commerce, d.identity.currency),
    commerce,
  };
  const checks = {
    store: datasetSchema.storeSchema.safeParse(dataset.store),
    products: datasetSchema.productsFileSchema.safeParse(dataset.products),
    collections: datasetSchema.collectionsFileSchema.safeParse(dataset.collections),
    navigation: datasetSchema.navigationSchema.safeParse(dataset.navigation),
    pages: datasetSchema.pagesFileSchema.safeParse(dataset.pages),
    policies: datasetSchema.policiesFileSchema.safeParse(dataset.policies),
    inventory: datasetSchema.inventoryFileSchema.safeParse(dataset.inventory),
    customers: datasetSchema.customersFileSchema.safeParse(dataset.customers),
    orders: datasetSchema.ordersFileSchema.safeParse(dataset.orders),
    commerce: datasetSchema.commerceSchema.safeParse(dataset.commerce),
  };
  const bad = Object.entries(checks).filter(([, r]) => !r.success);
  if (bad.length > 0) {
    throw new SynthError(
      `assembled dataset fails the backend schema: ${bad.map(([name, r]) => `${name}: ${r.error?.message}`).join('; ')}`,
    );
  }
  return dataset;
}

export const DATASET_FILES = [
  'store',
  'products',
  'collections',
  'navigation',
  'pages',
  'policies',
  'inventory',
  'customers',
  'orders',
  'commerce',
] as const satisfies readonly (keyof Dataset)[];

export async function writeDataset(sc: SynthContext, dataset: Dataset): Promise<void> {
  for (const name of DATASET_FILES) {
    await writeJsonFile(path.join(sc.dataDir, `${name}.json`), dataset[name]);
  }
  const prose = [
    ...dataset.products.flatMap((p) => [p.title, p.description_html, ...p.tags]),
    ...dataset.collections.flatMap((c) => [c.title, c.description ?? '']),
    ...[...dataset.pages, ...dataset.policies].flatMap((p) => [p.title, p.body_html]),
    dataset.store.description,
  ];
  const hits = prose.flatMap((text) => scanBrandLeaks(text, sc.allowlist));
  if (hits.length > 0) {
    const tokens = [...new Set(hits.map((h) => h.token))].sort();
    sc.log(
      `[data_synth] brand scan: ${hits.length} capitalised tokens outside the allowlist (${tokens.slice(0, 20).join(', ')})`,
    );
  }
}
