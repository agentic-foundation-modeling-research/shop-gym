/**
 * The verifier contract. Callers implement `Verifier`; the harness owns
 * dispatch, persistence, and feedback rendering.
 */

import type { TaskList } from '../plan/tasks.js';

/**
 * Outcome of one verifier invocation.
 *
 * - `pass`: the loop advances.
 * - `fail`: blocking; the selected task's `[x]` or `[!]` is rewritten to `[~]`.
 * - `advisory`: non-blocking; feedback is surfaced to the next iteration.
 * - `error`: set by the harness when `run` threw. Does not block.
 */
export type Verdict = 'pass' | 'fail' | 'advisory' | 'error';

export interface VerifierResult {
  readonly verdict: Verdict;
  /** Markdown surfaced to the next iteration on `fail` and `advisory`. */
  readonly feedback?: string;
  /** Structured payload persisted verbatim in the per-verifier file. */
  readonly details?: Readonly<Record<string, unknown>>;
}

/** State handed to each `Verifier.run` call. */
export interface VerifierContext {
  readonly runDir: string;
  /** Iteration whose post-state is being verified, e.g. `exec-0003`. */
  readonly iterId: string;
  readonly selectedTaskId: string;
  /** Parsed `plan.md` after the iteration ran. */
  readonly plan: TaskList;
  /** `run_dir/artifact`. */
  readonly artifactDir: string;
}

/** A caller-supplied check dispatched after each executor iteration. */
export interface Verifier {
  /** Filesystem-safe name, unique within a run. Names the telemetry file and feedback section. */
  readonly name: string;
  appliesTo(taskId: string): boolean;
  run(ctx: VerifierContext): Promise<VerifierResult>;
}

/** Telemetry row for one verifier invocation, aggregated into `run.json`. */
export interface VerifierRun {
  readonly iterId: string;
  readonly name: string;
  readonly taskId: string;
  readonly verdict: Verdict;
  readonly startedAt: string;
  readonly durationMs: number;
  /** Run-dir-relative path of the per-verifier file, which also holds feedback and details. */
  readonly path: string;
}
