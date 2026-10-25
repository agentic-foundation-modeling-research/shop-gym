/**
 * Human-readable rendering of an iteration's `trajectory.json`.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { type Trajectory, type TrajectoryStep, readTrajectory } from '@shop-gym/agent';

import { iterationMetadataSchema } from './telemetry/metadata.js';
import { TRAJECTORY_FILENAME } from './telemetry/recovery.js';

export interface TraceOptions {
  /** Longest text block printed before truncation. */
  readonly maxChars?: number;
}

const DEFAULT_MAX_CHARS = 2000;

/** Render a trajectory as indented plain text. */
export function renderTrajectory(trajectory: Trajectory, options: TraceOptions = {}): string {
  const maxChars = options.maxChars ?? DEFAULT_MAX_CHARS;
  const started = Date.parse(trajectory.startedAt);
  const durationS = ((Date.parse(trajectory.endedAt) - started) / 1000).toFixed(1);
  const usage = trajectory.usage;
  const lines = [
    `runtime: ${trajectory.runtime}  model: ${trajectory.model.provider}/${trajectory.model.id}`,
    `started: ${trajectory.startedAt}  duration: ${durationS}s`,
    `tokens: in=${usage.input} out=${usage.output} cache_read=${usage.cacheRead} cache_write=${usage.cacheWrite}  cost: $${usage.costUsd.toFixed(4)}`,
    `steps: ${trajectory.steps.length}`,
    '',
  ];
  for (const step of trajectory.steps) {
    const offset = ((Date.parse(step.timestamp) - started) / 1000).toFixed(1).padStart(7);
    lines.push(`[${offset}s] ${renderStep(step, maxChars)}`);
  }
  return `${lines.join('\n')}\n`;
}

/** Render `iters/<id>/`: the metadata header when present, then the trajectory. */
export async function renderIterDir(iterDir: string, options: TraceOptions = {}): Promise<string> {
  const trajectory = await readTrajectory(path.join(iterDir, TRAJECTORY_FILENAME));
  const metadataText = await fs
    .readFile(path.join(iterDir, 'metadata.json'), 'utf-8')
    .catch(() => undefined);
  const header: string[] = [];
  if (metadataText !== undefined) {
    const metadata = iterationMetadataSchema.parse(JSON.parse(metadataText));
    header.push(`iter: ${metadata.iterId} (${metadata.iterKind})`);
    if (metadata.selectedTaskId !== null) {
      header.push(
        `task: ${metadata.selectedTaskId}  completed=[${metadata.completedTaskIds}] blocked=[${metadata.blockedTaskIds}] added=[${metadata.addedTaskIds}]`,
      );
    }
  }
  return header.map((line) => `${line}\n`).join('') + renderTrajectory(trajectory, options);
}

function renderStep(step: TrajectoryStep, maxChars: number): string {
  switch (step.kind) {
    case 'message':
      return `${step.role}> ${indent(clip(step.text, maxChars))}${step.stopReason === undefined ? '' : `  (stop: ${step.stopReason})`}`;
    case 'thought':
      return `thinking: ${indent(clip(step.text, maxChars))}`;
    case 'tool_call':
      return `call ${step.tool} ${clip(JSON.stringify(step.arguments), maxChars)}`;
    case 'tool_result':
      return `${step.isError ? 'ERROR' : 'result'} ${indent(clip(step.output, maxChars))}`;
    case 'screenshot':
      return `screenshot ${step.path}`;
    case 'error':
      return `error: ${clip(step.message, maxChars)}`;
  }
}

function clip(text: string, maxChars: number): string {
  return text.length <= maxChars
    ? text
    : `${text.slice(0, maxChars)}... [${text.length - maxChars} more chars]`;
}

function indent(text: string): string {
  return text.replace(/\n/g, '\n           ');
}
