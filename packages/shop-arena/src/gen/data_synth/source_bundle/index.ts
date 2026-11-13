/**
 * The Dataset of a shop made from a complete Source bundle, and its hidden
 * `users/` directory.
 *
 * The catalog, the department menu, the Personas, their orders and the
 * Reviews come from the bundle, with every time shifted by the bundle
 * clock. The identity, store, pages, policies and Commerce settings are
 * synthesized from the Shop Manual, as for every shop; the identity takes
 * the bundle currency and the country of the bundle locale. The footer
 * links every page and policy.
 *
 * `users/` sits next to `data/`, so the backend never loads it:
 *
 *   users/profiles.jsonl       the bundle profiles, as they are
 *   users/persona_map.json     bundle user id -> customer id
 *   users/future_events.jsonl  User events at the cutoff or later, each
 *                              with a `shop` block of shifted time and
 *                              shop ids and handles
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { BUNDLE_FILES } from '@shop-gym/core';

import { exists, writeJsonFile, writeTextFile } from '../../io.js';
import { type Dataset, assembleDataset } from '../assemble.js';
import { synthCommerce } from '../commerce.js';
import { synthPages, synthPolicies } from '../content.js';
import type { SynthContext } from '../context.js';
import { synthIdentity } from '../identity.js';
import type { NavigationItem, PageDraft } from '../schemas.js';
import { synthStore } from '../store.js';
import { mapBundleCatalog } from './catalog.js';
import { type BundleHistory, mapBundleHistory } from './history.js';
import { type SourceBundle, readSourceBundle } from './read.js';

export { type BundleClock, bundleClock } from './clock.js';
export type { FutureEvent } from './history.js';
export { sourceBundleInputs } from './read.js';

/** The hidden directory of a bundle shop, next to `data/`. */
export const USERS_DIR = 'users';
export const PROFILES_FILE = 'profiles.jsonl';
export const PERSONA_MAP_FILE = 'persona_map.json';
export const FUTURE_EVENTS_FILE = 'future_events.jsonl';

function footerMenu(pages: readonly PageDraft[], policies: readonly PageDraft[]): NavigationItem[] {
  return [
    ...pages.map((p) => ({ title: p.title, url: `/pages/${p.handle}`, type: 'PAGE' as const })),
    ...policies.map((p) => ({
      title: p.title,
      url: `/policies/${p.handle}`,
      type: 'PAGE' as const,
    })),
  ].map((item) => ({ ...item, children: [] }));
}

async function writeUsers(
  sc: SynthContext,
  bundle: SourceBundle,
  history: BundleHistory,
): Promise<void> {
  const dir = path.join(sc.shopDir, USERS_DIR);
  const profiles = path.join(bundle.dir, BUNDLE_FILES.profiles);
  if (await exists(profiles)) {
    await fs.mkdir(dir, { recursive: true });
    await fs.copyFile(profiles, path.join(dir, PROFILES_FILE));
  } else {
    await writeTextFile(path.join(dir, PROFILES_FILE), '');
  }
  await writeJsonFile(path.join(dir, PERSONA_MAP_FILE), history.personaMap);
  await writeTextFile(
    path.join(dir, FUTURE_EVENTS_FILE),
    history.futureEvents.map((event) => `${JSON.stringify(event)}\n`).join(''),
  );
}

/**
 * Reads the complete bundle in `bundleDir`, writes the catalog images
 * under `data/images/` and the hidden `users/` directory, and returns the
 * Dataset to write under `data/`.
 *
 * @throws BundleValidationError when the bundle is not complete.
 * @throws SynthError when a product has more than three options, or when
 *   the bundle has more modeled users than Persona name pairs.
 */
export async function bundleDataset(sc: SynthContext, bundleDir: string): Promise<Dataset> {
  const bundle = await readSourceBundle(bundleDir);
  const catalog = await mapBundleCatalog(sc, bundle);
  const country = new Intl.Locale(bundle.manifest.locale).region;
  const identity = await synthIdentity(sc, catalog, {
    currency: bundle.manifest.currency,
    ...(country !== undefined ? { country } : {}),
  });
  const store = await synthStore(sc, identity);
  const pages = await synthPages(sc, identity);
  const policies = await synthPolicies(sc, identity);
  const commerce = await synthCommerce(sc, identity, policies);
  const history = mapBundleHistory(bundle, catalog, identity, commerce, sc.log);
  const dataset = assembleDataset({
    identity,
    store,
    pages,
    policies,
    commerce,
    products: catalog.products,
    collections: catalog.collections,
    navigation: { 'main-menu': [...catalog.mainMenu], footer: footerMenu(pages, policies) },
    customers: history.customers,
    orders: history.orders,
    inventory: catalog.inventory,
    reviews: history.reviews,
  });
  await writeUsers(sc, bundle, history);
  return dataset;
}
