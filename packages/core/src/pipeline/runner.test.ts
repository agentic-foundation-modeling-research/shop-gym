import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { orderSteps, runPipeline } from './runner.js';
import {
  MissingInputError,
  PipelineConfigError,
  type Step,
  StepFailedError,
  StepOutputMissingError,
} from './step.js';

let outDir: string;

beforeEach(() => {
  outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'shopgym-pipeline-'));
});

afterEach(() => {
  fs.rmSync(outDir, { recursive: true, force: true });
});

interface Ctx {
  readonly runs: string[];
}

function writer(id: string, inputs: string[], outputs: string[], body = id): Step<Ctx> {
  return {
    id,
    inputs,
    outputs,
    async run(ctx) {
      ctx.context.runs.push(id);
      for (const out of outputs) {
        const full = path.join(ctx.outDir, out);
        fs.mkdirSync(path.dirname(full), { recursive: true });
        fs.writeFileSync(full, body);
      }
    },
  };
}

describe('orderSteps', () => {
  it('orders consumers after producers regardless of input order', () => {
    const a = writer('a', [], ['a.txt']);
    const b = writer('b', ['a.txt'], ['b.txt']);
    const c = writer('c', ['b.txt'], ['c.txt']);
    expect(orderSteps([c, b, a]).map((s) => s.id)).toEqual(['a', 'b', 'c']);
  });

  it('treats a file inside an output directory as produced by that step', () => {
    const synth = writer('synth', [], ['data']);
    const check = writer('check', ['data/products.json'], ['report.json']);
    expect(orderSteps([check, synth]).map((s) => s.id)).toEqual(['synth', 'check']);
  });

  it('rejects cycles', () => {
    const a = writer('a', ['b.txt'], ['a.txt']);
    const b = writer('b', ['a.txt'], ['b.txt']);
    expect(() => orderSteps([a, b])).toThrow(PipelineConfigError);
  });

  it('rejects two steps writing the same output', () => {
    expect(() => orderSteps([writer('a', [], ['x']), writer('b', [], ['x'])])).toThrow(
      PipelineConfigError,
    );
  });

  it('rejects a step without outputs', () => {
    expect(() => orderSteps([writer('a', [], [])])).toThrow(PipelineConfigError);
  });
});

describe('runPipeline', () => {
  it('runs every step once and skips all of them on a second run', async () => {
    const steps = [writer('a', [], ['a.txt']), writer('b', ['a.txt'], ['b.txt'])];
    const first = await runPipeline(steps, { outDir, context: { runs: [] } });
    expect(first.map((r) => r.status)).toEqual(['ran', 'ran']);

    const ctx: Ctx = { runs: [] };
    const second = await runPipeline(steps, { outDir, context: ctx });
    expect(second.map((r) => r.status)).toEqual(['skipped', 'skipped']);
    expect(ctx.runs).toEqual([]);
  });

  it('reruns a step whose output was deleted', async () => {
    const steps = [writer('a', [], ['a.txt']), writer('b', ['a.txt'], ['b.txt'])];
    await runPipeline(steps, { outDir, context: { runs: [] } });
    fs.rmSync(path.join(outDir, 'b.txt'));

    const ctx: Ctx = { runs: [] };
    await runPipeline(steps, { outDir, context: ctx });
    expect(ctx.runs).toEqual(['b']);
  });

  it('cascades through downstream steps only when the forced output changed', async () => {
    let body = 'v1';
    const a: Step<Ctx> = {
      id: 'a',
      inputs: [],
      outputs: ['a.txt'],
      async run(ctx) {
        ctx.context.runs.push('a');
        fs.writeFileSync(path.join(ctx.outDir, 'a.txt'), body);
      },
    };
    const b = writer('b', ['a.txt'], ['b.txt']);
    await runPipeline([a, b], { outDir, context: { runs: [] } });

    const unchanged: Ctx = { runs: [] };
    await runPipeline([a, b], { outDir, context: unchanged, from: 'a' });
    expect(unchanged.runs).toEqual(['a']);

    body = 'v2';
    const changed: Ctx = { runs: [] };
    await runPipeline([a, b], { outDir, context: changed, from: 'a' });
    expect(changed.runs).toEqual(['a', 'b']);
  });

  it('stops after the `to` step', async () => {
    const steps = [writer('a', [], ['a.txt']), writer('b', ['a.txt'], ['b.txt'])];
    const reports = await runPipeline(steps, { outDir, context: { runs: [] }, to: 'a' });
    expect(reports.map((r) => r.id)).toEqual(['a']);
    expect(fs.existsSync(path.join(outDir, 'b.txt'))).toBe(false);
  });

  it('removes stale outputs before rerunning but keeps outputs of an unfinished attempt', async () => {
    const seed = path.join(outDir, 'seed.txt');
    fs.writeFileSync(seed, 'one');
    const cache: Step<Ctx> = {
      id: 'cache',
      inputs: [seed],
      outputs: ['cache'],
      async run(ctx) {
        const dir = path.join(ctx.outDir, 'cache');
        fs.mkdirSync(dir, { recursive: true });
        ctx.context.runs.push(fs.readdirSync(dir).join(','));
        fs.writeFileSync(path.join(dir, 'item.json'), '{}');
      },
    };

    fs.mkdirSync(path.join(outDir, 'cache'));
    fs.writeFileSync(path.join(outDir, 'cache', 'partial.json'), '{}');
    const resumed: Ctx = { runs: [] };
    await runPipeline([cache], { outDir, context: resumed });
    expect(resumed.runs).toEqual(['partial.json']);

    fs.writeFileSync(seed, 'two');
    const stale: Ctx = { runs: [] };
    await runPipeline([cache], { outDir, context: stale });
    expect(stale.runs).toEqual(['']);
  });

  it('fails fast when an input is missing', async () => {
    const step = writer('b', ['never.txt'], ['b.txt']);
    await expect(runPipeline([step], { outDir, context: { runs: [] } })).rejects.toBeInstanceOf(
      MissingInputError,
    );
  });

  it('wraps step errors and does not record completion', async () => {
    const boom: Step<Ctx> = {
      id: 'boom',
      inputs: [],
      outputs: ['x'],
      async run() {
        throw new Error('nope');
      },
    };
    await expect(runPipeline([boom], { outDir, context: { runs: [] } })).rejects.toBeInstanceOf(
      StepFailedError,
    );
    expect(fs.existsSync(path.join(outDir, '.pipeline', 'boom.json'))).toBe(false);
  });

  it('rejects a step that returns without writing its outputs', async () => {
    const lazy: Step<Ctx> = { id: 'lazy', inputs: [], outputs: ['x'], run: async () => undefined };
    await expect(runPipeline([lazy], { outDir, context: { runs: [] } })).rejects.toBeInstanceOf(
      StepOutputMissingError,
    );
  });

  it('rejects unknown from and to ids', async () => {
    const steps = [writer('a', [], ['a.txt'])];
    await expect(
      runPipeline(steps, { outDir, context: { runs: [] }, from: 'zzz' }),
    ).rejects.toBeInstanceOf(PipelineConfigError);
  });
});
