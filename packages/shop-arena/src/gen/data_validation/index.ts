/**
 * `data_validation` step: schema + referential checks on `<shopDir>/data/`,
 * then a hosting smoke against the pristine backend template. Writes
 * `<shopDir>/data_validation.json` and fails the step when anything is off.
 */

import * as path from 'node:path';

import type { Step, StepContext } from '@shop-gym/core';

import { defaultBackendTemplateDir } from '../build/seed.js';
import { spawnSidecar } from '../build/sidecar.js';
import type { GenContext } from '../context.js';
import { writeJsonFile } from '../io.js';
import { type HostingSmokeResult, runHostingSmoke } from './hosting_check.js';
import { checkDataset } from './schema_check.js';

export {
  type HostingCheck,
  type HostingSmokeOptions,
  type HostingSmokeResult,
  runHostingSmoke,
} from './hosting_check.js';
export { checkDataset } from './schema_check.js';

export const DATA_VALIDATION_FILE = 'data_validation.json';

export class DataValidationError extends Error {
  constructor(readonly problems: readonly string[]) {
    super(`dataset failed validation:\n${problems.map((p) => `  - ${p}`).join('\n')}`);
    this.name = 'DataValidationError';
  }
}

export interface DataValidationReport {
  readonly ok: boolean;
  readonly dataDir: string;
  readonly schemaProblems: readonly string[];
  /** `null` when the schema checks already failed. */
  readonly hosting: HostingSmokeResult | null;
}

export async function runDataValidation(ctx: StepContext<GenContext>): Promise<void> {
  const dataDir = path.join(ctx.outDir, 'data');
  const schemaProblems = await checkDataset(dataDir);
  let hosting: HostingSmokeResult | null = null;
  if (schemaProblems.length === 0) {
    hosting = await runHostingSmoke({
      dataDir,
      backendDir: defaultBackendTemplateDir(),
      logPath: path.join(ctx.outDir, '.shop_gen', 'validation', 'sidecar.log'),
      launch: ctx.context.sidecarLaunch ?? spawnSidecar,
    });
    for (const c of hosting.checks)
      ctx.log(`[data_validation] ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
  }
  const problems = [
    ...schemaProblems,
    ...(hosting?.checks ?? []).filter((c) => !c.ok).map((c) => `hosting ${c.name}: ${c.detail}`),
  ];
  const report: DataValidationReport = {
    ok: problems.length === 0,
    dataDir,
    schemaProblems,
    hosting,
  };
  await writeJsonFile(path.join(ctx.outDir, DATA_VALIDATION_FILE), report);
  if (problems.length > 0) throw new DataValidationError(problems);
}

export function dataValidationStep(): Step<GenContext> {
  return {
    id: 'data_validation',
    inputs: ['data'],
    outputs: [DATA_VALIDATION_FILE],
    run: runDataValidation,
  };
}
