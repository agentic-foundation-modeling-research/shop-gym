/**
 * Per-iteration verifier dispatch.
 *
 * Runs every applicable verifier in registration order with timing and
 * exception trapping, writes one JSON file per verifier under
 * `checks/verifiers/`, writes `feedback.md` when any verifier produced
 * feedback, and reopens the selected task in `plan.md` when any verifier
 * returned `fail`.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { reopenTask } from '../plan/rewrite.js';
import type { TaskList } from '../plan/tasks.js';
import type { Verifier, VerifierContext, VerifierResult, VerifierRun } from './types.js';

export const VERIFIERS_DIRNAME = 'verifiers';
export const FEEDBACK_FILENAME = 'feedback.md';

export interface DispatchInput {
  readonly verifiers: readonly Verifier[];
  readonly iterDir: string;
  readonly iterId: string;
  readonly runDir: string;
  readonly selectedTaskId: string;
  readonly plan: TaskList;
  readonly planPath: string;
}

export interface DispatchOutcome {
  readonly runs: readonly VerifierRun[];
  /** True when at least one verifier returned `fail`. */
  readonly blocking: boolean;
}

/** Run the applicable verifiers and persist their outcomes. */
export async function dispatchVerifiers(input: DispatchInput): Promise<DispatchOutcome> {
  const applicable = input.verifiers.filter((verifier) => verifier.appliesTo(input.selectedTaskId));
  if (applicable.length === 0) {
    return { runs: [], blocking: false };
  }
  const checksDir = path.join(input.iterDir, 'checks', VERIFIERS_DIRNAME);
  await fs.mkdir(checksDir, { recursive: true });
  const ctx: VerifierContext = {
    runDir: input.runDir,
    iterId: input.iterId,
    selectedTaskId: input.selectedTaskId,
    plan: input.plan,
    artifactDir: path.join(input.runDir, 'artifact'),
  };

  const runs: VerifierRun[] = [];
  const sections: [string, string][] = [];
  let blocking = false;
  for (const verifier of applicable) {
    const startedAt = new Date();
    const startedPerf = performance.now();
    let result: VerifierResult;
    try {
      result = await verifier.run(ctx);
    } catch (error) {
      result = {
        verdict: 'error',
        feedback: error instanceof Error ? error.message : String(error),
      };
    }
    const durationMs = Math.floor(performance.now() - startedPerf);
    const feedback = result.feedback ?? '';
    const record = {
      iterId: input.iterId,
      name: verifier.name,
      taskId: input.selectedTaskId,
      verdict: result.verdict,
      startedAt: startedAt.toISOString(),
      durationMs,
      feedback,
      details: result.details ?? {},
    };
    await fs.writeFile(
      path.join(checksDir, `${verifier.name}.json`),
      `${JSON.stringify(record, null, 2)}\n`,
    );
    runs.push({
      iterId: input.iterId,
      name: verifier.name,
      taskId: input.selectedTaskId,
      verdict: result.verdict,
      startedAt: record.startedAt,
      durationMs,
      path: `iters/${input.iterId}/checks/${VERIFIERS_DIRNAME}/${verifier.name}.json`,
    });
    if (result.verdict === 'fail') {
      blocking = true;
    }
    if ((result.verdict === 'fail' || result.verdict === 'advisory') && feedback !== '') {
      sections.push([verifier.name, feedback]);
    }
  }

  if (sections.length > 0) {
    const body = sections.map(([name, text]) => `## ${name}\n\n${text.trimEnd()}\n`).join('\n');
    await fs.writeFile(path.join(checksDir, FEEDBACK_FILENAME), body);
  }
  if (blocking) {
    const text = await fs.readFile(input.planPath, 'utf-8');
    const reopened = reopenTask(text, input.selectedTaskId);
    if (reopened !== text) {
      await fs.writeFile(input.planPath, reopened);
    }
  }
  return { runs, blocking };
}

/**
 * Read a `feedback.md` and return its body truncated to `maxChars`, or the
 * empty string when the file is absent. The full body stays on disk.
 */
export async function renderFeedbackForPrompt(
  feedbackPath: string,
  maxChars: number,
): Promise<string> {
  let body: string;
  try {
    body = await fs.readFile(feedbackPath, 'utf-8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return '';
    }
    throw error;
  }
  return body.length <= maxChars ? body : `${body.slice(0, maxChars)}\n[...truncated]`;
}
