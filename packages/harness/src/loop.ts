/**
 * The plan-then-loop engine.
 *
 * One planner iteration writes `plan.md`; executor iterations then take the
 * highest-priority pending task one at a time until the plan drains, the
 * budget runs out, or a terminal failure occurs. Every iteration leaves a
 * `trajectory.json`, `metadata.json`, `plan.before.md` and `plan.after.md`
 * under `iters/<iterId>/`, and `run.json` is rewritten after each one. The
 * caller's `onIterationEnd` then hears whether the iteration was kept or
 * abandoned.
 *
 * Mode is inferred from `runDir`: empty or absent starts fresh, populated
 * resumes. Resume skips the planner when its trajectory exists, quarantines
 * partial iteration dirs, and grants `maxIters` further executor iterations.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  type AgentRunRequest,
  type AgentRuntime,
  type ImageAttachment,
  type PromptContent,
  type Trajectory,
  sha256,
  writeTrajectory,
} from '@shop-gym/agent';

import {
  DEFAULT_VERIFIER_FEEDBACK_MAX_CHARS,
  type FinalStatus,
  type IterationOutcome,
  type PlanExecLoopConfig,
  type PlanExecLoopResult,
  validateConfig,
} from './config.js';
import { InvalidPlanError, type PlanDiff, diff, parse, selectNext } from './plan/parser.js';
import {
  type ProtocolCheckResult,
  mergeProtocolResults,
  runProtocolChecks,
} from './plan/protocol.js';
import { blockTask } from './plan/rewrite.js';
import type { Task, TaskList } from './plan/tasks.js';
import { checkSeed } from './seed.js';
import { PLAN_ITER_ID, execIterId, isIterDirName, iterDirPath } from './telemetry/ids.js';
import type { IterationMetadata } from './telemetry/metadata.js';
import { TRAJECTORY_FILENAME, reconstruct, scanIterDirs } from './telemetry/recovery.js';
import { type ResumeAttempt, readPriorRunSummary, writeRunSummary } from './telemetry/summary.js';
import {
  FEEDBACK_FILENAME,
  FEEDBACK_IMAGES_FILENAME,
  VERIFIERS_DIRNAME,
  dispatchVerifiers,
  readFeedbackImages,
  renderFeedbackForPrompt,
} from './verifiers/dispatch.js';
import type { VerifierRun } from './verifiers/types.js';
import { Workspace } from './workspace.js';

const HARNESS_CONTROL_HEADER = (taskId: string) =>
  `<<<harness-control>>>\nselected_task_id: ${taskId}\n<<<end>>>\n\n`;
const VERIFIER_FEEDBACK_PLACEHOLDER = '{{verifier_feedback}}';
/** Verifier images attached to one executor prompt, at most. */
const MAX_FEEDBACK_IMAGES = 6;
const IMAGE_MIME_TYPES: Readonly<Record<string, string>> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
};
const METADATA_FILENAME = 'metadata.json';
const PROTOCOL_FILENAME = 'protocol.json';
const PLAN_BEFORE_FILENAME = 'plan.before.md';
const PLAN_AFTER_FILENAME = 'plan.after.md';
const ABORTED_SENTINEL_FILENAME = 'aborted.txt';
const REFUSAL_STATUSES: ReadonlySet<FinalStatus> = new Set([
  'protocol_violation',
  'invalid_plan',
  'runtime_error',
]);

/** The prior run's status implies a bad workspace; pass `force` to override. */
export class ResumeRefusedError extends Error {
  constructor(
    readonly runDir: string,
    readonly priorStatus: FinalStatus | undefined,
  ) {
    super(
      `refusing to resume run_dir=${runDir} with prior final_status=${priorStatus ?? 'unknown'}; pass force to override`,
    );
    this.name = 'ResumeRefusedError';
  }
}

export interface RunOptions {
  /** Override the refusal policy for prior `protocol_violation`, `invalid_plan`, `runtime_error`, or unknown status. */
  readonly force?: boolean;
}

/**
 * Run one plan-then-loop session.
 *
 * @throws HarnessConfigError on an invalid config.
 * @throws ResumeMismatchError when the existing run dir was built from a different config.
 * @throws ResumeRefusedError when the prior status implies a bad state and `force` is not set.
 */
export async function runPlanExecLoop(
  config: PlanExecLoopConfig,
  runtime: AgentRuntime,
  options: RunOptions = {},
): Promise<PlanExecLoopResult> {
  validateConfig(config);
  let workspace: Workspace;
  let priorHistory: ResumeAttempt[] = [];
  if (await isExistingWorkspace(config.runDir)) {
    workspace = await Workspace.open(config.runDir, config);
    const prior = await readPriorRunSummary(workspace.runDir);
    const priorStatus = prior?.finalStatus ?? (await reconstructedStatus(workspace.runDir));
    if (
      options.force !== true &&
      (priorStatus === undefined || REFUSAL_STATUSES.has(priorStatus))
    ) {
      throw new ResumeRefusedError(workspace.runDir, priorStatus);
    }
    await quarantinePartialIters(workspace.itersDir, priorStatus);
    priorHistory = prior?.resumeHistory ?? [];
  } else {
    workspace = await Workspace.create(config);
  }
  const state = new LoopState(workspace, config, runtime, priorHistory);
  await state.restoreFromDisk();
  if (state.planIterCount === 0 && !(await state.runPlanner())) {
    return state.finalize();
  }
  await state.runExecutorLoop();
  return state.finalize();
}

type Outcome = { trajectory: Trajectory } | { errorStatus: 'timeout' | 'runtime_error' };

class LoopState {
  planIterCount = 0;
  private execIterCount = 0;
  private execIterBaseline = 0;
  private trajectoryPaths: string[] = [];
  private finalStatus: FinalStatus | undefined;
  private readonly verifierRuns: VerifierRun[] = [];
  /** Tasks that timed out or violated protocol in this attempt; never re-selected. */
  private readonly skipped = new Set<string>();
  private hadTimeout = false;
  private readonly attemptStartedAt = new Date().toISOString();
  private readonly feedbackMaxChars: number;

  constructor(
    private readonly workspace: Workspace,
    private readonly config: PlanExecLoopConfig,
    private readonly runtime: AgentRuntime,
    private readonly priorHistory: readonly ResumeAttempt[],
  ) {
    this.feedbackMaxChars = config.verifierFeedbackMaxChars ?? DEFAULT_VERIFIER_FEEDBACK_MAX_CHARS;
  }

  /** Replay counters from `iters/`; a no-op on a fresh workspace. */
  async restoreFromDisk(): Promise<void> {
    const scan = await scanIterDirs(this.workspace.itersDir);
    this.planIterCount = scan.planIterCount;
    this.execIterCount = scan.execIterIds.length;
    this.execIterBaseline = this.execIterCount;
    this.trajectoryPaths = [...scan.trajectoryPaths];
  }

  /** Run the planner. Returns false on terminal failure. */
  async runPlanner(): Promise<boolean> {
    const planDir = iterDirPath(this.workspace.itersDir, PLAN_ITER_ID);
    await fs.mkdir(planDir);
    await this.workspace.snapshotPlan(path.join(planDir, PLAN_BEFORE_FILENAME));
    const outcome = await this.invokeRuntime(planDir, PLAN_ITER_ID, this.config.prompts.planner);
    if ('errorStatus' in outcome) {
      return this.terminateAfter(PLAN_ITER_ID, null, outcome.errorStatus);
    }
    await this.workspace.snapshotPlan(path.join(planDir, PLAN_AFTER_FILENAME));
    await writeTrajectory(path.join(planDir, TRAJECTORY_FILENAME), outcome.trajectory);
    this.planIterCount = 1;
    this.trajectoryPaths.push(`iters/${PLAN_ITER_ID}/${TRAJECTORY_FILENAME}`);
    await writeMetadata(planDir, {
      iterId: PLAN_ITER_ID,
      iterKind: 'plan',
      runtime: outcome.trajectory.runtime,
      startedAt: outcome.trajectory.startedAt,
      endedAt: outcome.trajectory.endedAt,
      selectedTaskId: null,
      completedTaskIds: [],
      blockedTaskIds: [],
      addedTaskIds: [],
    });

    const seedResult = await this.seedCheck(PLAN_ITER_ID);
    if (seedResult !== undefined) {
      await writeProtocolResult(planDir, seedResult);
      if (!seedResult.passed) {
        return this.terminateAfter(PLAN_ITER_ID, null, 'protocol_violation');
      }
    }
    try {
      diff([], await this.parsePlan());
    } catch (error) {
      if (error instanceof InvalidPlanError) {
        return this.terminateAfter(PLAN_ITER_ID, null, 'invalid_plan');
      }
      throw error;
    }
    await this.rewriteRunSummary();
    await this.endIteration(PLAN_ITER_ID, null, 'kept');
    return true;
  }

  async runExecutorLoop(): Promise<void> {
    for (;;) {
      let tasks: TaskList;
      try {
        tasks = await this.parsePlan();
      } catch (error) {
        if (error instanceof InvalidPlanError) {
          await this.terminate('invalid_plan');
          return;
        }
        throw error;
      }
      const selected = selectNext(tasks.filter((task) => !this.skipped.has(task.id)));
      if (selected === undefined) {
        await this.terminate(this.hadTimeout ? 'timeout' : 'completed');
        return;
      }
      if (this.execIterCount - this.execIterBaseline >= this.config.maxIters) {
        await this.terminate(this.hadTimeout ? 'timeout' : 'budget_exhausted');
        return;
      }
      if (!(await this.runOneExecutor(tasks, selected))) {
        return;
      }
    }
  }

  /**
   * One executor iteration. Returns false on terminal failure.
   *
   * A timeout quarantines the iteration dir and leaves the task pending for
   * a future resume. A protocol violation or an unparseable plan restores
   * `plan.md` from `plan.before.md`, force-blocks the task, and continues.
   */
  private async runOneExecutor(before: TaskList, selected: Task): Promise<boolean> {
    const n = this.execIterCount + 1;
    const execId = execIterId(n);
    const execDir = iterDirPath(this.workspace.itersDir, execId);
    await fs.mkdir(execDir);
    const planBefore = path.join(execDir, PLAN_BEFORE_FILENAME);
    const planAfter = path.join(execDir, PLAN_AFTER_FILENAME);
    await this.workspace.snapshotPlan(planBefore);

    const feedback = await this.previousFeedback(n);
    const text =
      HARNESS_CONTROL_HEADER(selected.id) +
      this.config.prompts.execute.replaceAll(VERIFIER_FEEDBACK_PLACEHOLDER, feedback.text);
    const prompt = feedback.images.length === 0 ? text : { text, images: feedback.images };
    const outcome = await this.invokeRuntime(execDir, execId, prompt);
    if ('errorStatus' in outcome) {
      if (outcome.errorStatus !== 'timeout') {
        return this.terminateAfter(execId, selected.id, outcome.errorStatus);
      }
      await quarantineIterDir(this.workspace.itersDir, execDir, 'timeout');
      this.skipped.add(selected.id);
      this.hadTimeout = true;
      await this.rewriteRunSummary();
      await this.endIteration(execId, selected.id, 'timeout');
      return true;
    }
    await this.workspace.snapshotPlan(planAfter);
    await writeTrajectory(path.join(execDir, TRAJECTORY_FILENAME), outcome.trajectory);
    this.execIterCount = n;
    this.trajectoryPaths.push(`iters/${execId}/${TRAJECTORY_FILENAME}`);

    let after: TaskList;
    let planDiff: PlanDiff;
    try {
      after = await this.parsePlan();
      planDiff = diff(before, after);
    } catch (error) {
      if (!(error instanceof InvalidPlanError)) {
        throw error;
      }
      await this.forceBlock(planBefore, planAfter, selected.id, `invalid_plan: ${error.message}`);
      await this.endIteration(execId, selected.id, 'invalid_plan');
      return true;
    }

    const protocol = mergeProtocolResults(execId, [
      runProtocolChecks({ iterId: execId, before, after, selectedTaskId: selected.id }),
      await this.seedCheck(execId),
    ]);
    await writeProtocolResult(execDir, protocol);
    await writeMetadata(execDir, {
      iterId: execId,
      iterKind: 'exec',
      runtime: outcome.trajectory.runtime,
      startedAt: outcome.trajectory.startedAt,
      endedAt: outcome.trajectory.endedAt,
      selectedTaskId: selected.id,
      completedTaskIds: [...planDiff.completedTaskIds],
      blockedTaskIds: [...planDiff.blockedTaskIds],
      addedTaskIds: [...planDiff.addedTaskIds],
    });
    const dispatched = await dispatchVerifiers({
      verifiers: this.config.verifiers ?? [],
      iterDir: execDir,
      iterId: execId,
      runDir: this.workspace.runDir,
      selectedTaskId: selected.id,
      plan: after,
      planPath: this.workspace.planMd,
    });
    this.verifierRuns.push(...dispatched.runs);

    if (!protocol.passed) {
      const note = `protocol_violation: ${protocol.violations.join(', ')}`;
      await this.forceBlock(planBefore, planAfter, selected.id, note);
      await this.endIteration(execId, selected.id, 'protocol_violation');
      return true;
    }
    await this.rewriteRunSummary();
    await this.endIteration(execId, selected.id, 'kept');
    return true;
  }

  /**
   * Restore `plan.md` from `plan.before.md`, mark `taskId` blocked with
   * `note`, re-snapshot `plan.after.md`, and skip the task for this attempt.
   * Falls back to an empty task list when the task line cannot be found.
   */
  private async forceBlock(
    planBefore: string,
    planAfter: string,
    taskId: string,
    note: string,
  ): Promise<void> {
    const text = await fs.readFile(planBefore, 'utf-8');
    const blocked = blockTask(text, taskId, note) ?? '## Tasks\n\n';
    await this.workspace.writePlan(blocked.endsWith('\n') ? blocked : `${blocked}\n`);
    await this.workspace.snapshotPlan(planAfter, true);
    this.skipped.add(taskId);
    await this.rewriteRunSummary();
  }

  /**
   * The previous executor iteration's verifier feedback and the images that
   * accompany it. Images are only loaded when the execute prompt renders the
   * feedback placeholder, so a prompt without the slot sees neither.
   */
  private async previousFeedback(
    n: number,
  ): Promise<{ text: string; images: readonly ImageAttachment[] }> {
    const none = { text: '', images: [] };
    if (n <= 1 || !this.config.prompts.execute.includes(VERIFIER_FEEDBACK_PLACEHOLDER)) {
      return none;
    }
    const checksDir = path.join(
      iterDirPath(this.workspace.itersDir, execIterId(n - 1)),
      'checks',
      VERIFIERS_DIRNAME,
    );
    const [text, imagePaths] = await Promise.all([
      renderFeedbackForPrompt(path.join(checksDir, FEEDBACK_FILENAME), this.feedbackMaxChars),
      readFeedbackImages(path.join(checksDir, FEEDBACK_IMAGES_FILENAME)),
    ]);
    const images = await Promise.all(imagePaths.slice(0, MAX_FEEDBACK_IMAGES).map(loadImage));
    return { text, images };
  }

  private async invokeRuntime(
    iterDir: string,
    iterId: string,
    prompt: string | PromptContent,
  ): Promise<Outcome> {
    const onEvent = this.config.onEvent;
    const request: AgentRunRequest = {
      cwd: this.workspace.runDir,
      systemPrompt: this.config.agentsMd,
      prompt,
      tools: this.config.tools,
      model: this.config.model,
      signal: AbortSignal.timeout(this.config.timeoutMs),
      logDir: iterDir,
      ...(onEvent === undefined ? {} : { onEvent: (event) => onEvent(iterId, event) }),
    };
    let trajectory: Trajectory;
    try {
      const result = await this.runtime.run(request);
      if (result.status === 'aborted') {
        return { errorStatus: 'timeout' };
      }
      if (result.status === 'error') {
        return { errorStatus: 'runtime_error' };
      }
      trajectory = result.trajectory;
    } catch {
      return { errorStatus: 'runtime_error' };
    }
    // The harness knows which prompt it sent; recompute the digest so
    // telemetry does not depend on each runtime filling it in correctly.
    const text = typeof prompt === 'string' ? prompt : prompt.text;
    return { trajectory: { ...trajectory, promptSha256: sha256(text) } };
  }

  private async parsePlan(): Promise<TaskList> {
    const text = await this.workspace.readPlan();
    return text.trim() === '' ? [] : parse(text);
  }

  private async seedCheck(iterId: string): Promise<ProtocolCheckResult | undefined> {
    const manifest = this.workspace.seedManifest;
    return manifest === undefined
      ? undefined
      : checkSeed(manifest, this.workspace.artifactDir, iterId);
  }

  private async terminate(status: FinalStatus): Promise<false> {
    this.finalStatus = status;
    await this.rewriteRunSummary();
    return false;
  }

  /** End the run because iteration `iterId` failed with `status`, then report that iteration. */
  private async terminateAfter(
    iterId: string,
    taskId: string | null,
    status: Exclude<IterationOutcome, 'kept'>,
  ): Promise<false> {
    await this.terminate(status);
    await this.endIteration(iterId, taskId, status);
    return false;
  }

  private async endIteration(
    iterId: string,
    taskId: string | null,
    outcome: IterationOutcome,
  ): Promise<void> {
    await this.config.onIterationEnd?.({ iterId, taskId, outcome });
  }

  async finalize(): Promise<PlanExecLoopResult> {
    this.finalStatus ??= this.hadTimeout ? 'timeout' : 'completed';
    return this.rewriteRunSummary();
  }

  private async rewriteRunSummary(): Promise<PlanExecLoopResult> {
    const finalStatus = this.finalStatus ?? 'completed';
    let tasksFinal: TaskList = [];
    try {
      tasksFinal = await this.parsePlan();
    } catch (error) {
      if (!(error instanceof InvalidPlanError)) {
        throw error;
      }
    }
    const result: PlanExecLoopResult = {
      runDir: this.workspace.runDir,
      finalStatus,
      planIterCount: this.planIterCount,
      execIterCount: this.execIterCount,
      trajectoryPaths: [...this.trajectoryPaths],
      tasksFinal,
      verifierRuns: [...this.verifierRuns],
    };
    const { provider, id, thinking } = this.config.model;
    await writeRunSummary(this.workspace.runDir, {
      ...result,
      configSnapshot: {
        maxIters: this.config.maxIters,
        timeoutMs: this.config.timeoutMs,
        verifierFeedbackMaxChars: this.feedbackMaxChars,
        artifactSeedDir: this.config.artifactSeedDir ?? null,
        model: { provider, id, ...(thinking === undefined ? {} : { thinking }) },
        tools: this.config.tools.map((tool) => tool.name),
        verifiers: (this.config.verifiers ?? []).map((verifier) => verifier.name),
        resumeHistory: [
          ...this.priorHistory,
          { startedAt: this.attemptStartedAt, endedAt: new Date().toISOString(), finalStatus },
        ],
      },
    });
    return result;
  }
}

async function isExistingWorkspace(runDir: string): Promise<boolean> {
  const stat = await fs.stat(runDir).catch(() => undefined);
  if (stat?.isDirectory() !== true) {
    return false;
  }
  return (await fs.readdir(runDir)).length > 0;
}

async function reconstructedStatus(runDir: string): Promise<FinalStatus | undefined> {
  try {
    return (await reconstruct(runDir)).finalStatus;
  } catch {
    return undefined;
  }
}

/** Rename iter dirs without a trajectory to `<id>.aborted-<N>/` and drop a sentinel. */
async function quarantinePartialIters(
  itersDir: string,
  priorStatus: FinalStatus | undefined,
): Promise<void> {
  const entries = await fs.readdir(itersDir, { withFileTypes: true });
  for (const entry of entries.sort((a, b) => (a.name < b.name ? -1 : 1))) {
    if (!entry.isDirectory() || !isIterDirName(entry.name)) {
      continue;
    }
    const dir = path.join(itersDir, entry.name);
    const hasTrajectory = await fs
      .stat(path.join(dir, TRAJECTORY_FILENAME))
      .then((stat) => stat.isFile())
      .catch(() => false);
    if (hasTrajectory) {
      continue;
    }
    const target = await nextAbortedPath(itersDir, entry.name);
    await fs.rename(dir, target);
    await fs.writeFile(
      path.join(target, ABORTED_SENTINEL_FILENAME),
      `resume_at: ${new Date().toISOString()}\nprior_final_status: ${priorStatus ?? 'unknown'}\n`,
    );
  }
}

/** Move one partial iter dir aside mid-run so the next iteration can reuse its id. */
async function quarantineIterDir(itersDir: string, iterDir: string, reason: string): Promise<void> {
  const target = await nextAbortedPath(itersDir, path.basename(iterDir));
  await fs.rename(iterDir, target);
  await fs.writeFile(
    path.join(target, ABORTED_SENTINEL_FILENAME),
    `aborted_at: ${new Date().toISOString()}\nreason: ${reason}\n`,
  );
}

async function nextAbortedPath(itersDir: string, baseName: string): Promise<string> {
  for (let counter = 1; ; counter += 1) {
    const candidate = path.join(itersDir, `${baseName}.aborted-${counter}`);
    if ((await fs.lstat(candidate).catch(() => undefined)) === undefined) {
      return candidate;
    }
  }
}

async function writeMetadata(iterDir: string, metadata: IterationMetadata): Promise<void> {
  await fs.writeFile(
    path.join(iterDir, METADATA_FILENAME),
    `${JSON.stringify(metadata, null, 2)}\n`,
  );
}

async function writeProtocolResult(iterDir: string, result: ProtocolCheckResult): Promise<void> {
  const checksDir = path.join(iterDir, 'checks');
  await fs.mkdir(checksDir, { recursive: true });
  await fs.writeFile(
    path.join(checksDir, PROTOCOL_FILENAME),
    `${JSON.stringify(result, null, 2)}\n`,
  );
}

/** Read an image file as a base64 prompt attachment; the extension picks the MIME type. */
async function loadImage(file: string): Promise<ImageAttachment> {
  const mimeType = IMAGE_MIME_TYPES[path.extname(file).toLowerCase()];
  if (mimeType === undefined) {
    throw new Error(`verifier image ${file} is not a PNG or JPEG`);
  }
  return { data: (await fs.readFile(file)).toString('base64'), mimeType };
}
