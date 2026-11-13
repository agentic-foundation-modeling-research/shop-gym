/**
 * `manual_merge` step: turns one or more Shop Manual directories into
 * `<shopDir>/manual/` (`manual.md`, `capabilities.json`, `stats.json`,
 * `parts/<area>.md`, `manifest.json`, and `site_graph.json` when the
 * manual has one).
 *
 * A single manual is copied byte for byte and split; its Site state graph,
 * when it has one, is checked and copied too. Several manuals are merged
 * (deterministic capability rules with LLM tiebreaks, LLM prose merge per
 * shared section, numeric stats merge); their graphs are not merged, so
 * the Merged manual has no graph. Every shop also gets the
 * checked-in Standard sub-manual as `parts/standard.md`, with the Merged
 * manual's observed Account and Checkout notes fused into it (no LLM call
 * and no change when there are none).
 */

import { existsSync } from 'node:fs';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { type Step, type StepContext, parseSiteGraph } from '@shop-gym/core';
import { z } from 'zod';

import { parseCapabilities } from '../../explore/capabilities.js';
import type { GenContext } from '../context.js';
import { exists, readJsonFile, writeJsonFile, writeTextFile } from '../io.js';
import { type LlmCall, completeText, loadPrompt } from '../llm.js';
import { type MergeConflict, type Tiebreaker, mergeCapabilities } from './capabilities.js';
import { fuseStandardSubManual } from './fusion.js';
import { mergeManualProse, seedBlocks } from './prose.js';
import { MANUAL_PARTS, splitManual } from './split.js';
import { STANDARD_SUB_MANUAL_FILE, STANDARD_SUB_MANUAL_PATH } from './standard_sub_manual.js';
import { type SeedStats, mergeStats, statsSchema } from './stats.js';

export {
  type CapabilitiesMerge,
  MERGE_RULES,
  type MergeConflict,
  type MergeRule,
  type Tiebreaker,
  mergeCapabilities,
} from './capabilities.js';
export { fuseStandardSubManual } from './fusion.js';
export { CANONICAL_SECTIONS, mergeManualProse, parseManualSections } from './prose.js';
export { MANUAL_PARTS, type ManualPart, splitManual } from './split.js';
export { FUSED_SECTIONS } from './standard_sub_manual.js';
export { type SeedStats, mergeStats, statsSchema } from './stats.js';

export const MANUAL_DIR = 'manual';
const PROMPTS_DIR = fileURLToPath(new URL('./prompts/', import.meta.url));
const SEED_FILES = ['manual.md', 'capabilities.json', 'stats.json'] as const;
/** The Site state graph of a Shop Manual. A manual may have none. */
export const SITE_GRAPH_FILE = 'site_graph.json';

/** `manual/manifest.json`. */
export interface ManualManifest {
  readonly schemaVersion: 1;
  readonly seeds: readonly string[];
  readonly capabilityConflicts: readonly MergeConflict[];
  readonly paths: Readonly<Record<'manual' | 'capabilities' | 'stats' | 'parts', string>>;
  readonly synthesizedAt: string;
}

function llmTiebreaker(call: LlmCall): Tiebreaker {
  return {
    descriptor: (tone, descriptors) =>
      completeText(
        call,
        loadPrompt(PROMPTS_DIR, 'tiebreak_descriptor', {
          tone: tone.length > 0 ? tone.join(', ') : '(none)',
          descriptors: descriptors.map((d) => `- ${d}`).join('\n'),
        }),
      ),
    layout: (leaf, candidates, descriptor) =>
      completeText(
        call,
        loadPrompt(PROMPTS_DIR, 'tiebreak_layout', {
          path: leaf,
          candidates: candidates.join(', '),
          descriptor,
        }),
      ),
  };
}

async function mergeManuals(
  ctx: StepContext<GenContext>,
  call: LlmCall,
  manualDir: string,
): Promise<readonly MergeConflict[]> {
  const dirs = ctx.context.manualDirs;
  const rawCapabilities = await Promise.all(
    dirs.map((dir) => readJsonFile(path.join(dir, 'capabilities.json'), z.unknown())),
  );
  const { capabilities, conflicts } = await mergeCapabilities(rawCapabilities, llmTiebreaker(call));
  ctx.log(`[manual_merge] merged capabilities with ${conflicts.length} conflict(s)`);

  const manuals = await Promise.all(
    dirs.map((dir) => fs.readFile(path.join(dir, 'manual.md'), 'utf-8')),
  );
  const capabilitiesJson = JSON.stringify(capabilities, null, 2);
  const manual = await mergeManualProse(
    manuals,
    capabilities.shop.descriptor,
    (section, contributions) =>
      completeText(
        call,
        loadPrompt(PROMPTS_DIR, 'merge_manual_prose', {
          section,
          capabilities: capabilitiesJson,
          seed_blocks: seedBlocks(contributions),
        }),
      ),
  );
  const seedStats: SeedStats[] = await Promise.all(
    dirs.map((dir) => readJsonFile(path.join(dir, 'stats.json'), statsSchema)),
  );
  await writeJsonFile(path.join(manualDir, 'capabilities.json'), capabilities);
  await writeTextFile(path.join(manualDir, 'manual.md'), manual);
  await writeJsonFile(path.join(manualDir, 'stats.json'), mergeStats(seedStats, capabilities));
  return conflicts;
}

async function copyManual(seedDir: string, manualDir: string): Promise<void> {
  await fs.mkdir(manualDir, { recursive: true });
  for (const name of SEED_FILES) {
    await fs.copyFile(path.join(seedDir, name), path.join(manualDir, name));
  }
  parseCapabilities(
    JSON.parse(await fs.readFile(path.join(manualDir, 'capabilities.json'), 'utf-8')),
  );
  const graphFile = path.join(seedDir, SITE_GRAPH_FILE);
  if (await exists(graphFile)) {
    parseSiteGraph(JSON.parse(await fs.readFile(graphFile, 'utf-8')));
    await fs.copyFile(graphFile, path.join(manualDir, SITE_GRAPH_FILE));
  }
}

export async function runManualMerge(ctx: StepContext<GenContext>): Promise<void> {
  const manualDir = path.join(ctx.outDir, MANUAL_DIR);
  await fs.rm(manualDir, { recursive: true, force: true });
  const call: LlmCall = {
    llm: ctx.context.llm,
    model: ctx.context.model,
    timeoutMs: ctx.context.config.llmTimeoutMs,
    signal: ctx.signal,
  };
  let conflicts: readonly MergeConflict[] = [];
  const [single] = ctx.context.manualDirs;
  if (ctx.context.manualDirs.length === 1 && single !== undefined) {
    await copyManual(single, manualDir);
  } else {
    conflicts = await mergeManuals(ctx, call, manualDir);
    const graphs = ctx.context.manualDirs.filter((dir) =>
      existsSync(path.join(dir, SITE_GRAPH_FILE)),
    );
    if (graphs.length > 0) {
      ctx.log(
        `[manual_merge] ${graphs.length} ${SITE_GRAPH_FILE} file(s) not merged: the Merged manual has no Site state graph`,
      );
    }
  }
  const manual = await fs.readFile(path.join(manualDir, 'manual.md'), 'utf-8');
  const parts = splitManual(manual, ctx.log);
  for (const part of MANUAL_PARTS) {
    await writeTextFile(path.join(manualDir, 'parts', `${part}.md`), parts[part]);
  }
  await writeTextFile(
    path.join(manualDir, 'parts', STANDARD_SUB_MANUAL_FILE),
    await fuseStandardSubManual(
      call,
      await fs.readFile(STANDARD_SUB_MANUAL_PATH, 'utf-8'),
      manual,
      ctx.log,
    ),
  );
  const manifest: ManualManifest = {
    schemaVersion: 1,
    seeds: ctx.context.manualDirs,
    capabilityConflicts: conflicts,
    paths: {
      manual: 'manual/manual.md',
      capabilities: 'manual/capabilities.json',
      stats: 'manual/stats.json',
      parts: 'manual/parts',
    },
    synthesizedAt: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
  };
  await writeJsonFile(path.join(manualDir, 'manifest.json'), manifest);
}

/**
 * The `manual_merge` step. Its inputs are the seed files of each manual,
 * the Site state graph of each manual that has one when the step is made,
 * and the Standard sub-manual.
 */
export function manualMergeStep(manualDirs: readonly string[]): Step<GenContext> {
  return {
    id: 'manual_merge',
    inputs: [
      ...manualDirs.flatMap((dir) => [
        ...SEED_FILES.map((name) => path.join(dir, name)),
        ...(existsSync(path.join(dir, SITE_GRAPH_FILE)) ? [path.join(dir, SITE_GRAPH_FILE)] : []),
      ]),
      STANDARD_SUB_MANUAL_PATH,
    ],
    outputs: [MANUAL_DIR],
    run: runManualMerge,
  };
}
