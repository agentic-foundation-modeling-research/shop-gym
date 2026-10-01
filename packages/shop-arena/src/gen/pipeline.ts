/**
 * The `shopgym gen` pipeline: `manual_merge -> data_synth -> data_validation
 * -> build -> final_eval -> publish`, run by the core pipeline runner so
 * completion is derived from the shop directory and `from` forces a step
 * plus its dependents. `final_eval` and `publish` key off the build run's
 * `run.json` and `build.json`, so a resumed or rebuilt loop reruns both.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { type Step, type StepReport, runPipeline } from '@shop-gym/core';
import type { FinalStatus } from '@shop-gym/harness';

import { STOREFRONT_TEMPLATE_DIR } from '../templates.js';
import {
  BACKEND_DIRNAME,
  BUILD_JSON,
  type BuildLoopResult,
  DATA_DIRNAME,
  MANUAL_DIRNAME,
  STOREFRONT_DIRNAME,
  readBuildInfo,
  runBuildLoop,
} from './build/build_loop.js';
import { defaultBackendTemplateDir } from './build/seed.js';
import { BackendSidecar, freePort } from './build/sidecar.js';
import { StorefrontSidecar } from './build/storefront_sidecar.js';
import { type GenConfigInput, parseGenConfig } from './config.js';
import { type GenContext, type GenDeps, createGenContext } from './context.js';
import { DATA_DIR, dataSynthStep } from './data_synth/index.js';
import { DATA_VALIDATION_FILE, dataValidationStep } from './data_validation/index.js';
import { runFinalEval } from './final_eval/final_eval.js';
import { MANUAL_DIR, manualMergeStep } from './manual_merge/index.js';
import { SHOP_JSON, publishShop } from './publish/publish.js';

export const BUILD_RUN_DIR = path.join('runs', 'build');
export const FINAL_EVAL_DIR = 'final_eval';
const BUILD_SEED_DIR = path.join('.shop_gen', 'build_seed');
const BUILD_RUN_JSON = path.join(BUILD_RUN_DIR, 'run.json');
const BUILD_INFO_JSON = path.join(BUILD_RUN_DIR, BUILD_JSON);

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
  readonly finalEvalDir: string;
  /** `<shopDir>/shop.json`, written by `publish`. */
  readonly manifestPath: string;
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
    judge: { llm: c.llm, model: c.model },
    ...(c.onEvent !== undefined ? { onEvent: c.onEvent } : {}),
    ...(c.commandRunner !== undefined ? { commandRunner: c.commandRunner } : {}),
    ...(c.sidecarLaunch !== undefined ? { sidecarLaunch: c.sidecarLaunch } : {}),
    ...(c.storefrontLaunch !== undefined ? { storefrontLaunch: c.storefrontLaunch } : {}),
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

/**
 * Boot the built shop from the build run's artifacts (backend on the port
 * recorded in `build.json`, so the storefront's `.env` still matches) and
 * run the final eval against it. Logs go next to the report.
 */
async function runFinalEvalStep(ctx: {
  outDir: string;
  context: GenContext;
  log: (line: string) => void;
  signal: AbortSignal;
}): Promise<void> {
  const c = ctx.context;
  const runDir = path.join(ctx.outDir, BUILD_RUN_DIR);
  const build = await readBuildInfo(runDir);
  if (build === undefined) {
    throw new Error(`${BUILD_JSON} missing in ${runDir}; run the build step first`);
  }
  const artifactDir = path.join(runDir, 'artifact');
  const outDir = path.join(ctx.outDir, FINAL_EVAL_DIR);
  await fs.mkdir(outDir, { recursive: true });
  const backend = new BackendSidecar({
    backendDir: path.join(artifactDir, BACKEND_DIRNAME),
    dataDir: path.join(artifactDir, DATA_DIRNAME),
    port: build.backendPort,
    logPath: path.join(outDir, 'backend.log'),
    ...(c.sidecarLaunch !== undefined ? { launch: c.sidecarLaunch } : {}),
  });
  const storefront = new StorefrontSidecar({
    storefrontDir: path.join(artifactDir, STOREFRONT_DIRNAME),
    backendUrl: build.backendUrl,
    port: await freePort(),
    logPath: path.join(outDir, 'storefront.log'),
    ...(c.storefrontLaunch !== undefined ? { launch: c.storefrontLaunch } : {}),
  });
  await backend.start();
  try {
    await storefront.start();
    try {
      await runFinalEval({
        dataDir: path.join(artifactDir, DATA_DIRNAME),
        manualDir: path.join(artifactDir, MANUAL_DIRNAME),
        backendUrl: build.backendUrl,
        storefrontUrl: storefront.url,
        llm: c.llm,
        model: c.model,
        outDir,
        log: ctx.log,
        signal: ctx.signal,
      });
    } finally {
      await storefront.stop();
    }
  } finally {
    await backend.stop();
  }
}

export function finalEvalStep(): Step<GenContext> {
  return {
    id: 'final_eval',
    inputs: [BUILD_RUN_JSON, BUILD_INFO_JSON],
    outputs: [FINAL_EVAL_DIR],
    run: runFinalEvalStep,
  };
}

export function publishStep(): Step<GenContext> {
  return {
    id: 'publish',
    inputs: [BUILD_RUN_JSON, BUILD_INFO_JSON],
    outputs: [STOREFRONT_DIRNAME, BACKEND_DIRNAME, SHOP_JSON],
    run: async (ctx) => {
      const result = await publishShop({
        runDir: path.join(ctx.outDir, BUILD_RUN_DIR),
        shopDir: ctx.outDir,
      });
      ctx.log(`[publish] ${result.manifest.name}: ${result.manifestPath}`);
    },
  };
}

/** Steps in pipeline order. */
export function genSteps(ctx: GenContext): Step<GenContext>[] {
  return [
    manualMergeStep(ctx.manualDirs),
    dataSynthStep(),
    dataValidationStep(),
    buildStep(),
    finalEvalStep(),
    publishStep(),
  ];
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
    finalEvalDir: path.join(ctx.shopDir, FINAL_EVAL_DIR),
    manifestPath: path.join(ctx.shopDir, SHOP_JSON),
    reports,
  };
}
