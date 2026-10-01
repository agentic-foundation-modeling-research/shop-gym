/**
 * `data_synth` step: Shop Manual -> SandboxShop dataset.
 *
 * Sub-steps run in order and each one caches its draft under
 * `<shopDir>/.shop_gen/stage_cache/` (`identity.json` sits at the shop
 * root), so an interrupted run resumes at the first missing draft:
 *
 *   identity -> store -> pages -> policies -> commerce -> collections
 *   -> skeletons -> details (per collection) -> alt_text -> images
 *   -> navigation -> customers -> assemble (incl. orders, inventory)
 */

import type { Step, StepContext } from '@shop-gym/core';

import type { GenContext } from '../context.js';
import { synthAltText } from './alt_text.js';
import { assembleDataset, writeDataset } from './assemble.js';
import { synthCollections, synthSkeletons } from './catalog.js';
import { synthCommerce } from './commerce.js';
import { synthPages, synthPolicies } from './content.js';
import { IDENTITY_FILE, STAGE_CACHE_DIR, createSynthContext } from './context.js';
import { synthCustomers } from './customers.js';
import { synthDetails } from './details.js';
import { synthIdentity } from './identity.js';
import { synthImages } from './images/step.js';
import { synthNavigation } from './navigation.js';
import { synthStore } from './store.js';

export { assembleDataset, type Dataset, type Drafts, writeDataset } from './assemble.js';
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

export const DATA_DIR = 'data';

export async function runDataSynth(ctx: StepContext<GenContext>): Promise<void> {
  const sc = createSynthContext(ctx);
  const identity = await synthIdentity(sc);
  const store = await synthStore(sc, identity);
  const pages = await synthPages(sc, identity);
  const policies = await synthPolicies(sc, identity);
  const commerce = await synthCommerce(sc, identity, policies);
  const collections = await synthCollections(sc, identity);
  const skeletons = await synthSkeletons(sc, collections);
  const details = await synthDetails(sc, identity, collections, skeletons);
  const altText = await synthAltText(sc, collections, skeletons, details);
  const images = await synthImages(sc, collections, skeletons, details);
  const navigation = await synthNavigation(sc, collections, pages, policies);
  const personas = await synthCustomers(sc, identity);
  const dataset = assembleDataset({
    identity,
    store,
    pages,
    policies,
    commerce,
    collections,
    skeletons,
    details,
    altText,
    images,
    navigation,
    personas,
  });
  await writeDataset(sc, dataset);
  ctx.log(
    `[data_synth] wrote ${dataset.products.length} products, ${dataset.collections.length} collections, ${dataset.customers.length} customers, ${dataset.orders.length} orders`,
  );
}

export function dataSynthStep(): Step<GenContext> {
  return {
    id: 'data_synth',
    inputs: ['manual'],
    outputs: [DATA_DIR, IDENTITY_FILE, STAGE_CACHE_DIR],
    run: runDataSynth,
  };
}
