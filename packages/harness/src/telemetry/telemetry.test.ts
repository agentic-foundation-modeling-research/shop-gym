import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { describe, expect, it } from 'vitest';

import { PLAN_ITER_ID, execIterId, isExecIterId, isIterDirName, iterDirPath } from './ids.js';
import { reconstruct, scanIterDirs } from './recovery.js';
import { REDACTED, scrubSecrets } from './secrets.js';
import { atomicWriteJson, readPriorRunSummary } from './summary.js';

describe('ids', () => {
  it('formats and recognises iteration ids', () => {
    expect(execIterId(1)).toBe('exec-0001');
    expect(execIterId(123)).toBe('exec-0123');
    expect(isExecIterId('exec-0001')).toBe(true);
    expect(isExecIterId('exec-0001.aborted-1')).toBe(false);
    expect(isIterDirName(PLAN_ITER_ID)).toBe(true);
    expect(isIterDirName('exec-0002')).toBe(true);
    expect(isIterDirName('random')).toBe(false);
    expect(iterDirPath('/r/iters', 'plan')).toBe(path.join('/r/iters', 'plan'));
  });
});

describe('scrubSecrets', () => {
  it('redacts secret-looking keys recursively and keeps the rest', () => {
    expect(
      scrubSecrets({
        apiKey: 'k',
        nested: [{ access_token: 't', model: 'm' }],
        Authorization: 'Bearer x',
        maxIters: 3,
      }),
    ).toEqual({
      apiKey: REDACTED,
      nested: [{ access_token: REDACTED, model: 'm' }],
      Authorization: REDACTED,
      maxIters: 3,
    });
  });
});

async function makeRun(): Promise<string> {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'rec-'));
  await fs.mkdir(path.join(runDir, 'iters'));
  return runDir;
}

async function addIter(runDir: string, id: string, withTrajectory = true): Promise<void> {
  const dir = path.join(runDir, 'iters', id);
  await fs.mkdir(dir, { recursive: true });
  if (withTrajectory) {
    await fs.writeFile(path.join(dir, 'trajectory.json'), '{}');
  }
}

describe('scanIterDirs', () => {
  it('counts only iteration dirs that have a trajectory', async () => {
    const runDir = await makeRun();
    await addIter(runDir, 'plan');
    await addIter(runDir, 'exec-0001');
    await addIter(runDir, 'exec-0002', false);
    await addIter(runDir, 'exec-0003.aborted-1');
    const scan = await scanIterDirs(path.join(runDir, 'iters'));
    expect(scan.planIterCount).toBe(1);
    expect(scan.execIterIds).toEqual(['exec-0001']);
    expect(scan.trajectoryPaths).toEqual([
      'iters/plan/trajectory.json',
      'iters/exec-0001/trajectory.json',
    ]);
  });
});

describe('reconstruct', () => {
  it('throws without iters/', async () => {
    const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'rec-'));
    await expect(reconstruct(runDir)).rejects.toThrow('missing iters/');
  });

  it('derives completed vs budget_exhausted from plan.md', async () => {
    const runDir = await makeRun();
    await addIter(runDir, 'plan');
    await fs.writeFile(path.join(runDir, 'plan.md'), '## Tasks\n- [ ] a\n');
    expect((await reconstruct(runDir)).finalStatus).toBe('budget_exhausted');
    await fs.writeFile(path.join(runDir, 'plan.md'), '## Tasks\n- [x] a\n');
    expect((await reconstruct(runDir)).finalStatus).toBe('completed');
  });

  it('reports invalid_plan and planner protocol violations', async () => {
    const runDir = await makeRun();
    await addIter(runDir, 'plan');
    await fs.writeFile(path.join(runDir, 'plan.md'), '## Tasks\n- [ ] a\n- [ ] a\n');
    expect((await reconstruct(runDir)).finalStatus).toBe('invalid_plan');
    await fs.writeFile(path.join(runDir, 'plan.md'), '## Tasks\n- [ ] a\n');
    await fs.mkdir(path.join(runDir, 'iters', 'plan', 'checks'));
    await fs.writeFile(
      path.join(runDir, 'iters', 'plan', 'checks', 'protocol.json'),
      JSON.stringify({ iterId: 'plan', passed: false, violations: ['seed_mutated: x'] }),
    );
    expect((await reconstruct(runDir)).finalStatus).toBe('protocol_violation');
  });
});

describe('run summary io', () => {
  it('writes atomically and reads back status plus history', async () => {
    const runDir = await makeRun();
    expect(await readPriorRunSummary(runDir)).toBeUndefined();
    await atomicWriteJson(path.join(runDir, 'run.json'), {
      finalStatus: 'timeout',
      configSnapshot: {
        resumeHistory: [{ startedAt: 's', endedAt: 'e', finalStatus: 'timeout' }],
      },
    });
    expect(await fs.readdir(runDir)).toEqual(['iters', 'run.json']);
    expect(await readPriorRunSummary(runDir)).toEqual({
      finalStatus: 'timeout',
      resumeHistory: [{ startedAt: 's', endedAt: 'e', finalStatus: 'timeout' }],
    });
  });
});
