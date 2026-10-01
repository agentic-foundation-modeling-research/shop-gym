/**
 * Filesystem layout of one run.
 *
 * ```
 * run_dir/
 *   AGENTS.md  prompts/{planner,execute}.md  artifact/  plan.md  iters/
 *   run.json   .harness/seed_manifest.json
 * ```
 *
 * `Workspace.create` materialises the layout; `Workspace.open` adopts an
 * existing one for resume after checking the identity tuple (AGENTS.md,
 * both prompts, the seed manifest).
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { PlanExecLoopConfig } from './config.js';
import { parse } from './plan/parser.js';
import { type SeedManifest, parseSeedManifest, rejectSymlinks, snapshotSeed } from './seed.js';
import { atomicWriteJson } from './telemetry/summary.js';

export type WorkspaceConfig = Pick<
  PlanExecLoopConfig,
  'runDir' | 'agentsMd' | 'prompts' | 'artifactSeedDir'
>;

export class WorkspaceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'WorkspaceError';
  }
}

export type ResumeMismatchField =
  | 'agents_md'
  | 'prompts.planner'
  | 'prompts.execute'
  | 'seed_manifest'
  | 'plan_md'
  | 'iters_dir';

/** An existing `runDir` is not continuation-compatible with the config. */
export class ResumeMismatchError extends Error {
  constructor(
    readonly field: ResumeMismatchField,
    readonly runDir: string,
    readonly prior: string,
    readonly current: string,
  ) {
    super(
      `resume identity mismatch on ${field} for run_dir=${runDir}: prior=${JSON.stringify(prior)} current=${JSON.stringify(current)}`,
    );
    this.name = 'ResumeMismatchError';
  }
}

export class Workspace {
  readonly agentsMd: string;
  readonly plannerPrompt: string;
  readonly executePrompt: string;
  readonly artifactDir: string;
  readonly planMd: string;
  readonly itersDir: string;
  readonly runSummary: string;
  readonly seedManifestPath: string;

  constructor(
    readonly runDir: string,
    readonly seedManifest?: SeedManifest,
  ) {
    this.agentsMd = path.join(runDir, 'AGENTS.md');
    this.plannerPrompt = path.join(runDir, 'prompts', 'planner.md');
    this.executePrompt = path.join(runDir, 'prompts', 'execute.md');
    this.artifactDir = path.join(runDir, 'artifact');
    this.planMd = path.join(runDir, 'plan.md');
    this.itersDir = path.join(runDir, 'iters');
    this.runSummary = path.join(runDir, 'run.json');
    this.seedManifestPath = path.join(runDir, '.harness', 'seed_manifest.json');
  }

  /**
   * Materialise the layout for a fresh run.
   *
   * @throws WorkspaceError when `runDir` exists and is not an empty directory.
   */
  static async create(config: WorkspaceConfig): Promise<Workspace> {
    const runDir = config.runDir;
    const stat = await fs.stat(runDir).catch(() => undefined);
    if (stat !== undefined) {
      if (!stat.isDirectory()) {
        throw new WorkspaceError(`run_dir is not a directory: ${runDir}`);
      }
      if ((await fs.readdir(runDir)).length > 0) {
        throw new WorkspaceError(`run_dir is not empty: ${runDir}`);
      }
    }
    const bare = new Workspace(runDir);
    await fs.mkdir(path.dirname(bare.plannerPrompt), { recursive: true });
    await fs.writeFile(bare.agentsMd, config.agentsMd);
    await fs.writeFile(bare.plannerPrompt, config.prompts.planner);
    await fs.writeFile(bare.executePrompt, config.prompts.execute);
    await fs.mkdir(bare.artifactDir);
    let seedManifest: SeedManifest | undefined;
    if (config.artifactSeedDir !== undefined) {
      const roots = await copyTreeInto(config.artifactSeedDir, bare.artifactDir);
      seedManifest = await snapshotSeed(bare.artifactDir, roots);
      await atomicWriteJson(bare.seedManifestPath, seedManifest);
    }
    await fs.writeFile(bare.planMd, '');
    await fs.mkdir(bare.itersDir);
    return new Workspace(runDir, seedManifest);
  }

  /**
   * Adopt an existing run for resume. Read-only.
   *
   * @throws ResumeMismatchError on a missing required file or identity mismatch.
   * @throws InvalidPlanError when `plan.md` does not parse.
   */
  static async open(runDir: string, config: WorkspaceConfig): Promise<Workspace> {
    const bare = new Workspace(runDir);
    await requirePath(bare.agentsMd, 'agents_md', runDir, 'file');
    await requirePath(bare.plannerPrompt, 'prompts.planner', runDir, 'file');
    await requirePath(bare.executePrompt, 'prompts.execute', runDir, 'file');
    await requirePath(bare.planMd, 'plan_md', runDir, 'file');
    await requirePath(bare.itersDir, 'iters_dir', runDir, 'dir');
    await checkTextMatch(bare.agentsMd, config.agentsMd, 'agents_md', runDir);
    await checkTextMatch(bare.plannerPrompt, config.prompts.planner, 'prompts.planner', runDir);
    await checkTextMatch(bare.executePrompt, config.prompts.execute, 'prompts.execute', runDir);
    const seedManifest = await validateSeedManifest(bare, config.artifactSeedDir);
    const planText = await fs.readFile(bare.planMd, 'utf-8');
    if (planText.trim() !== '') {
      parse(planText);
    }
    return new Workspace(runDir, seedManifest);
  }

  /** The live `plan.md` text. */
  async readPlan(): Promise<string> {
    return fs.readFile(this.planMd, 'utf-8');
  }

  async writePlan(text: string): Promise<void> {
    await fs.writeFile(this.planMd, text);
  }

  /**
   * Copy `plan.md` byte for byte to `target`.
   *
   * @throws WorkspaceError when `target` exists and `overwrite` is false.
   */
  async snapshotPlan(target: string, overwrite = false): Promise<void> {
    if (!overwrite && (await exists(target))) {
      throw new WorkspaceError(`snapshot target already exists: ${target}`);
    }
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.copyFile(this.planMd, target);
  }
}

async function exists(filePath: string): Promise<boolean> {
  return (await fs.lstat(filePath).catch(() => undefined)) !== undefined;
}

/** Copy every entry of `src` into `dst` and return the top-level names. */
async function copyTreeInto(src: string, dst: string): Promise<string[]> {
  try {
    await rejectSymlinks(src);
  } catch (error) {
    throw new WorkspaceError(error instanceof Error ? error.message : String(error));
  }
  const names: string[] = [];
  for (const entry of await fs.readdir(src, { withFileTypes: true })) {
    await fs.cp(path.join(src, entry.name), path.join(dst, entry.name), { recursive: true });
    names.push(entry.name);
  }
  return names;
}

async function requirePath(
  filePath: string,
  field: ResumeMismatchField,
  runDir: string,
  kind: 'file' | 'dir',
): Promise<void> {
  const stat = await fs.stat(filePath).catch(() => undefined);
  if (stat !== undefined && (kind === 'file' ? stat.isFile() : stat.isDirectory())) {
    return;
  }
  const prior =
    stat === undefined
      ? '<missing>'
      : kind === 'file'
        ? '<not a regular file>'
        : '<not a directory>';
  throw new ResumeMismatchError(field, runDir, prior, `<expected ${kind}>`);
}

const REPR_LIMIT = 80;

function truncateRepr(text: string): string {
  const flat = text.replace(/\n/g, '\\n');
  return flat.length <= REPR_LIMIT ? flat : `${flat.slice(0, REPR_LIMIT)}...`;
}

async function checkTextMatch(
  filePath: string,
  expected: string,
  field: ResumeMismatchField,
  runDir: string,
): Promise<void> {
  const actual = await fs.readFile(filePath, 'utf-8');
  if (actual !== expected) {
    throw new ResumeMismatchError(field, runDir, truncateRepr(actual), truncateRepr(expected));
  }
}

async function validateSeedManifest(
  bare: Workspace,
  seedDir: string | undefined,
): Promise<SeedManifest | undefined> {
  const persisted = await fs.readFile(bare.seedManifestPath, 'utf-8').catch(() => undefined);
  if (seedDir === undefined) {
    if (persisted !== undefined) {
      throw new ResumeMismatchError(
        'seed_manifest',
        bare.runDir,
        '<seeded run>',
        '<artifactSeedDir is undefined>',
      );
    }
    return undefined;
  }
  if (persisted === undefined) {
    throw new ResumeMismatchError(
      'seed_manifest',
      bare.runDir,
      '<no .harness/seed_manifest.json>',
      '<artifactSeedDir is set>',
    );
  }
  let manifest: SeedManifest;
  try {
    manifest = parseSeedManifest(JSON.parse(persisted));
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new ResumeMismatchError(
      'seed_manifest',
      bare.runDir,
      `<unreadable: ${reason}>`,
      '<valid manifest>',
    );
  }
  await rejectSymlinks(seedDir);
  const fresh = await snapshotSeed(seedDir, await fs.readdir(seedDir));
  if (JSON.stringify(fresh) !== JSON.stringify(manifest)) {
    throw new ResumeMismatchError(
      'seed_manifest',
      bare.runDir,
      summariseManifest(manifest),
      summariseManifest(fresh),
    );
  }
  return manifest;
}

function summariseManifest(manifest: SeedManifest): string {
  return `<roots=${JSON.stringify(manifest.seededRoots)} files=${Object.keys(manifest.files).length}>`;
}
