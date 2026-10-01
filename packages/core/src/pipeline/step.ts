/**
 * Step pipeline types and errors.
 *
 * A `Step` is a unit of work that reads declared input paths and writes
 * declared output paths under a pipeline output directory. Dependencies are
 * derived from those paths: a step runs after every step whose outputs
 * overlap its inputs. There is no separate dependency declaration to keep
 * in sync.
 */

/** What a step receives when it runs. */
export interface StepContext<C> {
  /** Absolute pipeline output directory; relative step paths resolve against it. */
  readonly outDir: string;
  /** Caller-supplied services and configuration shared by all steps. */
  readonly context: C;
  readonly log: (line: string) => void;
  readonly signal: AbortSignal;
}

export interface Step<C> {
  /** Unique id, `[a-z][a-z0-9_]*`. */
  readonly id: string;
  /**
   * Files or directories the step reads. Relative paths resolve against the
   * output directory; absolute paths may point anywhere (seed inputs).
   * Every input must exist when the step runs.
   */
  readonly inputs: readonly string[];
  /**
   * Files or directories the step writes, relative to the output directory.
   * At least one. Every output must exist after `run` returns.
   */
  readonly outputs: readonly string[];
  run(ctx: StepContext<C>): Promise<void>;
}

export interface PipelineOptions<C> {
  readonly outDir: string;
  readonly context: C;
  /** Force this step to run even if it is complete; stale downstream steps follow. */
  readonly from?: string;
  /** Stop after this step. */
  readonly to?: string;
  readonly log?: (line: string) => void;
  readonly signal?: AbortSignal;
}

export interface StepReport {
  readonly id: string;
  readonly status: 'ran' | 'skipped';
  readonly durationMs: number;
}

/** The step list itself is invalid: duplicate ids or outputs, a cycle, or an unknown `from` / `to`. */
export class PipelineConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PipelineConfigError';
  }
}

/** A step was about to run but one of its inputs does not exist. */
export class MissingInputError extends Error {
  readonly stepId: string;
  readonly path: string;

  constructor(stepId: string, inputPath: string) {
    super(`Step '${stepId}' input does not exist: ${inputPath}`);
    this.name = 'MissingInputError';
    this.stepId = stepId;
    this.path = inputPath;
  }
}

/** A step's `run` threw. The original error is `cause`. */
export class StepFailedError extends Error {
  readonly stepId: string;

  constructor(stepId: string, cause: unknown) {
    const reason = cause instanceof Error ? cause.message : String(cause);
    super(`Step '${stepId}' failed: ${reason}`, { cause });
    this.name = 'StepFailedError';
    this.stepId = stepId;
  }
}

/** A step returned without producing one of its declared outputs. */
export class StepOutputMissingError extends Error {
  readonly stepId: string;
  readonly path: string;

  constructor(stepId: string, outputPath: string) {
    super(`Step '${stepId}' finished without writing its output: ${outputPath}`);
    this.name = 'StepOutputMissingError';
    this.stepId = stepId;
    this.path = outputPath;
  }
}
