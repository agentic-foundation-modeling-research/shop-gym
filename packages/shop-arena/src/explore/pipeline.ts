/**
 * The explore pipeline: prefetch a storefront, run the plan-then-loop
 * harness with browser and file tools, merge the per-task fragments, and
 * synthesize the anonymized shop manual.
 *
 * Output layout under `outDir` (default
 * `outputs/shop_manuals/<domain>/<run_id>/`):
 *
 * ```
 * seed/prefetch/        prefetch.json + saved bodies (seeded into the run)
 * run/                  harness workspace (plan.md, iters/, artifact/, run.json)
 * explore.json          harness outcome of the explore step
 * capabilities.json     merged, schema-validated capabilities
 * stats.json            catalog and feature statistics
 * manifest.json         counts, omissions, conflicts, coverage gaps, paths
 * manual.md             the synthesized shop manual
 * .pipeline/            step records of the pipeline runner
 * ```
 *
 * Steps are `prefetch`, `explore`, `merge`, and `synthesize`. A complete
 * step is skipped on a later call with the same `outDir`; `from` forces a
 * step and everything downstream. The harness workspace under `run/` is
 * never deleted by the pipeline: an interrupted or forced explore step
 * resumes it, so the same `outDir` continues the same exploration.
 */

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  type AgentEvent,
  type AgentRuntime,
  type LlmClient,
  type ModelRef,
  PiLlmClient,
  PiRuntime,
} from '@shop-gym/agent';
import { BrowserSession, browserTools } from '@shop-gym/browser';
import { type Credentials, type Step, type StepReport, runPipeline } from '@shop-gym/core';
import { type FinalStatus, type RunSummary, runPlanExecLoop } from '@shop-gym/harness';

import { anonymizationVerifier } from './anonymization.js';
import {
  type Capabilities,
  type Conflict,
  capabilitiesJsonSchema,
  mergeFragments,
  parseCapabilities,
} from './capabilities.js';
import { coverageGaps, parsePlanCoverage } from './coverage.js';
import { fileTools } from './files.js';
import { type PrefetchReport, normalizeBase, prefetch } from './prefetch.js';
import { computeStats } from './stats.js';
import { renderManual } from './synthesize.js';

export const DEFAULT_MODEL = 'anthropic/claude-opus-4-7';
export const DEFAULT_MAX_ITERS = 20;
export const DEFAULT_TIMEOUT_MS = 1_800_000;
export const DEFAULT_OUTPUT_ROOT = join('outputs', 'shop_manuals');
export const EXPLORE_STEPS = ['prefetch', 'explore', 'merge', 'synthesize'] as const;

/** Bumped when the prompts or the output contract change shape. */
const EXPLORE_VERSION = '1.1';
const RUN_ID_HASH_LEN = 8;
const PROMPTS_DIR = fileURLToPath(new URL('./prompts/', import.meta.url));

export type ExploreStep = (typeof EXPLORE_STEPS)[number];

export interface ExploreOptions {
  /** Storefront URL; only scheme and host are used. */
  readonly url: string;
  /** Run directory. Defaults to `outputs/shop_manuals/<domain>/<run_id>` under the cwd. */
  readonly outDir?: string;
  /** `provider/model-id`, e.g. `anthropic/claude-opus-4-7`. */
  readonly model?: string;
  /** Executor iterations granted to the explore step. */
  readonly maxIters?: number;
  /** Per-iteration wall clock budget. */
  readonly timeoutMs?: number;
  /** Minimum gap between prefetch requests. Defaults to 500. */
  readonly rateLimitMs?: number;
  /** Force this step and everything after it. */
  readonly from?: ExploreStep;
  /** Resume a harness run that ended in a refused status. */
  readonly forceResume?: boolean;
  readonly credentials: Credentials;
  /** Overrides the pi runtime (tests). */
  readonly runtime?: AgentRuntime;
  /** Overrides the pi completion client (tests). */
  readonly llm?: LlmClient;
  readonly onEvent?: (iterId: string, event: AgentEvent) => void;
  readonly log?: (line: string) => void;
  readonly signal?: AbortSignal;
}

export interface ExploreResult {
  readonly outDir: string;
  readonly runDir: string;
  readonly prefetchDir: string;
  readonly manualPath: string;
  readonly capabilitiesPath: string;
  readonly statsPath: string;
  readonly manifestPath: string;
  readonly finalStatus: FinalStatus;
  readonly steps: readonly StepReport[];
}

/** The `explore.json` the explore step writes. */
export interface ExploreOutcome {
  readonly final_status: FinalStatus;
  readonly plan_iters: number;
  readonly exec_iters: number;
  readonly finished_at: string;
}

/** The `manifest.json` the merge step writes. */
export interface Manifest {
  readonly run_id: string;
  readonly domain: string;
  readonly runtime: string;
  readonly model: string;
  readonly harness_status: FinalStatus;
  readonly iters: { plan: number; exec: number };
  readonly plan_tasks_total: number;
  readonly plan_tasks_done: number;
  readonly plan_tasks_blocked: number;
  readonly omitted_areas: readonly { area: string; reason: string }[];
  readonly capability_conflicts: readonly Conflict[];
  readonly coverage_gaps: readonly string[];
  readonly merged_at: string;
  readonly paths: {
    manual: string;
    capabilities: string;
    stats: string;
    manifest: string;
    prefetch: string;
    run: string;
  };
}

interface Prompts {
  readonly agents: string;
  readonly planner: string;
  readonly execute: string;
  readonly manual: string;
}

interface ExploreContext {
  readonly url: string;
  readonly model: ModelRef;
  readonly modelName: string;
  readonly maxIters: number;
  readonly timeoutMs: number;
  readonly rateLimitMs: number | undefined;
  readonly forceResume: boolean;
  readonly runtime: AgentRuntime;
  readonly llm: LlmClient;
  readonly prompts: Prompts;
  readonly onEvent: ((iterId: string, event: AgentEvent) => void) | undefined;
}

const PATHS = {
  prefetch: join('seed', 'prefetch'),
  seed: 'seed',
  run: 'run',
  explore: 'explore.json',
  capabilities: 'capabilities.json',
  stats: 'stats.json',
  manifest: 'manifest.json',
  manual: 'manual.md',
} as const;

/** Splits `provider/model-id` into a `ModelRef`. */
export function parseModel(model: string): ModelRef {
  const slash = model.indexOf('/');
  if (slash <= 0 || slash === model.length - 1) {
    throw new Error(`model must be "provider/model-id", got ${JSON.stringify(model)}`);
  }
  return { provider: model.slice(0, slash), id: model.slice(slash + 1) };
}

/** `<UTC timestamp>-<8 hex of sha256(url|runtime|version)>`. */
export function runId(url: string, runtimeName: string, now: Date = new Date()): string {
  const stamp = now
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}Z$/, 'Z');
  const digest = createHash('sha256')
    .update(`${url}|${runtimeName}|${EXPLORE_VERSION}`)
    .digest('hex')
    .slice(0, RUN_ID_HASH_LEN);
  return `${stamp}-${digest}`;
}

function loadPrompts(): Prompts {
  const read = (name: string) => readFileSync(join(PROMPTS_DIR, name), 'utf8');
  return {
    agents: read('agents.md').replace('{{CAPABILITIES_SCHEMA}}', capabilitiesJsonSchema()),
    planner: read('planner.md'),
    execute: read('execute.md'),
    manual: read('synthesize_manual.md'),
  };
}

function writeJson(path: string, value: unknown): void {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, 'utf8')) as T;
}

function readRunSummary(runDir: string): RunSummary | undefined {
  const path = join(runDir, 'run.json');
  return existsSync(path) ? readJson<RunSummary>(path) : undefined;
}

const prefetchStep: Step<ExploreContext> = {
  id: 'prefetch',
  inputs: [],
  outputs: [PATHS.prefetch],
  async run({ outDir, context, log }) {
    const report: PrefetchReport = await prefetch(
      context.url,
      join(outDir, PATHS.prefetch),
      context.rateLimitMs === undefined ? {} : { rateLimitMs: context.rateLimitMs },
    );
    log(`prefetched ${report.entries.length} URLs from ${report.base_url}`);
  },
};

const exploreStep: Step<ExploreContext> = {
  id: 'explore',
  inputs: [PATHS.prefetch],
  outputs: [PATHS.explore],
  async run({ outDir, context, log }) {
    const runDir = join(outDir, PATHS.run);
    const session = await BrowserSession.launch({ episodeId: basename(outDir) });
    let summary: Awaited<ReturnType<typeof runPlanExecLoop>>;
    try {
      summary = await runPlanExecLoop(
        {
          runDir,
          prompts: { planner: context.prompts.planner, execute: context.prompts.execute },
          agentsMd: context.prompts.agents,
          artifactSeedDir: join(outDir, PATHS.seed),
          maxIters: context.maxIters,
          timeoutMs: context.timeoutMs,
          model: context.model,
          tools: [...browserTools(session), ...fileTools()],
          verifiers: [anonymizationVerifier(context.url)],
          ...(context.onEvent ? { onEvent: context.onEvent } : {}),
        },
        context.runtime,
        { force: context.forceResume },
      );
    } finally {
      await session.close();
    }
    log(`harness finished: ${summary.finalStatus} (${summary.execIterCount} executor iterations)`);
    const outcome: ExploreOutcome = {
      final_status: summary.finalStatus,
      plan_iters: summary.planIterCount,
      exec_iters: summary.execIterCount,
      finished_at: new Date().toISOString(),
    };
    writeJson(join(outDir, PATHS.explore), outcome);
  },
};

const mergeStep: Step<ExploreContext> = {
  id: 'merge',
  inputs: [PATHS.explore, PATHS.prefetch, join(PATHS.run, 'plan.md')],
  outputs: [PATHS.capabilities, PATHS.stats, PATHS.manifest],
  async run({ outDir, context, log }) {
    const runDir = join(outDir, PATHS.run);
    const partsDir = join(runDir, 'artifact', 'parts');
    const prefetchDir = join(outDir, PATHS.prefetch);
    const outcome = readJson<ExploreOutcome>(join(outDir, PATHS.explore));
    const planMd = readFileSync(join(runDir, 'plan.md'), 'utf8');

    const { capabilities, conflicts } = existsSync(partsDir)
      ? mergeFragments(partsDir)
      : { capabilities: parseCapabilities({}), conflicts: [] };
    writeJson(join(outDir, PATHS.capabilities), capabilities);
    writeJson(join(outDir, PATHS.stats), computeStats(prefetchDir, capabilities));

    const summary = readRunSummary(runDir);
    const tasks = summary?.tasksFinal ?? [];
    const omitted = [...parsePlanCoverage(planMd).omitted].map((entry) => ({
      area: entry,
      reason: omissionReason(planMd, entry),
    }));
    const manifest: Manifest = {
      run_id: basename(outDir),
      domain: new URL(context.url).hostname,
      runtime: context.runtime.name,
      model: context.modelName,
      harness_status: outcome.final_status,
      iters: { plan: outcome.plan_iters, exec: outcome.exec_iters },
      plan_tasks_total: tasks.length,
      plan_tasks_done: tasks.filter((task) => task.status === 'done').length,
      plan_tasks_blocked: tasks.filter((task) => task.status === 'blocked').length,
      omitted_areas: omitted,
      capability_conflicts: conflicts,
      coverage_gaps: coverageGaps(prefetchDir, planMd),
      merged_at: new Date().toISOString(),
      paths: {
        manual: PATHS.manual,
        capabilities: PATHS.capabilities,
        stats: PATHS.stats,
        manifest: PATHS.manifest,
        prefetch: PATHS.prefetch,
        run: PATHS.run,
      },
    };
    writeJson(join(outDir, PATHS.manifest), manifest);
    log(
      `merged ${tasks.length} tasks: ${conflicts.length} conflicts, ${manifest.coverage_gaps.length} coverage gaps`,
    );
  },
};

/** The reason text after `- <area> - ` in the `## Omitted Areas` block. */
function omissionReason(planMd: string, area: string): string {
  for (const line of planMd.split(/\r?\n/)) {
    const stripped = line.trim();
    if (!stripped.startsWith(`- ${area}`)) continue;
    const match = /^- \S+\s+(?:-|—)\s+(.*)$/.exec(stripped);
    return match?.[1]?.trim() ?? '';
  }
  return '';
}

const synthesizeStep: Step<ExploreContext> = {
  id: 'synthesize',
  inputs: [PATHS.capabilities],
  outputs: [PATHS.manual],
  async run({ outDir, context, log, signal }) {
    const partsDir = join(outDir, PATHS.run, 'artifact', 'parts');
    mkdirSync(partsDir, { recursive: true });
    const capabilities: Capabilities = parseCapabilities(
      readJson(join(outDir, PATHS.capabilities)),
    );
    const manual = await renderManual(
      context.llm,
      context.model,
      context.prompts.manual,
      capabilities,
      partsDir,
      signal,
    );
    writeFileSync(join(outDir, PATHS.manual), manual);
    log(`wrote manual.md (${manual.length} chars)`);
  },
};

const STEPS: readonly Step<ExploreContext>[] = [
  prefetchStep,
  exploreStep,
  mergeStep,
  synthesizeStep,
];

/**
 * Explores a storefront end to end and returns the output paths.
 *
 * Calling again with the same `outDir` skips complete steps and resumes
 * an unfinished harness run; `from` forces a step and its dependents.
 *
 * @throws ShopUnreachableError when the prefetch gates reject the shop.
 * @throws ResumeRefusedError when the prior harness run ended in a
 *   refused status and `forceResume` is not set.
 */
export async function exploreStorefront(options: ExploreOptions): Promise<ExploreResult> {
  const base = normalizeBase(options.url);
  const runtime = options.runtime ?? new PiRuntime({ credentials: options.credentials });
  const llm = options.llm ?? new PiLlmClient({ credentials: options.credentials });
  const modelName = options.model ?? DEFAULT_MODEL;
  const domain = new URL(base).hostname;
  const outDir = resolve(
    options.outDir ?? join(DEFAULT_OUTPUT_ROOT, domain, runId(base, runtime.name)),
  );
  const context: ExploreContext = {
    url: base,
    model: parseModel(modelName),
    modelName,
    maxIters: options.maxIters ?? DEFAULT_MAX_ITERS,
    timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    rateLimitMs: options.rateLimitMs,
    forceResume: options.forceResume ?? false,
    runtime,
    llm,
    prompts: loadPrompts(),
    onEvent: options.onEvent,
  };
  const steps = await runPipeline(STEPS, {
    outDir,
    context,
    ...(options.from ? { from: options.from } : {}),
    ...(options.log ? { log: options.log } : {}),
    ...(options.signal ? { signal: options.signal } : {}),
  });
  const outcome = readJson<ExploreOutcome>(join(outDir, PATHS.explore));
  return {
    outDir,
    runDir: join(outDir, PATHS.run),
    prefetchDir: join(outDir, PATHS.prefetch),
    manualPath: join(outDir, PATHS.manual),
    capabilitiesPath: join(outDir, PATHS.capabilities),
    statsPath: join(outDir, PATHS.stats),
    manifestPath: join(outDir, PATHS.manifest),
    finalStatus: outcome.final_status,
    steps,
  };
}
