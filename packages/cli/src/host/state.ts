/**
 * Host bookkeeping under `<repoRoot>/.run/shops/<name>/`: the running
 * processes (`state.json`), the last install/build (`build.json`) and the
 * process logs.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { z } from 'zod';

const processStateSchema = z.object({
  pid: z.number().int().positive(),
  port: z.number().int().positive(),
  url: z.string(),
  logPath: z.string(),
});

export const hostStateSchema = z.object({
  name: z.string(),
  shopDir: z.string(),
  startedAt: z.string(),
  backend: processStateSchema,
  storefront: processStateSchema,
});

export type ProcessState = z.infer<typeof processStateSchema>;
export type HostState = z.infer<typeof hostStateSchema>;

/** What the last successful install + build was made from. */
export const buildRecordSchema = z.object({
  publishedAt: z.string(),
  /** Template content hashes from `shop.json`. */
  storefront: z.string(),
  backend: z.string(),
});

export type BuildRecord = z.infer<typeof buildRecordSchema>;

const STATE_FILE = 'state.json';
const BUILD_FILE = 'build.json';

export function shopsRunDir(repoRoot: string): string {
  return path.join(repoRoot, '.run', 'shops');
}

export function shopRunDir(repoRoot: string, name: string): string {
  return path.join(shopsRunDir(repoRoot), name);
}

export async function readState(runDir: string): Promise<HostState | undefined> {
  const raw = await readOptional(path.join(runDir, STATE_FILE));
  return raw === undefined ? undefined : hostStateSchema.parse(JSON.parse(raw));
}

export async function writeState(runDir: string, state: HostState): Promise<void> {
  await writeJson(path.join(runDir, STATE_FILE), state);
}

export async function removeState(runDir: string): Promise<void> {
  await fs.rm(path.join(runDir, STATE_FILE), { force: true });
}

/** Every tracked shop, sorted by name. */
export async function listStates(repoRoot: string): Promise<HostState[]> {
  const entries = await fs.readdir(shopsRunDir(repoRoot), { withFileTypes: true }).catch(() => []);
  const states: HostState[] = [];
  for (const entry of entries.filter((e) => e.isDirectory())) {
    const state = await readState(path.join(shopsRunDir(repoRoot), entry.name));
    if (state !== undefined) {
      states.push(state);
    }
  }
  return states.sort((a, b) => a.name.localeCompare(b.name));
}

export async function readBuildRecord(runDir: string): Promise<BuildRecord | undefined> {
  const raw = await readOptional(path.join(runDir, BUILD_FILE));
  return raw === undefined ? undefined : buildRecordSchema.parse(JSON.parse(raw));
}

export async function writeBuildRecord(runDir: string, record: BuildRecord): Promise<void> {
  await writeJson(path.join(runDir, BUILD_FILE), record);
}

async function readOptional(file: string): Promise<string | undefined> {
  try {
    return await fs.readFile(file, 'utf-8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return undefined;
    }
    throw error;
  }
}

async function writeJson(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`);
}
