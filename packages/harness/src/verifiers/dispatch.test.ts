import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { parse } from '../plan/parser.js';
import { dispatchVerifiers, renderFeedbackForPrompt } from './dispatch.js';
import type { Verifier, VerifierResult } from './types.js';

function verifier(name: string, result: VerifierResult | Error, applies = true): Verifier {
  return {
    name,
    appliesTo: () => applies,
    run: async () => {
      if (result instanceof Error) {
        throw result;
      }
      return result;
    },
  };
}

let runDir: string;
let iterDir: string;
let planPath: string;
beforeEach(async () => {
  runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'disp-'));
  iterDir = path.join(runDir, 'iters', 'exec-0001');
  await fs.mkdir(iterDir, { recursive: true });
  planPath = path.join(runDir, 'plan.md');
  await fs.writeFile(planPath, '## Tasks\n- [x] a\n- [ ] b\n');
});

async function dispatch(verifiers: Verifier[]) {
  return dispatchVerifiers({
    verifiers,
    iterDir,
    iterId: 'exec-0001',
    runDir,
    selectedTaskId: 'a',
    plan: parse(await fs.readFile(planPath, 'utf-8')),
    planPath,
  });
}

describe('dispatchVerifiers', () => {
  it('writes nothing when no verifier applies', async () => {
    const outcome = await dispatch([verifier('v', { verdict: 'pass' }, false)]);
    expect(outcome).toEqual({ runs: [], blocking: false });
    await expect(fs.stat(path.join(iterDir, 'checks'))).rejects.toThrow();
  });

  it('records a pass and leaves the plan alone', async () => {
    const outcome = await dispatch([verifier('v', { verdict: 'pass', details: { n: 1 } })]);
    expect(outcome.blocking).toBe(false);
    expect(outcome.runs[0]).toMatchObject({
      iterId: 'exec-0001',
      name: 'v',
      taskId: 'a',
      verdict: 'pass',
      path: 'iters/exec-0001/checks/verifiers/v.json',
    });
    const record = JSON.parse(
      await fs.readFile(path.join(iterDir, 'checks', 'verifiers', 'v.json'), 'utf-8'),
    );
    expect(record).toMatchObject({ verdict: 'pass', details: { n: 1 }, feedback: '' });
    expect(await fs.readFile(planPath, 'utf-8')).toBe('## Tasks\n- [x] a\n- [ ] b\n');
  });

  it('reopens the task and writes feedback.md on fail', async () => {
    const outcome = await dispatch([
      verifier('lint', { verdict: 'fail', feedback: 'broken\n' }),
      verifier('hint', { verdict: 'advisory', feedback: 'consider x' }),
    ]);
    expect(outcome.blocking).toBe(true);
    expect(await fs.readFile(planPath, 'utf-8')).toBe('## Tasks\n- [~] a\n- [ ] b\n');
    const feedback = await fs.readFile(
      path.join(iterDir, 'checks', 'verifiers', 'feedback.md'),
      'utf-8',
    );
    expect(feedback).toBe('## lint\n\nbroken\n\n## hint\n\nconsider x\n');
  });

  it('turns a thrown verifier into a non-blocking error verdict', async () => {
    const outcome = await dispatch([verifier('boom', new Error('kaboom'))]);
    expect(outcome.blocking).toBe(false);
    expect(outcome.runs[0]?.verdict).toBe('error');
    const record = JSON.parse(
      await fs.readFile(path.join(iterDir, 'checks', 'verifiers', 'boom.json'), 'utf-8'),
    );
    expect(record.feedback).toBe('kaboom');
  });
});

describe('renderFeedbackForPrompt', () => {
  it('returns empty for a missing file and truncates long bodies', async () => {
    const file = path.join(runDir, 'fb.md');
    expect(await renderFeedbackForPrompt(file, 10)).toBe('');
    await fs.writeFile(file, 'x'.repeat(20));
    expect(await renderFeedbackForPrompt(file, 10)).toBe(`${'x'.repeat(10)}\n[...truncated]`);
    expect(await renderFeedbackForPrompt(file, 20)).toBe('x'.repeat(20));
  });
});
