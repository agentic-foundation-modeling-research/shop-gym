/**
 * Content snapshots of directory trees.
 *
 * A snapshot maps POSIX-style relative paths to SHA-256 hex digests. The
 * build loop uses snapshots to detect what an iteration changed (owned-file
 * checks) and whether the backend sidecar needs a restart.
 */

import { createHash } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

/** Relative POSIX path -> SHA-256 hex of the file content. */
export type TreeSnapshot = Readonly<Record<string, string>>;

/** Directory names skipped by every snapshot: generated or vendored trees. */
export const DEFAULT_IGNORED_DIRS: readonly string[] = [
  'node_modules',
  'dist',
  'build',
  '.react-router',
  '.vite',
  '.cache',
  'coverage',
];

/** Hex SHA-256 of a byte buffer. */
export function sha256Hex(data: Uint8Array | string): string {
  return createHash('sha256').update(data).digest('hex');
}

/**
 * Hash every regular file under `root`, skipping `ignoreDirs` at any depth.
 *
 * Symlinks are not followed. A missing root yields an empty snapshot.
 */
export async function snapshotTree(
  root: string,
  ignoreDirs: readonly string[] = DEFAULT_IGNORED_DIRS,
): Promise<TreeSnapshot> {
  const out: Record<string, string> = {};
  const ignored = new Set(ignoreDirs);
  async function walk(dir: string, rel: string): Promise<void> {
    let entries: import('node:fs').Dirent[];
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return;
      }
      throw error;
    }
    for (const entry of entries) {
      const entryRel = rel === '' ? entry.name : `${rel}/${entry.name}`;
      if (entry.isDirectory()) {
        if (!ignored.has(entry.name)) {
          await walk(path.join(dir, entry.name), entryRel);
        }
      } else if (entry.isFile()) {
        out[entryRel] = sha256Hex(await fs.readFile(path.join(dir, entry.name)));
      }
    }
  }
  await walk(root, '');
  return out;
}

/** Sorted relative paths added, removed, or modified between two snapshots. */
export function diffTrees(before: TreeSnapshot, after: TreeSnapshot): string[] {
  const changed = new Set<string>();
  for (const [rel, digest] of Object.entries(after)) {
    if (before[rel] !== digest) {
      changed.add(rel);
    }
  }
  for (const rel of Object.keys(before)) {
    if (!(rel in after)) {
      changed.add(rel);
    }
  }
  return [...changed].sort();
}

/** One digest over a whole snapshot; equal snapshots hash equal. */
export function hashSnapshot(snapshot: TreeSnapshot): string {
  const lines = Object.keys(snapshot)
    .sort()
    .map((rel) => `${rel}\0${snapshot[rel]}\n`);
  return sha256Hex(lines.join(''));
}
