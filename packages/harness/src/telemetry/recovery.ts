/**
 * Crash-tolerant result reconstruction from `iters/` and `plan.md`.
 *
 * `reconstruct` never reads `run.json`, so a caller can still produce a
 * defensible summary when the harness process died mid-run.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { PlanExecLoopResult } from '../config.js';
import { InvalidPlanError, parse, selectNext } from '../plan/parser.js';
import { protocolCheckResultSchema } from '../plan/protocol.js';
import type { TaskList } from '../plan/tasks.js';
import { PLAN_ITER_ID, isExecIterId } from './ids.js';

export const TRAJECTORY_FILENAME = 'trajectory.json';

export interface IterScan {
  /** 1 when `iters/plan/trajectory.json` exists. */
  readonly planIterCount: number;
  /** Executor iter dir names with a trajectory, sorted. */
  readonly execIterIds: readonly string[];
  readonly trajectoryPaths: readonly string[];
}

/** Count the iterations under `itersDir` that wrote a trajectory. */
export async function scanIterDirs(itersDir: string): Promise<IterScan> {
  const planIterCount = (await hasTrajectory(path.join(itersDir, PLAN_ITER_ID))) ? 1 : 0;
  const execIterIds: string[] = [];
  const entries = await fs.readdir(itersDir, { withFileTypes: true });
  for (const entry of entries.sort((a, b) => (a.name < b.name ? -1 : 1))) {
    if (entry.isDirectory() && isExecIterId(entry.name)) {
      if (await hasTrajectory(path.join(itersDir, entry.name))) {
        execIterIds.push(entry.name);
      }
    }
  }
  const trajectoryPaths = [
    ...(planIterCount === 1 ? [`iters/${PLAN_ITER_ID}/${TRAJECTORY_FILENAME}`] : []),
    ...execIterIds.map((id) => `iters/${id}/${TRAJECTORY_FILENAME}`),
  ];
  return { planIterCount, execIterIds, trajectoryPaths };
}

/**
 * Rebuild a result from disk.
 *
 * Inferred status: `invalid_plan` when `plan.md` fails to parse,
 * `protocol_violation` when the planner's seed check failed, `completed`
 * when no selectable task remains, else `budget_exhausted`. Executor
 * protocol violations are not terminal: the loop force-blocks the task and
 * continues, and the blocked marker is already visible in `plan.md`.
 *
 * @throws Error when `<runDir>/iters/` does not exist.
 */
export async function reconstruct(runDir: string): Promise<PlanExecLoopResult> {
  const itersDir = path.join(runDir, 'iters');
  if ((await fs.stat(itersDir).catch(() => undefined))?.isDirectory() !== true) {
    throw new Error(`missing iters/ under run_dir: ${runDir}`);
  }
  const scan = await scanIterDirs(itersDir);
  const base = {
    runDir,
    planIterCount: scan.planIterCount,
    execIterCount: scan.execIterIds.length,
    trajectoryPaths: scan.trajectoryPaths,
    verifierRuns: [],
  };
  const planText = await fs.readFile(path.join(runDir, 'plan.md'), 'utf-8').catch(() => '');
  let tasks: TaskList = [];
  try {
    tasks = planText.trim() === '' ? [] : parse(planText);
  } catch (error) {
    if (error instanceof InvalidPlanError) {
      return { ...base, finalStatus: 'invalid_plan', tasksFinal: [] };
    }
    throw error;
  }
  if (await plannerProtocolFailed(itersDir)) {
    return { ...base, finalStatus: 'protocol_violation', tasksFinal: tasks };
  }
  const pending = planText.trim() !== '' && selectNext(tasks) !== undefined;
  return { ...base, finalStatus: pending ? 'budget_exhausted' : 'completed', tasksFinal: tasks };
}

async function hasTrajectory(dir: string): Promise<boolean> {
  const stat = await fs.stat(path.join(dir, TRAJECTORY_FILENAME)).catch(() => undefined);
  return stat?.isFile() === true;
}

async function plannerProtocolFailed(itersDir: string): Promise<boolean> {
  const protocolPath = path.join(itersDir, PLAN_ITER_ID, 'checks', 'protocol.json');
  const text = await fs.readFile(protocolPath, 'utf-8').catch(() => undefined);
  if (text === undefined) {
    return false;
  }
  return !protocolCheckResultSchema.parse(JSON.parse(text)).passed;
}
