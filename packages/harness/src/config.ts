/**
 * Run configuration and result types of the plan-exec loop.
 */

import type { AgentEvent, ModelRef, ToolSet } from '@shop-gym/agent';

import type { Task } from './plan/tasks.js';
import type { Verifier, VerifierRun } from './verifiers/types.js';

/** The two prompt bodies the harness sends. */
export interface Prompts {
  readonly planner: string;
  /** May contain `{{verifier_feedback}}`, rendered from the previous iteration's feedback. */
  readonly execute: string;
}

export type FinalStatus =
  | 'completed'
  | 'budget_exhausted'
  | 'invalid_plan'
  | 'protocol_violation'
  | 'timeout'
  | 'runtime_error';

export interface PlanExecLoopConfig {
  /** Workspace root. Empty or absent for a fresh run, populated to resume. */
  readonly runDir: string;
  readonly prompts: Prompts;
  /** System prompt for every iteration, also written to `AGENTS.md`. */
  readonly agentsMd: string;
  /** Directory copied into `artifact/` at creation and kept immutable. */
  readonly artifactSeedDir?: string;
  /** Executor iterations granted to this call. Prior iterations on disk do not count. */
  readonly maxIters: number;
  /** Per-iteration wall clock budget. */
  readonly timeoutMs: number;
  readonly model: ModelRef;
  readonly tools: ToolSet;
  readonly verifiers?: readonly Verifier[];
  /** Truncation budget of verifier feedback rendered into the prompt. */
  readonly verifierFeedbackMaxChars?: number;
  readonly onEvent?: (iterId: string, event: AgentEvent) => void;
}

export const DEFAULT_VERIFIER_FEEDBACK_MAX_CHARS = 4000;

export interface PlanExecLoopResult {
  readonly runDir: string;
  readonly finalStatus: FinalStatus;
  /** 0 or 1. */
  readonly planIterCount: number;
  readonly execIterCount: number;
  /** Run-dir-relative `trajectory.json` paths, one per counted iteration. */
  readonly trajectoryPaths: readonly string[];
  /** Tasks of the final `plan.md`, empty when it does not parse. */
  readonly tasksFinal: readonly Task[];
  readonly verifierRuns: readonly VerifierRun[];
}

export class HarnessConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'HarnessConfigError';
  }
}

const VERIFIER_NAME_RE = /^[A-Za-z0-9_.-]+$/;

/** @throws HarnessConfigError on an invalid config. */
export function validateConfig(config: PlanExecLoopConfig): void {
  if (!Number.isInteger(config.maxIters) || config.maxIters < 1) {
    throw new HarnessConfigError(`maxIters must be a positive integer, got ${config.maxIters}`);
  }
  if (!(config.timeoutMs > 0)) {
    throw new HarnessConfigError(`timeoutMs must be positive, got ${config.timeoutMs}`);
  }
  const maxChars = config.verifierFeedbackMaxChars ?? DEFAULT_VERIFIER_FEEDBACK_MAX_CHARS;
  if (!Number.isInteger(maxChars) || maxChars < 1) {
    throw new HarnessConfigError(
      `verifierFeedbackMaxChars must be a positive integer, got ${maxChars}`,
    );
  }
  const names = new Set<string>();
  for (const verifier of config.verifiers ?? []) {
    if (!VERIFIER_NAME_RE.test(verifier.name)) {
      throw new HarnessConfigError(`verifier name is not filesystem-safe: '${verifier.name}'`);
    }
    if (names.has(verifier.name)) {
      throw new HarnessConfigError(`duplicate verifier name: '${verifier.name}'`);
    }
    names.add(verifier.name);
  }
}
