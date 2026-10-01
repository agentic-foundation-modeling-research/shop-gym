/**
 * The `shopgym gen` pipeline: `manual_merge -> data_synth -> data_validation
 * -> build`, run by the core pipeline runner so completion is derived from
 * the shop directory and `from` forces a step plus its dependents.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { type Step, type StepReport, runPipeline } from '@shop-gym/core';
import type { FinalStatus } from '@shop-gym/harness';

import { STOREFRONT_TEMPLATE_DIR } from '../templates.js';
import { type BuildLoopResult, runBuildLoop } from './build/build_loop.js';
import { defaultBackendTemplateDir } from './build/seed.js';
import { type GenConfigInput, parseGenConfig } from './config.js';
import { type GenContext, type GenDeps, createGenContext } from './context.js';
import { DATA_DIR, dataSynthStep } from './data_synth/index.js';
import { DATA_VALIDATION_FILE, dataValidationStep } from './data_validation/index.js';
import { MANUAL_DIR, manualMergeStep } from './manual_merge/index.js';

export const BUILD_RUN_DIR = path.join('runs', 'build');
const BUILD_SEED_DIR = path.join('.shop_gen', 'build_seed');

/** The build loop ended in a status other than `completed`; rerun resumes it. */
export class BuildIncompleteError extends Error {
  constructor(
    readonly finalStatus: FinalStatus,
    readonly result: BuildLoopResult,
  ) {
    super(
      `build loop ended with status ${finalStatus} after ${result.execIterCount} executor iterations`,
    );
    this.name = 'BuildIncompleteError';
  }
}

export interface GenResult {
  readonly shopDir: string;
  readonly manualDir: string;
  readonly dataDir: string;
  readonly dataValidationPath: string;
  readonly buildRunDir: string;
  readonly reports: readonly StepReport[];
}

async function runBuild(ctx: {
  outDir: string;
  context: GenContext;
  log: (line: string) => void;
}): Promise<void> {
  const { config } = ctx.context;
  const seedDir = path.join(ctx.outDir, BUILD_SEED_DIR);
  await fs.rm(seedDir, { recursive: true, force: true });
  for (const dir of [DATA_DIR, MANUAL_DIR]) {
    await fs.cp(path.join(ctx.outDir, dir), path.join(seedDir, dir), { recursive: true });
  }
  const c = ctx.context;
  const result = await runBuildLoop({
    runDir: path.join(ctx.outDir, BUILD_RUN_DIR),
    seedDir,
    storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
    backendTemplateDir: defaultBackendTemplateDir(),
    genBackend: config.genBackend,
    runtime: c.runtime,
    model: c.buildModel,
    tools: c.tools,
    maxIters: config.maxIters,
    timeoutMs: config.buildTimeoutMs,
    force: config.forceResume,
    ...(c.onEvent !== undefined ? { onEvent: c.onEvent } : {}),
    ...(c.commandRunner !== undefined ? { commandRunner: c.commandRunner } : {}),
    ...(c.sidecarLaunch !== undefined ? { sidecarLaunch: c.sidecarLaunch } : {}),
    ...(c.introspect !== undefined ? { introspect: c.introspect } : {}),
  });
  ctx.log(
    `[build] ${result.finalStatus}: ${result.execIterCount} executor iterations, ${result.verifierRuns.length} verifier runs`,
  );
  if (result.finalStatus !== 'completed') {
    throw new BuildIncompleteError(result.finalStatus, result);
  }
}

export function buildStep(): Step<GenContext> {
  return {
    id: 'build',
    inputs: [DATA_DIR, MANUAL_DIR, DATA_VALIDATION_FILE],
    outputs: [BUILD_RUN_DIR],
    run: runBuild,
  };
}

/** Steps in pipeline order; `final_eval` and `publish` append here. */
export function genSteps(ctx: GenContext): Step<GenContext>[] {
  return [manualMergeStep(ctx.manualDirs), dataSynthStep(), dataValidationStep(), buildStep()];
}

/**
 * Generates a SandboxShop from one or more Shop Manuals.
 *
 * @throws z.ZodError when `input` is invalid.
 * @throws StepFailedError when a step fails; `cause` carries the step's error.
 */
export async function generateShop(input: GenConfigInput, deps: GenDeps): Promise<GenResult> {
  const config = parseGenConfig(input);
  const ctx = createGenContext(config, deps);
  const reports = await runPipeline(genSteps(ctx), {
    outDir: ctx.shopDir,
    context: ctx,
    ...(config.from !== undefined ? { from: config.from } : {}),
    ...(deps.log !== undefined ? { log: deps.log } : {}),
    ...(deps.signal !== undefined ? { signal: deps.signal } : {}),
  });
  return {
    shopDir: ctx.shopDir,
    manualDir: path.join(ctx.shopDir, MANUAL_DIR),
    dataDir: path.join(ctx.shopDir, DATA_DIR),
    dataValidationPath: path.join(ctx.shopDir, DATA_VALIDATION_FILE),
    buildRunDir: path.join(ctx.shopDir, BUILD_RUN_DIR),
    reports,
  };
}
