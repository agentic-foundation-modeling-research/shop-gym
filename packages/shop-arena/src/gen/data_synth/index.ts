/**
 * `data_synth` step: Shop Manual -> SandboxShop dataset.
 *
 * Sub-steps run in order and each one caches its draft under
 * `<shopDir>/.shop_gen/stage_cache/` (`identity.json` sits at the shop
 * root), so an interrupted run resumes at the first missing draft:
 *
 *   identity -> store -> pages -> policies -> commerce -> collections
 *   -> skeletons -> details (per collection) -> alt_text -> images
 *   -> navigation -> customers -> reviews -> assemble (incl. orders,
 *   inventory)
 *
 * With `sourceDataDir`, the catalog of that source Dataset is copied
 * first. It takes the place of `collections` through `images`.
 *
 * With `bundleDir`, the Dataset comes from that complete Source bundle:
 * only identity, store, pages, policies and commerce are synthesized, and
 * the hidden `users/` directory is written next to `data/`.
 */

import * as path from 'node:path';

import type { Step, StepContext } from '@shop-gym/core';

import type { GenContext } from '../context.js';
import { synthAltText } from './alt_text.js';
import {
  type Catalog,
  type Dataset,
  assembleDataset,
  buildCollections,
  buildCustomer,
  buildProducts,
  writeDataset,
} from './assemble.js';
import { synthCollections, synthSkeletons } from './catalog.js';
import { synthCommerce } from './commerce.js';
import { synthPages, synthPolicies } from './content.js';
import {
  IDENTITY_FILE,
  STAGE_CACHE_DIR,
  type SynthContext,
  createSynthContext,
} from './context.js';
import { synthCustomers } from './customers.js';
import { synthDetails } from './details.js';
import { synthIdentity } from './identity.js';
import { synthImages } from './images/step.js';
import { synthNavigation } from './navigation.js';
import { synthReviews } from './reviews.js';
import type { Identity } from './schemas.js';
import { USERS_DIR, bundleDataset, sourceBundleInputs } from './source_bundle/index.js';
import { SOURCE_CATALOG_PATHS, copySourceCatalog } from './source_catalog.js';
import { synthStore } from './store.js';

export {
  assembleDataset,
  buildProducts,
  type Dataset,
  type Drafts,
  writeDataset,
} from './assemble.js';
export {
  IDENTITY_FILE,
  STAGE_CACHE_DIR,
  type SynthContext,
  createSynthContext,
} from './context.js';
export type { ImageBackend, ImageBackendName, ImageRequest } from './images/backend.js';
export { createImageBackend } from './images/backend.js';
export { synthOrders } from './orders.js';
export * from './schemas.js';
export {
  type BundleClock,
  FUTURE_EVENTS_FILE,
  type FutureEvent,
  PERSONA_MAP_FILE,
  PROFILES_FILE,
  USERS_DIR,
  bundleClock,
} from './source_bundle/index.js';

export const DATA_DIR = 'data';

/** The catalog that `collections` through `images` synthesize. */
async function synthCatalog(sc: SynthContext, identity: Identity): Promise<Catalog> {
  const collections = await synthCollections(sc, identity);
  const skeletons = await synthSkeletons(sc, collections);
  const details = await synthDetails(sc, identity, collections, skeletons);
  const altText = await synthAltText(sc, collections, skeletons, details);
  const images = await synthImages(sc, collections, skeletons, details);
  const products = buildProducts(skeletons, details, altText, images);
  return { products, collections: buildCollections(collections, skeletons, products) };
}

/** The Dataset synthesized from the manual, with the catalog of `sourceDataDir` when it is set. */
async function synthDataset(sc: SynthContext, sourceDataDir: string | undefined): Promise<Dataset> {
  const copiedCatalog =
    sourceDataDir === undefined ? undefined : await copySourceCatalog(sc, sourceDataDir);
  const identity = await synthIdentity(sc, copiedCatalog);
  const store = await synthStore(sc, identity);
  const pages = await synthPages(sc, identity);
  const policies = await synthPolicies(sc, identity);
  const commerce = await synthCommerce(sc, identity, policies);
  const catalog = copiedCatalog ?? (await synthCatalog(sc, identity));
  const navigation = await synthNavigation(sc, catalog.collections, pages, policies);
  const personas = await synthCustomers(sc, identity);
  const reviews = await synthReviews(sc, catalog.products);
  return assembleDataset({
    identity,
    store,
    pages,
    policies,
    commerce,
    ...catalog,
    navigation,
    customers: personas.map((p) => buildCustomer(p, identity.country)),
    reviews,
  });
}

export async function runDataSynth(ctx: StepContext<GenContext>): Promise<void> {
  const sc = createSynthContext(ctx);
  const { sourceDataDir, bundleDir } = ctx.context;
  const dataset =
    bundleDir === undefined
      ? await synthDataset(sc, sourceDataDir)
      : await bundleDataset(sc, bundleDir);
  await writeDataset(sc, dataset);
  ctx.log(
    `[data_synth] wrote ${dataset.products.length} products, ${dataset.collections.length} collections, ${dataset.customers.length} customers, ${dataset.orders.length} orders, ${dataset.reviews.length} reviews`,
  );
}

/**
 * @param sourceDataDir The source Dataset whose catalog is copied; its catalog files are inputs too.
 * @param bundleDir The Source bundle the Dataset comes from; its files are inputs too, and
 *   `users/` is an output.
 */
export function dataSynthStep(sourceDataDir?: string, bundleDir?: string): Step<GenContext> {
  return {
    id: 'data_synth',
    inputs: [
      'manual',
      ...(sourceDataDir === undefined
        ? []
        : SOURCE_CATALOG_PATHS.map((name) => path.join(sourceDataDir, name))),
      ...(bundleDir === undefined ? [] : sourceBundleInputs(bundleDir)),
    ],
    outputs: [
      DATA_DIR,
      IDENTITY_FILE,
      STAGE_CACHE_DIR,
      ...(bundleDir === undefined ? [] : [USERS_DIR]),
    ],
    run: runDataSynth,
  };
}
