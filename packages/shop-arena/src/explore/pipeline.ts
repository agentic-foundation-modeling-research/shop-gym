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
 * run/iters/<id>/start_state.json   where the Iteration's fresh browser started
 * focus.json            the focus that the planner got, written by the explore step
 * explore.json          harness outcome of the explore step
 * capabilities.json     merged, schema-validated capabilities
 * stats.json            catalog and feature statistics
 * manifest.json         counts, omissions, conflicts, coverage and fixed area gaps, paths
 * manual.md             the synthesized shop manual
 * site_graph.json       the Site state graph, from the finished parts and their actions
 * brand_terms.json      the brand terms of the run (never published)
 * .pipeline/            step records of the pipeline runner
 * ```
 *
 * Steps are `prefetch`, `explore`, `merge`, `synthesize`, and `graph`. A complete
 * step is skipped on a later call with the same `outDir`; `from` forces a
 * step and everything downstream. The harness workspace under `run/` is
 * never deleted by the pipeline: an interrupted or forced explore step
 * resumes it, so the same `outDir` continues the same exploration. For
 * the same reason a later call must pass the focus of the first call.
 *
 * The synthesize step ends with the final Anonymization scan of the
 * published files (`manual.md`, `capabilities.json`, `stats.json`): a
 * brand token, a brand term or the storefront host in them fails the
 * step, and `manual.md` is not written. The graph step runs the same scan
 * on the graph before it writes `site_graph.json`. Synthesize and graph
 * are two branches after merge: neither reads the output of the other.
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
import { type Credentials, type Step, type StepReport, runPipeline } from '@shop-gym/core';
import {
  type FinalStatus,
  InvalidPlanError,
  PLAN_ITER_ID,
  type RunSummary,
  type TaskList,
  iterDirPath,
  parse,
  runPlanExecLoop,
} from '@shop-gym/harness';
import { z } from 'zod';

import {
  AnonymizationLeakError,
  type LeakScanner,
  anonymizationVerifier,
  checkBrandTerms,
  leakScanner,
  publishedLeaks,
} from './anonymization.js';
import { IterationBrowser, START_STATE_FILENAME, parseCart } from './browser.js';
import {
  type Capabilities,
  type Conflict,
  capabilitiesJsonSchema,
  mergeFragments,
  parseCapabilities,
} from './capabilities.js';
import { type FixedAreaGap, coverageGaps, fixedAreaGaps, parseOmittedAreas } from './coverage.js';
import { fileTools } from './files.js';
import { readFinishedParts, renderSiteGraph } from './graph.js';
import {
  productObservationJsonSchema,
  productObservationTool,
  productObservationVerifier,
} from './observations.js';
import {
  type Platform,
  type PrefetchReport,
  normalizeBase,
  prefetch,
  readPlatform,
} from './prefetch.js';
import { computeObservedStats, computeStats } from './stats.js';
import { renderManual } from './synthesize.js';

export const DEFAULT_MODEL = 'anthropic/claude-opus-4-7';
export const DEFAULT_MAX_ITERS = 20;
export const DEFAULT_TIMEOUT_MS = 1_800_000;
export const DEFAULT_OUTPUT_ROOT = join('outputs', 'shop_manuals');
export const EXPLORE_STEPS = ['prefetch', 'explore', 'merge', 'synthesize', 'graph'] as const;

/** Bumped when the prompts or the output contract change shape. */
const EXPLORE_VERSION = '1.3';
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
  /**
   * One part of the site to explore, for example the department "Video
   * Games". The planner gets it as a hint for its start URLs, product
   * pages and search queries, and still plans the site-wide areas.
   * Navigation outside the focus is not blocked.
   */
  readonly focus?: string;
  /**
   * Brand words or phrases, such as sub-brands, that the Shop Manual must
   * not name, in addition to the brand tokens from the homepage. They
   * replace the terms that a prior call stored in `outDir`; when not given,
   * the stored terms are used again.
   */
  readonly brandTerms?: readonly string[];
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
  readonly siteGraphPath: string;
  readonly finalStatus: FinalStatus;
  /** Why the explore step stopped the run, or `null` when it did not. */
  readonly stop: ExploreStop | null;
  readonly steps: readonly StepReport[];
}

/** Why the explore step stopped the harness run early. */
export type ExploreStopReason = 'bot_check' | 'navigation_cap';

/** A harness run that the explore step stopped after Iteration `iteration`. */
export interface ExploreStop {
  readonly reason: ExploreStopReason;
  /** `plan` or `exec-NNNN`. */
  readonly iteration: string;
}

/** The `explore.json` the explore step writes. */
export interface ExploreOutcome {
  readonly final_status: FinalStatus;
  readonly plan_iters: number;
  readonly exec_iters: number;
  /** `null` when the explore step did not stop the run. Absent in older files. */
  readonly stop?: ExploreStop | null;
  readonly finished_at: string;
}

/** The `manifest.json` the merge step writes. */
export interface Manifest {
  readonly run_id: string;
  readonly domain: string;
  readonly runtime: string;
  readonly model: string;
  /** The prefetch path that the run took. */
  readonly platform: Platform;
  /** The focus hint of the run, or `null` when the run has none. */
  readonly focus: string | null;
  readonly harness_status: FinalStatus;
  readonly iters: { plan: number; exec: number };
  readonly plan_tasks_total: number;
  readonly plan_tasks_done: number;
  readonly plan_tasks_blocked: number;
  readonly omitted_areas: readonly { area: string; reason: string }[];
  readonly capability_conflicts: readonly Conflict[];
  readonly coverage_gaps: readonly string[];
  /** Each fixed area whose Plan task did not end done, with a one-line reason. */
  readonly fixed_area_gaps: readonly FixedAreaGap[];
  /** The early stop of the run, with the ids of its blocked Plan tasks; `null` when the run did not stop early. */
  readonly stop: (ExploreStop & { readonly blocked_tasks: readonly string[] }) | null;
  readonly merged_at: string;
  readonly paths: {
    manual: string;
    capabilities: string;
    stats: string;
    manifest: string;
    site_graph: string;
    prefetch: string;
    run: string;
  };
}

interface Prompts {
  readonly agents: string;
  readonly planner: string;
  /** The planner prompt for a site on the generic platform. */
  readonly plannerGeneric: string;
  /** The hint added to either planner prompt when the run has a focus. */
  readonly plannerFocus: string;
  readonly execute: string;
  /** The executor prompt for a site on the generic platform. */
  readonly executeGeneric: string;
  readonly manual: string;
  readonly graph: string;
}

interface ExploreContext {
  readonly url: string;
  readonly model: ModelRef;
  readonly modelName: string;
  readonly maxIters: number;
  readonly timeoutMs: number;
  readonly rateLimitMs: number | undefined;
  readonly forceResume: boolean;
  readonly focus: string | null;
  readonly brandTerms: readonly string[];
  readonly runtime: AgentRuntime;
  readonly llm: LlmClient;
  readonly prompts: Prompts;
  readonly onEvent: ((iterId: string, event: AgentEvent) => void) | undefined;
}

const PATHS = {
  prefetch: join('seed', 'prefetch'),
  seed: 'seed',
  run: 'run',
  focus: 'focus.json',
  explore: 'explore.json',
  capabilities: 'capabilities.json',
  stats: 'stats.json',
  manifest: 'manifest.json',
  manual: 'manual.md',
  siteGraph: 'site_graph.json',
  brandTerms: 'brand_terms.json',
} as const;

/** Shape of `brand_terms.json`. */
const BRAND_TERMS_SCHEMA = z.array(z.string());

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
    agents: read('agents.md')
      .replace('{{CAPABILITIES_SCHEMA}}', capabilitiesJsonSchema())
      // A replacer function, because the schema text contains `$`.
      .replace('{{PRODUCT_OBSERVATION_SCHEMA}}', () => productObservationJsonSchema()),
    planner: read('planner.md'),
    plannerGeneric: read('planner_generic.md'),
    plannerFocus: read('planner_focus.md'),
    execute: read('execute.md'),
    executeGeneric: read('execute_generic.md'),
    manual: read('synthesize_manual.md'),
    graph: read('site_graph.md'),
  };
}

/** The planner prompt for a site on `platform`, then the focus hint when there is a focus. */
function plannerPrompt(prompts: Prompts, platform: Platform, focus: string | null): string {
  const planner = platform === 'generic' ? prompts.plannerGeneric : prompts.planner;
  if (focus === null) return planner;
  // A function replacement inserts the text as is, so `$&` in it is not a pattern.
  return `${planner}\n${prompts.plannerFocus.replaceAll('{{FOCUS}}', () => focus)}`;
}

/** The executor prompt for a site on `platform`. */
function executePrompt(prompts: Prompts, platform: Platform): string {
  return platform === 'generic' ? prompts.executeGeneric : prompts.execute;
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

/** `focus "<text>"`, or `no focus`. */
function describeFocus(focus: string | null): string {
  return focus === null ? 'no focus' : `focus ${JSON.stringify(focus)}`;
}

/**
 * Checks `focus` against `<outDir>/focus.json`, which the explore step
 * writes before the harness runs. A later call must pass the same focus:
 * a resumed harness run keeps the plan of its first planner, so a new
 * focus would not reach the plan.
 *
 * @throws Error when `focus` differs from the recorded focus.
 */
function checkFocus(outDir: string, focus: string | null): void {
  const path = join(outDir, PATHS.focus);
  if (!existsSync(path)) return;
  const recorded = readJson<{ focus: string | null }>(path).focus;
  if (recorded !== focus) {
    const want = describeFocus(recorded);
    const got = describeFocus(focus);
    throw new Error(
      `${outDir} started with ${want}, got ${got}; pass the same focus or a new outDir`,
    );
  }
}

/**
 * The Plan tasks as the planner wrote them: the `plan.after.md` snapshot
 * of the planner iteration. Empty when the planner wrote no valid plan.
 */
function readPlannedTasks(runDir: string): TaskList {
  const path = join(iterDirPath(join(runDir, 'iters'), PLAN_ITER_ID), 'plan.after.md');
  if (!existsSync(path)) return [];
  try {
    return parse(readFileSync(path, 'utf8'));
  } catch (error) {
    if (error instanceof InvalidPlanError) return [];
    throw error;
  }
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
    log(
      `prefetched ${report.entries.length} URLs from ${report.base_url} (platform: ${report.platform})`,
    );
  },
};

const exploreStep: Step<ExploreContext> = {
  id: 'explore',
  inputs: [PATHS.prefetch],
  outputs: [PATHS.explore],
  async run({ outDir, context, log }) {
    const runDir = join(outDir, PATHS.run);
    const platform = readPlatform(join(outDir, PATHS.prefetch));
    const generic = platform === 'generic';
    const planner = plannerPrompt(context.prompts, platform, context.focus);
    writeJson(join(outDir, PATHS.focus), { focus: context.focus });
    const browser = await IterationBrowser.launch({
      episodeId: basename(outDir),
      baseUrl: context.url,
      startUrl: `${context.url}/`,
      ...(servesCart(join(outDir, PATHS.prefetch)) ? { cartUrl: `${context.url}/cart.js` } : {}),
    });
    let stop: ExploreStop | null = null;
    let botCheckStreak = 0;
    let summary: Awaited<ReturnType<typeof runPlanExecLoop>>;
    try {
      summary = await runPlanExecLoop(
        {
          runDir,
          prompts: { planner, execute: executePrompt(context.prompts, platform) },
          agentsMd: context.prompts.agents,
          artifactSeedDir: join(outDir, PATHS.seed),
          maxIters: context.maxIters,
          timeoutMs: context.timeoutMs,
          model: context.model,
          tools: [
            ...browser.tools,
            ...fileTools(),
            ...(generic ? [productObservationTool(browser)] : []),
          ],
          verifiers: [
            anonymizationVerifier(context.url, context.brandTerms),
            ...(generic ? [productObservationVerifier()] : []),
          ],
          ...(context.onEvent ? { onEvent: context.onEvent } : {}),
          onIterationStart: async ({ iterDir }) =>
            writeJson(join(iterDir, START_STATE_FILENAME), await browser.start()),
          onIterationEnd: async ({ iterId }) => {
            botCheckStreak = browser.botCheck === null ? 0 : botCheckStreak + 1;
            const reason = stopReason(botCheckStreak, browser.navigationCapReached);
            if (reason === null) return;
            stop = { reason, iteration: iterId };
            log(`asking the harness to stop the run after ${iterId}: ${reason}`);
            return { stopReason: reason };
          },
        },
        context.runtime,
        { force: context.forceResume },
      );
    } finally {
      await browser.close();
    }
    log(`harness finished: ${summary.finalStatus} (${summary.execIterCount} executor iterations)`);
    const outcome: ExploreOutcome = {
      final_status: summary.finalStatus,
      plan_iters: summary.planIterCount,
      exec_iters: summary.execIterCount,
      // The harness ignores a stop after an iteration that failed the run.
      stop: summary.finalStatus === 'stopped' ? stop : null,
      finished_at: new Date().toISOString(),
    };
    writeJson(join(outDir, PATHS.explore), outcome);
  },
};

/** Iterations in a row with a bot check that stop the run. */
const BOT_CHECK_STOP_STREAK = 2;

/**
 * Why the run stops after an Iteration, or `null` when it goes on.
 * `botCheckStreak` counts the Iterations in a row, up to this one, that
 * came to a bot-check page.
 */
function stopReason(
  botCheckStreak: number,
  navigationCapReached: boolean,
): ExploreStopReason | null {
  if (botCheckStreak >= BOT_CHECK_STOP_STREAK) return 'bot_check';
  if (navigationCapReached) return 'navigation_cap';
  return null;
}

/** True when prefetch saved a `/cart.js` body that parses as a cart. */
function servesCart(prefetchDir: string): boolean {
  const path = join(prefetchDir, 'cart.js');
  return existsSync(path) && parseCart(readFileSync(path, 'utf8')) !== null;
}

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
    const platform = readPlatform(prefetchDir);

    const { capabilities, conflicts } = existsSync(partsDir)
      ? mergeFragments(partsDir)
      : { capabilities: parseCapabilities({}), conflicts: [] };
    writeJson(join(outDir, PATHS.capabilities), capabilities);
    writeJson(
      join(outDir, PATHS.stats),
      platform === 'generic'
        ? computeObservedStats(partsDir, capabilities)
        : computeStats(prefetchDir, capabilities),
    );

    const summary = readRunSummary(runDir);
    const tasks = summary?.tasksFinal ?? [];
    const stop = outcome.stop ?? null;
    const blockedTasks = tasks.filter((task) => task.status === 'blocked').map((task) => task.id);
    const omittedAreas = parseOmittedAreas(planMd);
    const omitted = [...omittedAreas].map((entry) => ({
      area: entry,
      reason: omissionReason(planMd, entry),
    }));
    const manifest: Manifest = {
      run_id: basename(outDir),
      domain: new URL(context.url).hostname,
      runtime: context.runtime.name,
      model: context.modelName,
      platform,
      focus: context.focus,
      harness_status: outcome.final_status,
      iters: { plan: outcome.plan_iters, exec: outcome.exec_iters },
      plan_tasks_total: tasks.length,
      plan_tasks_done: tasks.filter((task) => task.status === 'done').length,
      plan_tasks_blocked: blockedTasks.length,
      omitted_areas: omitted,
      capability_conflicts: conflicts,
      coverage_gaps: coverageGaps(prefetchDir, tasks, omittedAreas),
      fixed_area_gaps: fixedAreaGaps(tasks, readPlannedTasks(runDir)),
      stop: stop === null ? null : { ...stop, blocked_tasks: blockedTasks },
      merged_at: new Date().toISOString(),
      paths: {
        manual: PATHS.manual,
        capabilities: PATHS.capabilities,
        stats: PATHS.stats,
        manifest: PATHS.manifest,
        site_graph: PATHS.siteGraph,
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

/**
 * The Anonymization scan of the published files: the storefront host, the
 * brand tokens of the prefetched homepage, and the Brand terms of the run.
 */
function publishedFileScanner(outDir: string, context: ExploreContext): LeakScanner {
  // Prefetch saves no homepage when `/` answers with an empty body or a
  // success status other than 200; then no title gives brand tokens.
  const homepagePath = join(outDir, PATHS.prefetch, 'index.html');
  return leakScanner(
    new URL(context.url).hostname,
    existsSync(homepagePath) ? readFileSync(homepagePath, 'utf8') : '',
    context.brandTerms,
  );
}

const synthesizeStep: Step<ExploreContext> = {
  id: 'synthesize',
  inputs: [PATHS.capabilities, PATHS.stats, PATHS.brandTerms, PATHS.prefetch],
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
    const leaks = publishedLeaks(publishedFileScanner(outDir, context), {
      [PATHS.manual]: manual,
      [PATHS.capabilities]: readFileSync(join(outDir, PATHS.capabilities), 'utf8'),
      [PATHS.stats]: readFileSync(join(outDir, PATHS.stats), 'utf8'),
    });
    if (leaks.length > 0) throw new AnonymizationLeakError(leaks);
    writeFileSync(join(outDir, PATHS.manual), manual);
    log(`wrote manual.md (${manual.length} chars)`);
  },
};

/**
 * Writes the Site state graph from the finished parts, the browser
 * actions of their executor Iterations, and the merged Capabilities with
 * one completion. The graph must pass its checks and the Anonymization
 * scan, or the step fails and writes no file.
 *
 * The step does not read `manifest.json`, but it is an input. Merge
 * writes the manifest again on each run, with a new time. Thus each
 * merge makes the graph stale, also a forced merge that keeps the same
 * Capabilities. `plan.md` decides which parts are finished. The
 * trajectories under `run/iters/` are not inputs: only the explore step
 * writes them, and the merge after it makes the graph stale.
 */
const graphStep: Step<ExploreContext> = {
  id: 'graph',
  inputs: [
    PATHS.capabilities,
    PATHS.manifest,
    PATHS.brandTerms,
    PATHS.prefetch,
    join(PATHS.run, 'plan.md'),
  ],
  outputs: [PATHS.siteGraph],
  async run({ outDir, context, log, signal }) {
    const runDir = join(outDir, PATHS.run);
    const graph = await renderSiteGraph(
      context.llm,
      context.model,
      context.prompts.graph,
      parseCapabilities(readJson(join(outDir, PATHS.capabilities))),
      await readFinishedParts(runDir),
      signal,
    );
    const text = `${JSON.stringify(graph, null, 2)}\n`;
    const leaks = publishedLeaks(publishedFileScanner(outDir, context), {
      [PATHS.siteGraph]: text,
    });
    if (leaks.length > 0) throw new AnonymizationLeakError(leaks);
    writeFileSync(join(outDir, PATHS.siteGraph), text);
    const pages = graph.states.filter((state) => state.kind === 'page').length;
    const overlays = graph.states.length - pages;
    log(
      `wrote site_graph.json: pages ${pages}, overlays ${overlays}, transitions ${graph.transitions.length}`,
    );
  },
};

/**
 * The brand terms of a run: `given`, or else the terms that a prior call
 * kept in `<outDir>/brand_terms.json`, so a resumed run keeps them. Writes
 * the result back to that file, which is outside the published files.
 *
 * @throws Error when a term has no letter or digit.
 */
function resolveBrandTerms(
  outDir: string,
  given: readonly string[] | undefined,
): readonly string[] {
  const path = join(outDir, PATHS.brandTerms);
  const terms = given ?? (existsSync(path) ? BRAND_TERMS_SCHEMA.parse(readJson(path)) : []);
  checkBrandTerms(terms);
  mkdirSync(outDir, { recursive: true });
  writeJson(path, terms);
  return terms;
}

const STEPS: readonly Step<ExploreContext>[] = [
  prefetchStep,
  exploreStep,
  mergeStep,
  synthesizeStep,
  graphStep,
];

/**
 * Explores a storefront end to end and returns the output paths.
 *
 * Calling again with the same `outDir` skips complete steps and resumes
 * an unfinished harness run; `from` forces a step and its dependents.
 *
 * @throws Error when `focus` differs from the focus that `outDir` started with.
 * @throws Error when a brand term has no letter or digit.
 * @throws ShopUnreachableError when the prefetch gates reject the shop.
 * @throws ResumeRefusedError when the prior harness run ended in a
 *   refused status and `forceResume` is not set.
 * @throws StepFailedError for the synthesize step, with an
 *   AnonymizationLeakError cause, when the final Anonymization scan finds
 *   a leak in a published file.
 * @throws StepFailedError for the graph step when the graph reply is not
 *   one JSON object (SiteGraphReplyError cause), fails a graph check
 *   (SiteGraphValidationError cause), or has a leak
 *   (AnonymizationLeakError cause).
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
  const focus = options.focus ?? null;
  checkFocus(outDir, focus);
  const context: ExploreContext = {
    url: base,
    model: parseModel(modelName),
    modelName,
    maxIters: options.maxIters ?? DEFAULT_MAX_ITERS,
    timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    rateLimitMs: options.rateLimitMs,
    forceResume: options.forceResume ?? false,
    focus,
    brandTerms: resolveBrandTerms(outDir, options.brandTerms),
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
    siteGraphPath: join(outDir, PATHS.siteGraph),
    finalStatus: outcome.final_status,
    stop: outcome.stop ?? null,
    steps,
  };
}
