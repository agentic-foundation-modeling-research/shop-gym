/**
 * `synth_images`: renders `imagesPerProduct` files per product into
 * `data/images/<handle>-<n><ext>` (1-based `n`). Files already on disk are
 * kept, so an interrupted run resumes where it stopped.
 */

import * as path from 'node:path';

import { exists, mapLimit, writeBytes, writeJsonFile } from '../../io.js';
import { STAGE_CACHE_DIR, type SynthContext } from '../context.js';
import {
  type CollectionDraft,
  type ImagesManifest,
  type ProductDetail,
  type ProductSkeleton,
  imagesManifestSchema,
} from '../schemas.js';
import type { ImageRequest } from './backend.js';

export const IMAGES_DIR = 'images';
export const IMAGES_MANIFEST = 'images_manifest.json';
export const IMAGE_SIZE = 800;

export function imageFileName(handle: string, index: number, extension: string): string {
  return `${handle}-${index + 1}${extension}`;
}

export async function synthImages(
  sc: SynthContext,
  collections: readonly CollectionDraft[],
  skeletons: readonly ProductSkeleton[],
  details: ReadonlyMap<string, ProductDetail>,
): Promise<ImagesManifest> {
  const { images } = sc;
  const perProduct = sc.config.catalog.imagesPerProduct;
  const titles = new Map(collections.map((c) => [c.handle, c.title]));
  const requests: ImageRequest[] = skeletons
    .filter((s) => details.has(s.handle))
    .flatMap((s) =>
      Array.from({ length: perProduct }, (_, index) => ({
        handle: s.handle,
        index,
        title: s.title,
        category:
          details.get(s.handle)?.product_type ??
          titles.get(s.collection_handle) ??
          s.collection_handle,
        width: IMAGE_SIZE,
        height: IMAGE_SIZE,
      })),
    );
  const imagesDir = path.join(sc.dataDir, IMAGES_DIR);
  const entries = await mapLimit(requests, sc.config.concurrency, async (request) => {
    const file = imageFileName(request.handle, request.index, images.extension);
    const target = path.join(imagesDir, file);
    if (!(await exists(target))) {
      await writeBytes(target, await images.render(request, sc.signal));
    }
    return {
      handle: request.handle,
      index: request.index,
      file,
      width: request.width,
      height: request.height,
    };
  });
  const manifest: ImagesManifest = {
    backend: images.name,
    extension: images.extension,
    imagesPerProduct: perProduct,
    entries,
  };
  await writeJsonFile(
    path.join(sc.shopDir, STAGE_CACHE_DIR, IMAGES_MANIFEST),
    imagesManifestSchema.parse(manifest),
  );
  sc.log(`[data_synth] images: ${entries.length} files via ${images.name}`);
  return manifest;
}
