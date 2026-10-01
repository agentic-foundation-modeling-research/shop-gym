/**
 * `run.json`: the result of the run plus a secret-free echo of the config,
 * rewritten atomically after every iteration.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { z } from 'zod';

import type { FinalStatus, PlanExecLoopResult } from '../config.js';
import { scrubSecrets } from './secrets.js';

export const FINAL_STATUSES: readonly FinalStatus[] = [
  'completed',
  'budget_exhausted',
  'invalid_plan',
  'protocol_violation',
  'timeout',
  'runtime_error',
];

/** One attempt (fresh run or resume) of a run dir. */
export const resumeAttemptSchema = z.object({
  startedAt: z.string(),
  endedAt: z.string(),
  finalStatus: z.enum(FINAL_STATUSES),
});

export type ResumeAttempt = z.infer<typeof resumeAttemptSchema>;

export interface ConfigSnapshot {
  readonly maxIters: number;
  readonly timeoutMs: number;
  readonly verifierFeedbackMaxChars: number;
  readonly artifactSeedDir: string | null;
  readonly model: { readonly provider: string; readonly id: string; readonly thinking?: string };
  readonly tools: readonly string[];
  readonly verifiers: readonly string[];
  /** One entry per attempt; the tail entry tracks the attempt in flight. */
  readonly resumeHistory: readonly ResumeAttempt[];
}

export interface RunSummary extends PlanExecLoopResult {
  readonly configSnapshot: ConfigSnapshot;
}

/** Atomically rewrite `<runDir>/run.json`. */
export async function writeRunSummary(runDir: string, summary: RunSummary): Promise<void> {
  const payload = { ...summary, configSnapshot: scrubSecrets(summary.configSnapshot) };
  await atomicWriteJson(path.join(runDir, 'run.json'), payload);
}

/** Loosely read a prior `run.json`; `undefined` when missing or malformed. */
export async function readPriorRunSummary(
  runDir: string,
): Promise<{ finalStatus?: FinalStatus; resumeHistory: ResumeAttempt[] } | undefined> {
  let payload: unknown;
  try {
    payload = JSON.parse(await fs.readFile(path.join(runDir, 'run.json'), 'utf-8'));
  } catch {
    return undefined;
  }
  const parsed = z
    .object({
      finalStatus: z.enum(FINAL_STATUSES).optional(),
      configSnapshot: z
        .object({ resumeHistory: z.array(resumeAttemptSchema).optional() })
        .loose()
        .optional(),
    })
    .loose()
    .safeParse(payload);
  if (!parsed.success) {
    return undefined;
  }
  const finalStatus = parsed.data.finalStatus;
  return {
    ...(finalStatus === undefined ? {} : { finalStatus }),
    resumeHistory: parsed.data.configSnapshot?.resumeHistory ?? [],
  };
}

/** Write pretty JSON via a temp file and rename so readers never see a partial file. */
export async function atomicWriteJson(filePath: string, data: unknown): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const tmp = path.join(
    path.dirname(filePath),
    `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`,
  );
  try {
    const handle = await fs.open(tmp, 'w');
    try {
      await handle.writeFile(`${JSON.stringify(data, null, 2)}\n`);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.rename(tmp, filePath);
  } catch (error) {
    await fs.rm(tmp, { force: true });
    throw error;
  }
}
