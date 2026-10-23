/**
 * Step pipeline runner.
 *
 * `runPipeline` orders steps by their input/output overlap and runs each
 * one that is not complete. A step is complete when every declared output
 * exists and `<outDir>/.pipeline/<id>.json` records the fingerprint of its
 * inputs as they are now. Because completion is derived from the
 * filesystem, deleting an output or changing an input is all it takes to
 * make a step run again.
 *
 * Output cleanup follows the input fingerprint: when a step's inputs
 * changed since it last completed (or it is forced with `from`), its
 * outputs are removed before it runs so no stale cache survives. When a
 * step never completed (no record), existing outputs are kept so a step
 * that caches per-item progress can resume after an interruption.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

import { fingerprintPaths } from './fingerprint.js';
import {
  MissingInputError,
  PipelineConfigError,
  type PipelineOptions,
  type Step,
  StepFailedError,
  StepOutputMissingError,
  type StepReport,
} from './step.js';

const STATE_DIR = '.pipeline';
const ID_PATTERN = /^[a-z][a-z0-9_]*$/;

interface StepRecord {
  readonly inputFingerprint: string;
  readonly completedAt: string;
}

/**
 * Order steps so every step comes after the steps that produce its inputs.
 *
 * @throws {PipelineConfigError} Duplicate ids, two steps writing the same path, or a cycle.
 */
export function orderSteps<C>(steps: readonly Step<C>[]): Step<C>[] {
  validateSteps(steps);
  const producers = new Map<Step<C>, Set<Step<C>>>(steps.map((s) => [s, new Set()]));
  for (const consumer of steps) {
    for (const producer of steps) {
      if (producer !== consumer && overlaps(producer.outputs, consumer.inputs)) {
        producers.get(consumer)?.add(producer);
      }
    }
  }
  const ordered: Step<C>[] = [];
  const placed = new Set<Step<C>>();
  while (ordered.length < steps.length) {
    const ready = steps.find(
      (s) => !placed.has(s) && [...(producers.get(s) ?? [])].every((p) => placed.has(p)),
    );
    if (ready === undefined) {
      const stuck = steps.filter((s) => !placed.has(s)).map((s) => s.id);
      throw new PipelineConfigError(`Dependency cycle among steps: ${stuck.join(', ')}`);
    }
    ordered.push(ready);
    placed.add(ready);
  }
  return ordered;
}

/**
 * Run every stale step in dependency order.
 *
 * @returns One report per step in execution order, up to and including `to`.
 * @throws {PipelineConfigError} Invalid step list or unknown `from` / `to`.
 * @throws {MissingInputError} A step is due to run but an input is absent.
 * @throws {StepFailedError} A step threw; the original error is `cause`.
 * @throws {StepOutputMissingError} A step returned without writing an output.
 */
export async function runPipeline<C>(
  steps: readonly Step<C>[],
  options: PipelineOptions<C>,
): Promise<StepReport[]> {
  const ordered = orderSteps(steps);
  const outDir = path.resolve(options.outDir);
  const log = options.log ?? (() => undefined);
  const signal = options.signal ?? new AbortController().signal;
  const from = findStep(ordered, options.from, 'from');
  const to = findStep(ordered, options.to, 'to');

  const reports: StepReport[] = [];
  for (const step of ordered) {
    signal.throwIfAborted();
    const inputs = step.inputs.map((p) => path.resolve(outDir, p));
    const outputs = step.outputs.map((p) => path.resolve(outDir, p));
    const recordPath = path.join(outDir, STATE_DIR, `${step.id}.json`);
    const record = readRecord(recordPath);
    const fingerprint = fingerprintPaths(inputs);
    const forced = step === from;
    const complete =
      !forced && record?.inputFingerprint === fingerprint && outputs.every((p) => fs.existsSync(p));

    if (complete) {
      log(`[${step.id}] up to date`);
      reports.push({ id: step.id, status: 'skipped', durationMs: 0 });
    } else {
      for (const input of inputs) {
        if (!fs.existsSync(input)) {
          throw new MissingInputError(step.id, input);
        }
      }
      if (forced || record !== null) {
        for (const output of outputs) {
          fs.rmSync(output, { recursive: true, force: true });
        }
      }
      fs.rmSync(recordPath, { force: true });
      log(`[${step.id}] running`);
      const started = Date.now();
      try {
        await step.run({ outDir, context: options.context, log, signal });
      } catch (err) {
        throw new StepFailedError(step.id, err);
      }
      for (const output of outputs) {
        if (!fs.existsSync(output)) {
          throw new StepOutputMissingError(step.id, output);
        }
      }
      writeRecord(recordPath, {
        inputFingerprint: fingerprintPaths(inputs),
        completedAt: new Date().toISOString(),
      });
      reports.push({ id: step.id, status: 'ran', durationMs: Date.now() - started });
    }

    if (step === to) {
      break;
    }
  }
  return reports;
}

function validateSteps<C>(steps: readonly Step<C>[]): void {
  const ids = new Set<string>();
  const outputs = new Map<string, string>();
  for (const step of steps) {
    if (!ID_PATTERN.test(step.id)) {
      throw new PipelineConfigError(`Invalid step id '${step.id}'`);
    }
    if (ids.has(step.id)) {
      throw new PipelineConfigError(`Duplicate step id '${step.id}'`);
    }
    ids.add(step.id);
    if (step.outputs.length === 0) {
      throw new PipelineConfigError(`Step '${step.id}' declares no outputs`);
    }
    for (const output of step.outputs) {
      if (path.isAbsolute(output)) {
        throw new PipelineConfigError(`Step '${step.id}' output must be relative: ${output}`);
      }
      const normalized = path.normalize(output);
      const owner = outputs.get(normalized);
      if (owner !== undefined) {
        throw new PipelineConfigError(
          `Output '${output}' is written by both '${owner}' and '${step.id}'`,
        );
      }
      outputs.set(normalized, step.id);
    }
  }
}

/** True when any output path and any input path are the same or nested. */
function overlaps(outputs: readonly string[], inputs: readonly string[]): boolean {
  return outputs.some((o) => inputs.some((i) => contains(o, i) || contains(i, o)));
}

function contains(parent: string, child: string): boolean {
  const rel = path.relative(path.normalize(parent), path.normalize(child));
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

function findStep<C>(
  steps: readonly Step<C>[],
  id: string | undefined,
  option: 'from' | 'to',
): Step<C> | undefined {
  if (id === undefined) {
    return undefined;
  }
  const step = steps.find((s) => s.id === id);
  if (step === undefined) {
    throw new PipelineConfigError(`Unknown step '${id}' for '${option}'`);
  }
  return step;
}

function readRecord(recordPath: string): StepRecord | null {
  if (!fs.existsSync(recordPath)) {
    return null;
  }
  const parsed: unknown = JSON.parse(fs.readFileSync(recordPath, 'utf-8'));
  if (
    typeof parsed === 'object' &&
    parsed !== null &&
    typeof (parsed as StepRecord).inputFingerprint === 'string' &&
    typeof (parsed as StepRecord).completedAt === 'string'
  ) {
    return parsed as StepRecord;
  }
  return null;
}

function writeRecord(recordPath: string, record: StepRecord): void {
  fs.mkdirSync(path.dirname(recordPath), { recursive: true });
  const tmp = `${recordPath}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(record, null, 2)}\n`);
  fs.renameSync(tmp, recordPath);
}
