/** `synth_alt_text`: per-collection alt-text strings, one per product image. */

import { findAllowlistedToken } from '../brands/allowlist.js';
import { mapLimit } from '../io.js';
import { completeStructured } from '../llm.js';
import { type SynthContext, cached, pretty, synthPrompt } from './context.js';
import {
  type AltTextMap,
  type CollectionDraft,
  type ProductDetail,
  type ProductSkeleton,
  altTextEntriesSchema,
  altTextMapSchema,
} from './schemas.js';

const MIN_CHARS = 10;
const MAX_CHARS = 200;

export function synthAltText(
  sc: SynthContext,
  collections: readonly CollectionDraft[],
  skeletons: readonly ProductSkeleton[],
  details: ReadonlyMap<string, ProductDetail>,
): Promise<AltTextMap> {
  const perProduct = sc.config.catalog.imagesPerProduct;
  return cached(sc, 'alt_text.json', altTextMapSchema, async () => {
    if (perProduct === 0) return {};
    const perCollection = await mapLimit(collections, sc.config.concurrency, (collection) => {
      const products = skeletons
        .filter((s) => s.collection_handle === collection.handle && details.has(s.handle))
        .map((s) => {
          const d = details.get(s.handle);
          return {
            handle: s.handle,
            title: s.title,
            vendor: d?.vendor ?? '',
            product_type: d?.product_type ?? '',
            tags: d?.tags ?? [],
          };
        });
      if (products.length === 0) return Promise.resolve([]);
      const expected = new Set(products.map((p) => p.handle));
      return completeStructured(
        sc.call,
        synthPrompt(sc, 'synth_alt_text', {
          images_per_product: String(perProduct),
          collection: pretty({ title: collection.title, handle: collection.handle }),
          products: pretty(products),
          min_chars: String(MIN_CHARS),
          max_chars: String(MAX_CHARS),
        }),
        altTextEntriesSchema,
        (entries) => {
          const got = new Set(entries.map((e) => e.handle));
          const missing = [...expected].filter((h) => !got.has(h));
          if (missing.length > 0) return `missing handles: ${missing.join(', ')}`;
          for (const entry of entries) {
            if (!expected.has(entry.handle)) return `unknown handle ${entry.handle}`;
            if (entry.alts.length !== perProduct) {
              return `${entry.handle} has ${entry.alts.length} alts, expected ${perProduct}`;
            }
            for (const alt of entry.alts) {
              if (alt.length < MIN_CHARS || alt.length > MAX_CHARS) {
                return `alt for ${entry.handle} must be ${MIN_CHARS}-${MAX_CHARS} chars: ${JSON.stringify(alt)}`;
              }
              const token = findAllowlistedToken(alt, sc.allowlist);
              if (token !== undefined)
                return `alt for ${entry.handle} contains brand token ${token}`;
            }
          }
          return undefined;
        },
      );
    });
    return Object.fromEntries(perCollection.flat().map((e) => [e.handle, e.alts]));
  });
}
