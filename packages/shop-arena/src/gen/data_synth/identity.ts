/**
 * `synth_identity`: descriptor, tone, currency, country from the manual,
 * and from a summary of the copied catalog with `--data`; name from the
 * allowlist.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { z } from 'zod';

import { pickBrandName } from '../brands/allowlist.js';
import { readJsonFile, readJsonIfExists, writeJsonFile } from '../io.js';
import { completeStructured } from '../llm.js';
import type { Catalog } from './assemble.js';
import { IDENTITY_FILE, type SynthContext, pretty, synthPrompt } from './context.js';
import { type Identity, identityDraftSchema, identitySchema } from './schemas.js';

/** Most product types and product titles in a catalog summary. */
const SUMMARY_LIMIT = 10;

/**
 * What the identity step needs to know about `catalog`: its collections,
 * its most common product types, its price range and its first product
 * titles.
 */
function summarizeCatalog(catalog: Catalog): unknown {
  const typeCounts = new Map<string, number>();
  for (const p of catalog.products) {
    typeCounts.set(p.product_type, (typeCounts.get(p.product_type) ?? 0) + 1);
  }
  const prices = catalog.products
    .flatMap((p) => p.variants.map((v) => v.price))
    .sort((a, b) => Number(a) - Number(b));
  return {
    product_count: catalog.products.length,
    collections: catalog.collections.map((c) => ({
      title: c.title,
      product_count: c.product_handles.length,
    })),
    product_types: [...typeCounts]
      .sort(([a, m], [b, n]) => n - m || (a < b ? -1 : a > b ? 1 : 0))
      .slice(0, SUMMARY_LIMIT)
      .map(([productType, count]) => ({ product_type: productType, product_count: count })),
    price_range: { min: prices[0] ?? null, max: prices.at(-1) ?? null },
    sample_titles: catalog.products.slice(0, SUMMARY_LIMIT).map((p) => p.title),
  };
}

/** @param catalog The copied catalog of `--data`, or `undefined` when the catalog is synthesized. */
export async function synthIdentity(sc: SynthContext, catalog?: Catalog): Promise<Identity> {
  const file = path.join(sc.shopDir, IDENTITY_FILE);
  const existing = await readJsonIfExists(file, identitySchema);
  if (existing !== undefined) {
    sc.log('[data_synth] identity.json: cached');
    return existing;
  }
  const capabilities = await readJsonFile(
    path.join(sc.manualDir, 'capabilities.json'),
    z.unknown(),
  );
  const manual = await fs.readFile(path.join(sc.manualDir, 'manual.md'), 'utf-8');
  const draft = await completeStructured(
    sc.call,
    synthPrompt(sc, 'synth_identity', {
      capabilities: pretty(capabilities),
      manual: manual.trimEnd(),
      catalog: catalog === undefined ? 'null' : pretty(summarizeCatalog(catalog)),
    }),
    identityDraftSchema,
  );
  const identity: Identity = {
    name: pickBrandName(`${sc.config.name}\0${draft.descriptor}`, sc.allowlist),
    descriptor: draft.descriptor.trim(),
    tone: draft.tone.map((t) => t.trim()),
    currency: draft.currency.toUpperCase(),
    country: draft.country.toUpperCase(),
  };
  await writeJsonFile(file, identity);
  return identity;
}
