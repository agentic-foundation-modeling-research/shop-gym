/**
 * The catalog of an existing source Dataset, used in place of a
 * synthesized one. Its products and collections keep the same JSON
 * values, also the fields that the backend schema does not name. Only
 * the collections with no products are dropped. Its `images/` directory
 * is copied as it is. Everything else in the Dataset is synthesized from
 * the Shop Manual.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { datasetSchema } from '@shop-gym/shop-backend';
import type { z } from 'zod';

import { readJsonFile } from '../io.js';
import type { Catalog } from './assemble.js';
import type { SynthContext } from './context.js';
import { IMAGES_DIR } from './images/step.js';

const PRODUCTS_FILE = 'products.json';
const COLLECTIONS_FILE = 'collections.json';

/** What is read from the source Dataset directory. */
export const SOURCE_CATALOG_PATHS = [PRODUCTS_FILE, COLLECTIONS_FILE, IMAGES_DIR] as const;

/**
 * Reads `file`, checks it against `schema`, and returns its JSON value,
 * also the fields that `schema` does not name.
 */
async function readAsWritten<T>(file: string, schema: z.ZodType<T>): Promise<T> {
  await readJsonFile(file, schema);
  // The check passed, and the catalog schemas have no defaults or
  // transforms, so the JSON as written is a `T`.
  return JSON.parse(await fs.readFile(file, 'utf-8')) as T;
}

/**
 * Copies the images of the Dataset in `sourceDataDir` into the shop's
 * `data/images/` and returns its catalog. Each dropped collection is
 * logged.
 */
export async function copySourceCatalog(sc: SynthContext, sourceDataDir: string): Promise<Catalog> {
  const products = await readAsWritten(
    path.join(sourceDataDir, PRODUCTS_FILE),
    datasetSchema.productsFileSchema,
  );
  const collections = await readAsWritten(
    path.join(sourceDataDir, COLLECTIONS_FILE),
    datasetSchema.collectionsFileSchema,
  );
  for (const c of collections) {
    if (c.product_handles.length === 0) {
      sc.log(`[data_synth] source Dataset: dropped collection ${c.handle}, which has no products`);
    }
  }
  await fs.cp(path.join(sourceDataDir, IMAGES_DIR), path.join(sc.dataDir, IMAGES_DIR), {
    recursive: true,
  });
  return { products, collections: collections.filter((c) => c.product_handles.length > 0) };
}
