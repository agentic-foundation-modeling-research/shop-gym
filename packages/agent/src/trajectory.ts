/**
 * Trajectory: the record of one agent episode.
 *
 * Every adapter produces the same shape, so telemetry, replay, and grading
 * never depend on the SDK behind a run. Steps are append-only and carry
 * real timestamps; assistant messages carry per-call usage.
 */

import { createHash } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { type Usage, usageSchema } from '@shop-gym/core';
import { z } from 'zod';

import type { ModelRef } from './types.js';

const timestamp = z.iso.datetime();

/** One step of a trajectory, discriminated by `kind`. */
export const trajectoryStepSchema = z.discriminatedUnion('kind', [
  z.object({
    kind: z.literal('message'),
    timestamp,
    role: z.enum(['user', 'assistant']),
    text: z.string(),
    /** Set on assistant messages only. */
    model: z.string().optional(),
    stopReason: z.string().optional(),
    usage: usageSchema.optional(),
  }),
  z.object({ kind: z.literal('thought'), timestamp, text: z.string() }),
  z.object({
    kind: z.literal('tool_call'),
    timestamp,
    callId: z.string(),
    tool: z.string(),
    arguments: z.record(z.string(), z.unknown()),
  }),
  z.object({
    kind: z.literal('tool_result'),
    timestamp,
    callId: z.string(),
    output: z.string(),
    isError: z.boolean(),
  }),
  z.object({
    kind: z.literal('screenshot'),
    timestamp,
    callId: z.string(),
    /** Path of the saved image, relative to the trajectory's log dir. */
    path: z.string(),
  }),
  z.object({ kind: z.literal('error'), timestamp, message: z.string() }),
]);

export type TrajectoryStep = z.infer<typeof trajectoryStepSchema>;

/** A step as handed to `TrajectoryRecorder.record`, before it is stamped. */
export type TrajectoryStepInput = TrajectoryStep extends infer S
  ? S extends TrajectoryStep
    ? Omit<S, 'timestamp'>
    : never
  : never;

/** The full record of one episode. */
export const trajectorySchema = z.object({
  runtime: z.string(),
  model: z.object({ provider: z.string(), id: z.string() }),
  startedAt: timestamp,
  endedAt: timestamp,
  /** SHA-256 of the prompt text, for matching a trajectory to its prompt file. */
  promptSha256: z.string().regex(/^[0-9a-f]{64}$/),
  steps: z.array(trajectoryStepSchema),
  /** Sum of the usage of every assistant message. */
  usage: usageSchema,
});

export type Trajectory = z.infer<typeof trajectorySchema>;

/** Hex SHA-256 of a string. */
export function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

const ZERO_USAGE: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, costUsd: 0 };

/** Add two usage records field by field. */
export function addUsage(a: Usage, b: Usage): Usage {
  return {
    input: a.input + b.input,
    output: a.output + b.output,
    cacheRead: a.cacheRead + b.cacheRead,
    cacheWrite: a.cacheWrite + b.cacheWrite,
    costUsd: a.costUsd + b.costUsd,
  };
}

/** Collects steps with timestamps and finishes into a `Trajectory`. */
export class TrajectoryRecorder {
  private readonly steps: TrajectoryStep[] = [];
  private readonly startedAt = new Date();

  constructor(
    private readonly runtime: string,
    private readonly model: ModelRef,
    private readonly promptSha256: string,
    private readonly onEvent?: (step: TrajectoryStep) => void,
  ) {}

  /** Append a step stamped with the current time and notify the listener. */
  record(step: TrajectoryStepInput): void {
    const stamped = { ...step, timestamp: new Date().toISOString() } as TrajectoryStep;
    this.steps.push(stamped);
    this.onEvent?.(stamped);
  }

  /** Build the trajectory. The recorder may keep recording afterwards. */
  finish(): Trajectory {
    let usage = ZERO_USAGE;
    for (const step of this.steps) {
      if (step.kind === 'message' && step.usage !== undefined) {
        usage = addUsage(usage, step.usage);
      }
    }
    return {
      runtime: this.runtime,
      model: { provider: this.model.provider, id: this.model.id },
      startedAt: this.startedAt.toISOString(),
      endedAt: new Date().toISOString(),
      promptSha256: this.promptSha256,
      steps: [...this.steps],
      usage,
    };
  }
}

/** Write a trajectory as pretty JSON, creating parent directories. */
export async function writeTrajectory(filePath: string, trajectory: Trajectory): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(trajectory, null, 2)}\n`);
}

/** Read and validate a trajectory file. */
export async function readTrajectory(filePath: string): Promise<Trajectory> {
  return trajectorySchema.parse(JSON.parse(await fs.readFile(filePath, 'utf-8')));
}
