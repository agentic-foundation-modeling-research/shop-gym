/**
 * `synth_product_details`: per-collection product details, drafted in
 * chunks of ten skeletons and cached per collection under
 * `.shop_gen/stage_cache/details/<handle>.json` so a crashed run resumes
 * with the collections already written. Rows the LLM gets wrong are
 * retried once on their own and dropped afterwards; dropping more than
 * 5% of the catalog fails the step.
 */

import * as path from 'node:path';

import { findAllowlistedToken, isAllowedBrand } from '../brands/allowlist.js';
import { mapLimit, readJsonIfExists, writeJsonFile } from '../io.js';
import { SynthError, completeStructured } from '../llm.js';
import { type SynthContext, pretty, synthPrompt } from './context.js';
import {
  type CollectionDraft,
  type DetailsManifest,
  type Identity,
  type ProductDetail,
  type ProductSkeleton,
  detailsManifestSchema,
  productDetailsSchema,
} from './schemas.js';

export const DETAILS_DIR = 'details';
export const DETAILS_MANIFEST = '_manifest.json';
const CHUNK_SIZE = 10;
const MAX_DROP_RATIO = 0.05;

function validateDetail(
  sc: SynthContext,
  skeleton: ProductSkeleton,
  detail: ProductDetail,
): string | undefined {
  if (detail.handle !== skeleton.handle) {
    return `expected handle ${skeleton.handle}, got ${detail.handle}`;
  }
  if (!isAllowedBrand(detail.vendor, sc.allowlist)) {
    return `vendor ${JSON.stringify(detail.vendor)} is not in the fake-brand allowlist`;
  }
  for (const [field, text] of [
    ['description_html', detail.description_html],
    ['product_type', detail.product_type],
    ['tags', detail.tags.join(' ')],
  ] as const) {
    const token = findAllowlistedToken(text, sc.allowlist);
    if (token !== undefined) return `${field} of ${skeleton.handle} contains brand token ${token}`;
  }
  const seen = new Set<string>();
  for (const variant of detail.variants) {
    const key = [variant.option1, variant.option2, variant.option3].join('|');
    if (seen.has(key)) return `product ${skeleton.handle} has duplicate variant options ${key}`;
    seen.add(key);
    for (const [i, option] of detail.options.entries()) {
      const value = [variant.option1, variant.option2, variant.option3][i] ?? null;
      if (value === null || !option.values.includes(value)) {
        return `variant ${variant.title} of ${skeleton.handle} has option${i + 1}=${value} outside ${option.name} values`;
      }
    }
  }
  return undefined;
}

/** Drafts details for `skeletons`; returns the rows that validated, in skeleton order. */
async function draftChunk(
  sc: SynthContext,
  identity: Identity,
  collection: CollectionDraft,
  skeletons: readonly ProductSkeleton[],
): Promise<ProductDetail[]> {
  const prompt = synthPrompt(sc, 'synth_product_details', {
    identity: pretty(identity),
    collection: pretty({
      title: collection.title,
      handle: collection.handle,
      description: collection.description,
    }),
    skeletons: pretty(skeletons),
    product_count: String(skeletons.length),
    allowlist: sc.allowlist.brands.join(', '),
  });
  const rows = await completeStructured(sc.call, prompt, productDetailsSchema, (details) =>
    details.length === skeletons.length
      ? undefined
      : `expected ${skeletons.length} detail objects, got ${details.length}`,
  );
  const good: ProductDetail[] = [];
  const failed: ProductSkeleton[] = [];
  for (const [i, skeleton] of skeletons.entries()) {
    const row = rows[i];
    const problem = row === undefined ? 'missing row' : validateDetail(sc, skeleton, row);
    if (row !== undefined && problem === undefined) {
      good.push(row);
    } else {
      sc.log(`[data_synth] details ${skeleton.handle}: ${problem ?? 'missing row'}`);
      failed.push(skeleton);
    }
  }
  if (failed.length === 0 || skeletons.length === 1) {
    return good;
  }
  const retried = await mapLimit(failed, sc.config.concurrency, (s) =>
    draftChunk(sc, identity, collection, [s]),
  );
  const byHandle = new Map([...good, ...retried.flat()].map((d) => [d.handle, d]));
  return skeletons.flatMap((s) => {
    const d = byHandle.get(s.handle);
    return d === undefined ? [] : [d];
  });
}

async function synthCollectionDetails(
  sc: SynthContext,
  identity: Identity,
  collection: CollectionDraft,
  skeletons: readonly ProductSkeleton[],
): Promise<ProductDetail[]> {
  const file = path.join(sc.cacheDir, DETAILS_DIR, `${collection.handle}.json`);
  const hit = await readJsonIfExists(file, productDetailsSchema);
  if (hit !== undefined) {
    sc.log(`[data_synth] details/${collection.handle}.json: cached`);
    return hit;
  }
  const chunks: ProductSkeleton[][] = [];
  for (let i = 0; i < skeletons.length; i += CHUNK_SIZE) {
    chunks.push(skeletons.slice(i, i + CHUNK_SIZE));
  }
  const details = (
    await mapLimit(chunks, sc.config.concurrency, (c) => draftChunk(sc, identity, collection, c))
  ).flat();
  await writeJsonFile(file, details);
  return details;
}

/** Details for every collection, keyed by product handle; skeletons without a row were dropped. */
export async function synthDetails(
  sc: SynthContext,
  identity: Identity,
  collections: readonly CollectionDraft[],
  skeletons: readonly ProductSkeleton[],
): Promise<Map<string, ProductDetail>> {
  const manifest: DetailsManifest = {
    collections: [],
    totalProducts: skeletons.length,
    totalDropped: 0,
  };
  const all = new Map<string, ProductDetail>();
  for (const collection of collections) {
    const members = skeletons.filter((s) => s.collection_handle === collection.handle);
    const details = await synthCollectionDetails(sc, identity, collection, members);
    for (const d of details) all.set(d.handle, d);
    const dropped = members.length - details.length;
    manifest.collections.push({
      handle: collection.handle,
      file: `${DETAILS_DIR}/${collection.handle}.json`,
      detailsCount: details.length,
      droppedCount: dropped,
    });
    manifest.totalDropped += dropped;
  }
  await writeJsonFile(
    path.join(sc.cacheDir, DETAILS_DIR, DETAILS_MANIFEST),
    detailsManifestSchema.parse(manifest),
  );
  if (manifest.totalDropped > MAX_DROP_RATIO * manifest.totalProducts) {
    throw new SynthError(
      `synth_product_details dropped ${manifest.totalDropped} of ${manifest.totalProducts} products (limit ${MAX_DROP_RATIO * 100}%)`,
    );
  }
  return all;
}
