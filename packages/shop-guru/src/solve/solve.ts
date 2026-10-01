/**
 * Runs tasks as isolated episodes: one backend episode branch, one fresh
 * browser per task. Grading happens inside the episode while the page is
 * still open, because `locator_probe` with `url: 'last'` must inspect the
 * page exactly as the agent left it.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { type Tool, addUsage, writeTrajectory } from '@shop-gym/agent';
import { BrowserSession, browserTools } from '@shop-gym/browser';
import {
  type CheckResult,
  type EpisodeResult,
  type EpisodeStatus,
  type Task,
  episodeResultSchema,
} from '@shop-gym/core';
import type { Customer } from '@shop-gym/shop-backend';

import { BackendClient } from '../backend.js';
import { type Judge, grade } from '../grade/grade.js';
import { ZERO_USAGE } from '../usage.js';
import type { AgentUnderTest, SolveOutcome } from './agent.js';
import { applySetup } from './setup.js';

export interface EpisodeOptions {
  readonly agent: AgentUnderTest;
  /** Storefront origin the agent browses. */
  readonly baseUrl: string;
  /** Sandbox backend origin, for episode reset and state checks. */
  readonly backendUrl: string;
  /** Personas available to `setup.login`. */
  readonly customers: readonly Customer[];
  /** Directory receiving `episodes/<taskId>/`. */
  readonly runDir: string;
  /** When false the episode is solved but every check is skipped (`solve`). */
  readonly grade: boolean;
  readonly judge?: Judge;
  readonly episodeTimeoutMs: number;
  readonly headless?: boolean;
  readonly signal?: AbortSignal;
}

const TRAJECTORY_FILE = 'trajectory.json';
const SCREENSHOT_FILE = 'final.png';
const RESULT_FILE = 'result.json';

/** Episode ids must be url-safe; task ids already are, the suffix keeps reruns apart. */
function episodeIdFor(task: Task): string {
  return `${task.id}-${Date.now().toString(36)}`;
}

/** Wrap `finish` so calling it fires `onFinish` after it runs. */
function endOnFinish(tools: readonly Tool[], onFinish: () => void): Tool[] {
  return tools.map((tool) =>
    tool.name !== 'finish'
      ? tool
      : {
          ...tool,
          execute: async (params, ctx) => {
            const result = await tool.execute(params, ctx);
            onFinish();
            return result;
          },
        },
  );
}

/** Solve (and optionally grade) one task, writing its artifacts under `runDir`. */
export async function runEpisode(task: Task, options: EpisodeOptions): Promise<EpisodeResult> {
  const startedAt = new Date();
  const episodeDir = path.join(options.runDir, 'episodes', task.id);
  await fs.mkdir(episodeDir, { recursive: true });
  const episodeId = episodeIdFor(task);
  const backend = new BackendClient(options.backendUrl, episodeId);

  let status: EpisodeStatus = 'error';
  let error: string | undefined;
  let answer: string | null = null;
  let finalUrl: string | null = null;
  let checks: CheckResult[] = [];
  let passed = false;
  let usage = ZERO_USAGE;
  let outcome: SolveOutcome | undefined;
  let session: BrowserSession | undefined;

  try {
    await backend.reset();
    session = await BrowserSession.launch({
      episodeId,
      baseUrl: options.baseUrl,
      headless: options.headless ?? true,
    });
    await applySetup(task.setup, session, options.baseUrl, options.customers);
    await session.page.goto(options.baseUrl, { waitUntil: 'domcontentloaded' });

    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(new Error('episode timeout')),
      options.episodeTimeoutMs,
    );
    const onOuterAbort = () => controller.abort(options.signal?.reason);
    options.signal?.addEventListener('abort', onOuterAbort, { once: true });
    const finished = { value: false };
    try {
      outcome = await options.agent.run({
        task,
        baseUrl: options.baseUrl,
        session,
        tools: endOnFinish(browserTools(session), () => {
          finished.value = true;
          controller.abort(new Error('finish called'));
        }),
        logDir: path.join(episodeDir, 'agent'),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener('abort', onOuterAbort);
    }

    finalUrl = session.page.url();
    const screenshot = await session.page.screenshot({ fullPage: false });
    await fs.writeFile(path.join(episodeDir, SCREENSHOT_FILE), screenshot);

    if (session.finished !== undefined) {
      status = session.finished.infeasible ? 'infeasible' : 'completed';
      answer = session.finished.answer ?? null;
    } else if (outcome.status === 'aborted' && !finished.value) {
      status = 'aborted';
    } else if (outcome.status === 'error') {
      status = 'error';
      error = outcome.error ?? 'agent runtime error';
    } else {
      // The run ended without `finish`: nothing to grade an answer against.
      status = 'completed';
    }

    if (options.grade && status !== 'error') {
      const graded = await grade({
        task,
        answer,
        finalUrl,
        baseUrl: options.baseUrl,
        session,
        backend,
        screenshot,
        ...(options.judge === undefined ? {} : { judge: options.judge }),
        ...(options.signal === undefined ? {} : { signal: options.signal }),
      });
      checks = graded.checks;
      // Only an episode the agent brought to completion can pass.
      passed = status === 'completed' && graded.passed;
      usage = graded.usage;
    }
  } catch (caught) {
    status = 'error';
    error = caught instanceof Error ? caught.message : String(caught);
  } finally {
    await session?.close();
  }

  if (outcome !== undefined) {
    await writeTrajectory(path.join(episodeDir, TRAJECTORY_FILE), outcome.trajectory);
    usage = addUsage(usage, outcome.trajectory.usage);
  }

  const result = episodeResultSchema.parse({
    taskId: task.id,
    shop: task.shop,
    skill: task.skill,
    agent: { name: options.agent.name, model: options.agent.model.id },
    status,
    answer,
    finalUrl,
    passed,
    checks,
    usage,
    startedAt: startedAt.toISOString(),
    durationMs: Date.now() - startedAt.getTime(),
    ...(error === undefined ? {} : { error }),
    ...(outcome === undefined
      ? {}
      : { trajectoryPath: path.relative(options.runDir, path.join(episodeDir, TRAJECTORY_FILE)) }),
  } satisfies EpisodeResult);
  await fs.writeFile(path.join(episodeDir, RESULT_FILE), `${JSON.stringify(result, null, 2)}\n`);
  return result;
}

/** Run `tasks` with at most `concurrency` episodes in flight; results keep task order. */
export async function runEpisodes(
  tasks: readonly Task[],
  options: EpisodeOptions,
  concurrency: number,
): Promise<EpisodeResult[]> {
  const results: EpisodeResult[] = new Array<EpisodeResult>(tasks.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < tasks.length) {
      const index = next++;
      const task = tasks[index];
      if (task === undefined) return;
      results[index] = await runEpisode(task, options);
    }
  };
  await Promise.all(
    Array.from({ length: Math.max(1, Math.min(concurrency, tasks.length)) }, worker),
  );
  return results;
}
