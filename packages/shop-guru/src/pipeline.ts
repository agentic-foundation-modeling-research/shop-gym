/**
 * The four benchmark stages as plain functions over a `GuruConfig`:
 * `build` (seed + validate), `explore`, `solve`, and `evaluate`
 * (solve + grade + aggregate). A CLI wires them to arguments; nothing here
 * reads the process environment.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { AgentRuntime } from '@shop-gym/agent';
import type { Aggregate, EpisodeResult, Task } from '@shop-gym/core';
import { loadShopData } from '@shop-gym/shop-backend';

import { aggregate } from './aggregate.js';
import { readBenchmarks, writeBenchmarks } from './benchmarks.js';
import { type GuruConfig, shopOutDir } from './config.js';
import { type ExploreResult, explore as runExplore } from './explore/explore.js';
import type { Judge } from './grade/grade.js';
import { SEED_SKILLS, generateSeedTasks } from './seed/index.js';
import type { AgentUnderTest } from './solve/agent.js';
import { runEpisodes } from './solve/solve.js';
import { type ValidationIssue, validateTasks } from './validate.js';

export interface BuildResult {
  readonly tasks: Task[];
  readonly dropped: ValidationIssue[];
  /** Benchmark files written. */
  readonly files: string[];
}

/** Generate seed tasks from the dataset, validate them, and write `benchmarks/<skill>.json`. */
export async function build(config: GuruConfig): Promise<BuildResult> {
  const data = loadShopData(config.dataDir);
  const candidates = generateSeedTasks({ shop: config.shop, data, seed: config.seed }, config.caps);
  const { tasks, dropped } = validateTasks(candidates, data, config.caps);
  const files = await writeBenchmarks(shopOutDir(config), tasks);
  return { tasks, dropped, files };
}

export interface ExploreDeps {
  readonly runtime: AgentRuntime;
}

export interface ExploreStageResult extends ExploreResult {
  readonly dropped: ValidationIssue[];
  readonly files: string[];
  readonly outDir: string;
}

/** Discover tasks with an agent, verify them, validate references, and merge into the benchmarks. */
export async function explore(config: GuruConfig, deps: ExploreDeps): Promise<ExploreStageResult> {
  const data = loadShopData(config.dataDir);
  const outDir = path.join(shopOutDir(config), 'explore', runId());
  const result = await runExplore({
    runtime: deps.runtime,
    model: config.model,
    shop: config.shop,
    baseUrl: config.shopUrl,
    skills: SEED_SKILLS,
    customers: data.customers,
    maxTasks: config.exploreMaxTasks,
    outDir,
    headless: config.headless,
  });
  const { tasks, dropped } = validateTasks(result.tasks, data);
  await fs.writeFile(path.join(outDir, 'tasks.json'), `${JSON.stringify(tasks, null, 2)}\n`);
  const files = await writeBenchmarks(shopOutDir(config), tasks);
  return { ...result, tasks, dropped, files, outDir };
}

export interface SolveDeps {
  readonly agent: AgentUnderTest;
  /** Needed by `evaluate` for `llm_judge` and `fuzzyMatch` checks. */
  readonly judge?: Judge;
  /** Restrict to these skills; defaults to every benchmark file. */
  readonly skills?: readonly string[];
  readonly signal?: AbortSignal;
}

export interface SolveStageResult {
  readonly runDir: string;
  readonly results: EpisodeResult[];
}

export interface EvalStageResult extends SolveStageResult {
  readonly aggregate: Aggregate;
}

/** Run every benchmark task once without grading; artifacts land in `runs/<runId>/`. */
export async function solve(config: GuruConfig, deps: SolveDeps): Promise<SolveStageResult> {
  return runStage(config, deps, false);
}

/** Run, grade, and aggregate every benchmark task; writes `results.json` and `aggregate.json`. */
export async function evaluate(config: GuruConfig, deps: SolveDeps): Promise<EvalStageResult> {
  const stage = await runStage(config, deps, true);
  const summary = aggregate(stage.results);
  await fs.writeFile(
    path.join(stage.runDir, 'aggregate.json'),
    `${JSON.stringify(summary, null, 2)}\n`,
  );
  return { ...stage, aggregate: summary };
}

async function runStage(
  config: GuruConfig,
  deps: SolveDeps,
  grade: boolean,
): Promise<SolveStageResult> {
  const data = loadShopData(config.dataDir);
  const tasks = await readBenchmarks(shopOutDir(config), deps.skills);
  const runDir = path.join(shopOutDir(config), 'runs', runId());
  await fs.mkdir(runDir, { recursive: true });
  const results = await runEpisodes(
    tasks,
    {
      agent: deps.agent,
      baseUrl: config.shopUrl,
      backendUrl: config.backendUrl,
      customers: data.customers,
      runDir,
      grade,
      episodeTimeoutMs: config.episodeTimeoutMs,
      headless: config.headless,
      ...(deps.judge === undefined ? {} : { judge: deps.judge }),
      ...(deps.signal === undefined ? {} : { signal: deps.signal }),
    },
    config.concurrency,
  );
  await fs.writeFile(path.join(runDir, 'results.json'), `${JSON.stringify(results, null, 2)}\n`);
  return { runDir, results };
}

/** Filesystem-safe timestamp, e.g. `20260930T101500Z`. */
function runId(): string {
  return new Date()
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}/, '');
}
