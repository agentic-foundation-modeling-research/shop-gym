/**
 * Publish step: copy the built storefront and backend out of a build run
 * into a shop directory and write `shop.json`, the manifest the hosting
 * step reads. Nothing from `artifact/data` is copied: the published backend
 * serves the dataset it was built against from its own `data/` directory.
 *
 * No `storefront/.env` is written. The storefront template applies
 * defaults when its variables are unset, so `host` passes
 * `PUBLIC_STORE_DOMAIN` (and `PORT`, `SESSION_SECRET`) through the process
 * environment instead of a file that would pin a local URL.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { FinalStatus } from '@shop-gym/harness';
import { z } from 'zod';

import { BUILD_JSON, type BuildRunInfo } from '../build/build_loop.js';
import { TEMPLATE_JSON, type TemplateFingerprint } from '../build/seed.js';

export const SHOP_JSON = 'shop.json';

/** Directory names never copied out of a build artifact. */
export const PUBLISH_EXCLUDED_DIRS: ReadonlySet<string> = new Set([
  'node_modules',
  'dist',
  'build',
  '.react-router',
  '.vite',
  '.cache',
]);

const templateFingerprintSchema = z.object({
  name: z.string(),
  commit: z.string().nullable(),
  contentHash: z.string(),
  files: z.record(z.string(), z.string()),
  seededAt: z.string(),
});

export const shopManifestSchema = z.object({
  name: z.string(),
  templates: z.object({
    storefront: templateFingerprintSchema,
    backend: templateFingerprintSchema,
  }),
  genBackend: z.boolean(),
  publishedAt: z.string(),
  finalStatus: z.string(),
});

export type ShopManifest = z.infer<typeof shopManifestSchema>;

export interface PublishOptions {
  /** Build run directory containing `artifact/`, `build.json` and `run.json`. */
  readonly runDir: string;
  /** Destination shop directory; `storefront/`, `backend/` and `shop.json` are replaced. */
  readonly shopDir: string;
}

export interface PublishResult {
  readonly shopDir: string;
  readonly manifestPath: string;
  readonly manifest: ShopManifest;
}

export class PublishError extends Error {}

export async function publishShop(options: PublishOptions): Promise<PublishResult> {
  const { runDir, shopDir } = options;
  const artifactDir = path.join(runDir, 'artifact');
  const build = await readJson<BuildRunInfo>(path.join(runDir, BUILD_JSON));
  if (build === undefined) {
    throw new PublishError(`${path.join(runDir, BUILD_JSON)} is missing; was the build loop run?`);
  }
  await fs.mkdir(shopDir, { recursive: true });
  const templates: Record<'storefront' | 'backend', TemplateFingerprint> = {
    storefront: await copyComponent(artifactDir, shopDir, 'storefront'),
    backend: await copyComponent(artifactDir, shopDir, 'backend'),
  };
  const run = await readJson<{ finalStatus?: FinalStatus }>(path.join(runDir, 'run.json'));
  const manifest: ShopManifest = {
    name: path.basename(path.resolve(shopDir)),
    templates,
    genBackend: build.genBackend,
    publishedAt: new Date().toISOString(),
    finalStatus: run?.finalStatus ?? 'unknown',
  };
  const manifestPath = path.join(shopDir, SHOP_JSON);
  await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return { shopDir, manifestPath, manifest };
}

export async function readShopManifest(shopDir: string): Promise<ShopManifest> {
  const file = path.join(shopDir, SHOP_JSON);
  return shopManifestSchema.parse(JSON.parse(await fs.readFile(file, 'utf-8')));
}

/** Replace `<shopDir>/<name>` with a filtered copy of `<artifactDir>/<name>`. */
async function copyComponent(
  artifactDir: string,
  shopDir: string,
  name: 'storefront' | 'backend',
): Promise<TemplateFingerprint> {
  const source = path.join(artifactDir, name);
  const dest = path.join(shopDir, name);
  const fingerprint = await readJson<TemplateFingerprint>(path.join(source, TEMPLATE_JSON));
  if (fingerprint === undefined) {
    throw new PublishError(`${source} has no ${TEMPLATE_JSON}; not a seeded build artifact`);
  }
  await fs.rm(dest, { recursive: true, force: true });
  await fs.cp(source, dest, {
    recursive: true,
    filter: (src) => {
      const rel = path.relative(source, src);
      if (rel === '') {
        return true;
      }
      const base = path.basename(rel);
      if (PUBLISH_EXCLUDED_DIRS.has(base) || base.endsWith('.log')) {
        return false;
      }
      return !(name === 'storefront' && rel === '.env');
    },
  });
  return fingerprint;
}

async function readJson<T>(file: string): Promise<T | undefined> {
  const raw = await fs.readFile(file, 'utf-8').catch(() => undefined);
  return raw === undefined ? undefined : (JSON.parse(raw) as T);
}
