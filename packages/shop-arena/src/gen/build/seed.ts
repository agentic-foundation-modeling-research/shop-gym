/**
 * Template seeding: copy a template's tracked files into a run artifact and
 * install its dependencies so the agent starts from a working tree.
 *
 * Only `git ls-files` output is copied, so local scratch files never leak
 * into a shop. Every seeded copy carries `template.json`, a fingerprint of
 * the template (commit, content hash, per-file digests) that `publish`
 * records and that the `sandbox_contract` verifier compares against.
 */

import * as fsSync from 'node:fs';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sha256Hex } from './tree.js';
import { type CommandRunner, runCommand } from './verifiers/subprocess.js';

export const TEMPLATE_JSON = 'template.json';
const INSTALL_TIMEOUT_MS = 10 * 60_000;
const GIT_TIMEOUT_MS = 30_000;

export class SeedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SeedError';
  }
}

/** Identity of the template a copy was seeded from. Serialised as `template.json`. */
export interface TemplateFingerprint {
  /** Template directory basename, e.g. `shop_backend`. */
  readonly name: string;
  /** `git rev-parse HEAD` of the template checkout; `null` when unavailable. */
  readonly commit: string | null;
  /** Digest over every tracked file's path and content. */
  readonly contentHash: string;
  /** Tracked relative path -> SHA-256 of its content. */
  readonly files: Readonly<Record<string, string>>;
  readonly seededAt: string;
}

export interface SeedTemplateOptions {
  readonly templateDir: string;
  readonly destDir: string;
  /** Subprocess seam for `git` and `pnpm`; defaults to a real spawn. */
  readonly runner?: CommandRunner;
}

/** Tracked files of `templateDir` (relative, POSIX), via `git ls-files`. */
export async function listTrackedFiles(
  templateDir: string,
  runner: CommandRunner = runCommand,
): Promise<string[]> {
  const result = await runner(['git', 'ls-files', '-z'], {
    cwd: templateDir,
    timeoutMs: GIT_TIMEOUT_MS,
  });
  if (result.exitCode !== 0) {
    throw new SeedError(`git ls-files failed in ${templateDir}: ${result.stderr.trim()}`);
  }
  return result.stdout.split('\0').filter((rel) => rel !== '');
}

/** Fingerprint `templateDir` without copying it. */
export async function templateFingerprint(
  templateDir: string,
  runner: CommandRunner = runCommand,
): Promise<TemplateFingerprint> {
  const files: Record<string, string> = {};
  for (const rel of await listTrackedFiles(templateDir, runner)) {
    const content = await fs.readFile(path.join(templateDir, rel)).catch(() => undefined);
    if (content !== undefined) {
      files[rel] = sha256Hex(content);
    }
  }
  const head = await runner(['git', 'rev-parse', 'HEAD'], {
    cwd: templateDir,
    timeoutMs: GIT_TIMEOUT_MS,
  });
  const lines = Object.keys(files)
    .sort()
    .map((rel) => `${rel}\0${files[rel]}\n`);
  return {
    name: path.basename(templateDir),
    commit: head.exitCode === 0 ? head.stdout.trim() : null,
    contentHash: sha256Hex(lines.join('')),
    files,
    seededAt: new Date().toISOString(),
  };
}

/**
 * Copy the tracked files of `templateDir` into `destDir`, make the copy's
 * `tsconfig.json` standalone, write `template.json`, and run
 * `pnpm install --ignore-workspace --prefer-offline` (plus `--frozen-lockfile`
 * when the template tracks a `pnpm-lock.yaml`).
 *
 * @throws SeedError when `destDir` already contains `template.json`, when
 *   `git ls-files` fails, or when the install exits non-zero.
 */
export async function seedTemplate(options: SeedTemplateOptions): Promise<TemplateFingerprint> {
  const runner = options.runner ?? runCommand;
  const { templateDir, destDir } = options;
  if (await exists(path.join(destDir, TEMPLATE_JSON))) {
    throw new SeedError(`destination already seeded: ${destDir}`);
  }
  const fingerprint = await templateFingerprint(templateDir, runner);
  for (const rel of Object.keys(fingerprint.files)) {
    const target = path.join(destDir, rel);
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.copyFile(path.join(templateDir, rel), target);
  }
  await detachTsconfig(templateDir, destDir);
  await fs.writeFile(
    path.join(destDir, TEMPLATE_JSON),
    `${JSON.stringify(fingerprint, null, 2)}\n`,
  );
  const installArgv = ['pnpm', 'install', '--ignore-workspace', '--prefer-offline'];
  if ('pnpm-lock.yaml' in fingerprint.files) {
    installArgv.push('--frozen-lockfile');
  }
  const install = await runner(installArgv, { cwd: destDir, timeoutMs: INSTALL_TIMEOUT_MS });
  if (install.exitCode !== 0) {
    throw new SeedError(
      `pnpm install failed in ${destDir} (exit ${install.exitCode}):\n${install.stderr.trim()}`,
    );
  }
  return fingerprint;
}

/**
 * Seed `packages/shop_backend` into `destDir` (normally `<runDir>/artifact/backend`).
 */
export async function seedBackend(options: {
  readonly destDir: string;
  readonly templateDir?: string;
  readonly runner?: CommandRunner;
}): Promise<TemplateFingerprint> {
  return seedTemplate({
    templateDir: options.templateDir ?? defaultBackendTemplateDir(),
    destDir: options.destDir,
    ...(options.runner !== undefined ? { runner: options.runner } : {}),
  });
}

/** `packages/shop_backend` of the checkout this module runs from. */
export function defaultBackendTemplateDir(): string {
  return path.join(repoRoot(), 'packages', 'shop_backend');
}

/** Repository root, found by walking up from this file to `pnpm-workspace.yaml`. */
export function repoRoot(): string {
  let dir = path.dirname(fileURLToPath(import.meta.url));
  for (;;) {
    if (fsExistsSync(path.join(dir, 'pnpm-workspace.yaml'))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      throw new SeedError(`pnpm-workspace.yaml not found above ${import.meta.url}`);
    }
    dir = parent;
  }
}

/**
 * A template `tsconfig.json` that extends a file outside the template (the
 * workspace `tsconfig.base.json`) would break once copied. Copy the base
 * file next to it and point `extends` at the copy.
 */
async function detachTsconfig(templateDir: string, destDir: string): Promise<void> {
  const tsconfigPath = path.join(destDir, 'tsconfig.json');
  const raw = await fs.readFile(tsconfigPath, 'utf-8').catch(() => undefined);
  if (raw === undefined) {
    return;
  }
  const parsed = JSON.parse(raw) as { extends?: unknown };
  if (typeof parsed.extends !== 'string' || !parsed.extends.startsWith('..')) {
    return;
  }
  const baseSource = path.resolve(templateDir, parsed.extends);
  const baseName = path.basename(baseSource);
  await fs.copyFile(baseSource, path.join(destDir, baseName));
  await fs.writeFile(
    tsconfigPath,
    `${JSON.stringify({ ...parsed, extends: `./${baseName}` }, null, 2)}\n`,
  );
}

async function exists(filePath: string): Promise<boolean> {
  return (await fs.stat(filePath).catch(() => undefined)) !== undefined;
}

function fsExistsSync(filePath: string): boolean {
  try {
    return fsSync.statSync(filePath).isFile();
  } catch {
    return false;
  }
}
