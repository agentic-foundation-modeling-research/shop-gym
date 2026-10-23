/**
 * Content fingerprints for step inputs.
 *
 * A fingerprint is a SHA-256 over the sorted list of paths with, for each
 * one, either `missing` or the content hashes of every file beneath it.
 * Two fingerprints are equal exactly when every input is byte-identical,
 * so an unchanged upstream rerun does not invalidate downstream steps.
 */

import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

/**
 * Fingerprint a set of absolute paths.
 *
 * @param paths Files or directories; missing entries are included as missing.
 * @returns Hex SHA-256 digest.
 */
export function fingerprintPaths(paths: readonly string[]): string {
  const digest = createHash('sha256');
  for (const p of [...paths].sort()) {
    digest.update(`${p}\0`);
    if (!fs.existsSync(p)) {
      digest.update('missing\0');
      continue;
    }
    for (const file of listFiles(p)) {
      digest.update(`${path.relative(p, file)}\0${hashFile(file)}\0`);
    }
  }
  return digest.digest('hex');
}

function listFiles(root: string): string[] {
  if (fs.statSync(root).isFile()) {
    return [root];
  }
  const files: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort(byName)) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.isFile()) {
        files.push(full);
      }
    }
  };
  walk(root);
  return files;
}

function byName(a: fs.Dirent, b: fs.Dirent): number {
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

function hashFile(file: string): string {
  return createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}
