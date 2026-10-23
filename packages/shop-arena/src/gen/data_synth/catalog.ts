/** `synth_collections` and `synth_product_skeletons`: the catalog spine. */

import * as path from 'node:path';

import { z } from 'zod';

import { findAllowlistedToken } from '../brands/allowlist.js';
import { readJsonFile } from '../io.js';
import { completeStructured } from '../llm.js';
import { type SynthContext, cached, duplicates, pretty, synthPrompt } from './context.js';
import {
  type CollectionDraft,
  type Identity,
  type ProductSkeleton,
  collectionDraftsSchema,
  productSkeletonsSchema,
} from './schemas.js';

export function synthCollections(sc: SynthContext, identity: Identity): Promise<CollectionDraft[]> {
  const targetCount = sc.config.catalog.collections;
  const targetProducts = targetCount * sc.config.catalog.productsPerCollection;
  return cached(sc, 'collections.json', collectionDraftsSchema, async () => {
    const capabilities = await readJsonFile(
      path.join(sc.manualDir, 'capabilities.json'),
      z.unknown(),
    );
    const stats = await readJsonFile(
      path.join(sc.manualDir, 'stats.json'),
      z.record(z.string(), z.unknown()),
    );
    return completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_collections', {
        identity: pretty(identity),
        capabilities: pretty(capabilities),
        stats: pretty({ ...stats, collections_total: targetCount, products_total: targetProducts }),
        target_count: String(targetCount),
        target_products_total: String(targetProducts),
      }),
      collectionDraftsSchema,
      (collections) => {
        if (collections.length !== targetCount) {
          return `expected ${targetCount} collections, got ${collections.length}`;
        }
        const dupes = duplicates(collections.map((c) => c.handle));
        if (dupes.length > 0) return `duplicate collection handles: ${dupes.join(', ')}`;
        for (const c of collections) {
          const token = findAllowlistedToken(c.title, sc.allowlist);
          if (token !== undefined)
            return `collection title ${JSON.stringify(c.title)} contains brand token ${token}`;
        }
        const total = collections.reduce((sum, c) => sum + c.target_product_count, 0);
        return total === targetProducts
          ? undefined
          : `target_product_count sums to ${total}, expected ${targetProducts}`;
      },
    );
  });
}

function wordCount(title: string): number {
  return title
    .trim()
    .split(/\s+/)
    .filter((w) => w !== '' && !/^\d+$/.test(w)).length;
}

export function synthSkeletons(
  sc: SynthContext,
  collections: readonly CollectionDraft[],
): Promise<ProductSkeleton[]> {
  const total = collections.reduce((sum, c) => sum + c.target_product_count, 0);
  return cached(sc, 'skeletons.json', productSkeletonsSchema, () =>
    completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_product_skeletons', {
        collections: pretty(collections),
        total_products: String(total),
      }),
      productSkeletonsSchema,
      (skeletons) => {
        if (skeletons.length !== total)
          return `expected ${total} skeletons, got ${skeletons.length}`;
        const dupes = duplicates(skeletons.map((s) => s.handle));
        if (dupes.length > 0) return `duplicate product handles: ${dupes.join(', ')}`;
        for (const c of collections) {
          const n = skeletons.filter((s) => s.collection_handle === c.handle).length;
          if (n !== c.target_product_count) {
            return `collection ${c.handle} has ${n} skeletons, expected ${c.target_product_count}`;
          }
        }
        const known = new Set(collections.map((c) => c.handle));
        for (const s of skeletons) {
          if (!known.has(s.collection_handle))
            return `unknown collection_handle ${s.collection_handle}`;
          const words = wordCount(s.title);
          if (words < 2 || words > 5) return `title ${JSON.stringify(s.title)} must have 2-5 words`;
          const token = findAllowlistedToken(s.title, sc.allowlist);
          if (token !== undefined)
            return `title ${JSON.stringify(s.title)} contains brand token ${token}`;
        }
        return undefined;
      },
    ),
  );
}
