/**
 * Seed immutability check.
 *
 * Files copied from `artifactSeedDir` into `run_dir/artifact/` are stable for
 * the whole run. `snapshotSeed` fingerprints them at workspace creation and
 * `checkSeed` reports any mutation, deletion, or extension of the seeded
 * subtree after an iteration as `seed_mutated:`, `seed_deleted:`, and
 * `seed_extended:` violations.
 */

import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { pipeline } from 'node:stream/promises';

import { z } from 'zod';

import type { ProtocolCheckResult } from './plan/protocol.js';

/** Raised when a seed manifest cannot be built or read. */
export class SeedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SeedError';
  }
}

/** Fingerprint of the seeded subtree. Keys are POSIX paths relative to `artifact/`. */
export const seedManifestSchema = z.object({
  /** Top-level entries copied from the seed dir; bounds the post-iteration scan. */
  seededRoots: z.array(z.string()),
  /** Relative path to sha256 hex digest, sorted by path. */
  files: z.record(z.string(), z.string()),
});

export type SeedManifest = z.infer<typeof seedManifestSchema>;

/** Parse a persisted manifest. */
export function parseSeedManifest(payload: unknown): SeedManifest {
  const parsed = seedManifestSchema.safeParse(payload);
  if (!parsed.success) {
    throw new SeedError(`seed manifest has wrong shape: ${parsed.error.message}`);
  }
  return parsed.data;
}

/** Throw `SeedError` if any entry under `root` is a symlink. */
export async function rejectSymlinks(root: string, rel = ''): Promise<void> {
  for (const entry of await sortedEntries(root)) {
    const entryRel = rel === '' ? entry.name : `${rel}/${entry.name}`;
    if (entry.isSymbolicLink()) {
      throw new SeedError(`symlink in seed not supported: ${entryRel}`);
    }
    if (entry.isDirectory()) {
      await rejectSymlinks(path.join(root, entry.name), entryRel);
    }
  }
}

/**
 * Hash every regular file under the seeded roots of `artifactDir`.
 *
 * @throws SeedError on a symlink or a missing root.
 */
export async function snapshotSeed(
  artifactDir: string,
  seededRoots: readonly string[],
): Promise<SeedManifest> {
  const files: Record<string, string> = {};
  for (const root of [...seededRoots].sort()) {
    const rootPath = path.join(artifactDir, root);
    const stat = await fs.lstat(rootPath).catch(() => undefined);
    if (stat === undefined) {
      throw new SeedError(`seeded root missing from artifact_dir: ${root}`);
    }
    if (stat.isSymbolicLink()) {
      throw new SeedError(`symlink in seed not supported: ${root}`);
    }
    if (stat.isDirectory()) {
      await hashDir(rootPath, root, files);
    } else {
      files[root] = await hashFile(rootPath);
    }
  }
  return { seededRoots: [...seededRoots].sort(), files: sortRecord(files) };
}

/** Diff the seeded subtree against `manifest`; violations are sorted within each category. */
export async function checkSeed(
  manifest: SeedManifest,
  artifactDir: string,
  iterId: string,
): Promise<ProtocolCheckResult> {
  const current = await walkSeededSubtree(artifactDir, manifest.seededRoots);
  const mutated: string[] = [];
  const deleted: string[] = [];
  const extended: string[] = [];
  for (const [rel, expected] of Object.entries(manifest.files)) {
    const actual = current.get(rel);
    if (actual === undefined) {
      deleted.push(rel);
    } else if (actual !== expected) {
      mutated.push(rel);
    }
  }
  for (const rel of current.keys()) {
    if (!(rel in manifest.files)) {
      extended.push(rel);
    }
  }
  const violations = [
    ...mutated.sort().map((rel) => `seed_mutated: ${rel}`),
    ...deleted.sort().map((rel) => `seed_deleted: ${rel}`),
    ...extended.sort().map((rel) => `seed_extended: ${rel}`),
  ];
  return { iterId, passed: violations.length === 0, violations };
}

async function hashFile(filePath: string): Promise<string> {
  const hasher = createHash('sha256');
  await pipeline(createReadStream(filePath), hasher);
  return hasher.digest('hex');
}

async function sortedEntries(dir: string) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  return entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

async function hashDir(dir: string, rel: string, files: Record<string, string>): Promise<void> {
  for (const entry of await sortedEntries(dir)) {
    const entryRel = `${rel}/${entry.name}`;
    const entryPath = path.join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      throw new SeedError(`symlink in seed not supported: ${entryRel}`);
    }
    if (entry.isDirectory()) {
      await hashDir(entryPath, entryRel, files);
    } else if (entry.isFile()) {
      files[entryRel] = await hashFile(entryPath);
    } else {
      throw new SeedError(`unsupported seed entry kind: ${entryRel}`);
    }
  }
}

/**
 * Walk the seeded subtree tolerating deleted roots. Symlinks are recorded
 * with an empty digest so `checkSeed` reports them as extensions.
 */
async function walkSeededSubtree(
  artifactDir: string,
  seededRoots: readonly string[],
): Promise<Map<string, string>> {
  const found = new Map<string, string>();
  for (const root of seededRoots) {
    const rootPath = path.join(artifactDir, root);
    const stat = await fs.lstat(rootPath).catch(() => undefined);
    if (stat === undefined) {
      continue;
    }
    if (stat.isSymbolicLink()) {
      found.set(root, '');
    } else if (stat.isDirectory()) {
      await walkDir(rootPath, root, found);
    } else if (stat.isFile()) {
      found.set(root, await hashFile(rootPath));
    }
  }
  return found;
}

async function walkDir(dir: string, rel: string, found: Map<string, string>): Promise<void> {
  for (const entry of await sortedEntries(dir)) {
    const entryRel = `${rel}/${entry.name}`;
    const entryPath = path.join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      found.set(entryRel, '');
    } else if (entry.isDirectory()) {
      await walkDir(entryPath, entryRel, found);
    } else if (entry.isFile()) {
      found.set(entryRel, await hashFile(entryPath));
    }
  }
}

function sortRecord(record: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(record).sort(([a], [b]) => (a < b ? -1 : 1)));
}
