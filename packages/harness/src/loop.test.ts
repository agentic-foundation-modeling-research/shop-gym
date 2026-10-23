import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { AgentRunRequest, AgentRunResult, AgentRuntime } from '@shop-gym/agent';
import { FakeRuntime, type FakeScript } from '@shop-gym/agent/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { PlanExecLoopConfig } from './config.js';
import { ResumeRefusedError, runPlanExecLoop } from './loop.js';
import { NOTE_PREFIX } from './plan/parser.js';
import type { Verifier, VerifierResult } from './verifiers/types.js';
import { ResumeMismatchError } from './workspace.js';

const MODEL = { provider: 'fake', id: 'scripted' };
const PLAN_AB = '## Tasks\n\n- [ ] a [priority: 2]\n- [ ] b\n';
const PLAN_A_DONE = '## Tasks\n\n- [x] a [priority: 2]\n- [ ] b\n';
const PLAN_AB_DONE = '## Tasks\n\n- [x] a [priority: 2]\n- [x] b\n';
const PLAN_ONE = '## Tasks\n\n- [ ] a\n';
const PLAN_ONE_DONE = '## Tasks\n\n- [x] a\n';

let root: string;
beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'loop-'));
});

function config(overrides: Partial<PlanExecLoopConfig> = {}): PlanExecLoopConfig {
  return {
    runDir: path.join(root, 'run'),
    prompts: { planner: 'PLAN', execute: 'EXEC\n{{verifier_feedback}}\nEND' },
    agentsMd: '# agents\n',
    maxIters: 5,
    timeoutMs: 60_000,
    model: MODEL,
    tools: [],
    ...overrides,
  };
}

const planner = (plan = PLAN_AB): FakeScript => ({ writeFiles: { 'plan.md': plan } });
const exec = (plan: string): FakeScript => ({ writeFiles: { 'plan.md': plan } });

async function read(rel: string, runDir = path.join(root, 'run')): Promise<string> {
  return fs.readFile(path.join(runDir, rel), 'utf-8');
}

async function readJson(rel: string, runDir?: string): Promise<Record<string, unknown>> {
  return JSON.parse(await read(rel, runDir)) as Record<string, unknown>;
}

async function listIters(runDir = path.join(root, 'run')): Promise<string[]> {
  return (await fs.readdir(path.join(runDir, 'iters'))).sort();
}

class ThrowingRuntime implements AgentRuntime {
  readonly name = 'throwing';
  async run(_request: AgentRunRequest): Promise<AgentRunResult> {
    throw new Error('connection refused');
  }
}

function verifier(
  name: string,
  run: (taskId: string) => VerifierResult | Promise<VerifierResult>,
  appliesTo: (taskId: string) => boolean = () => true,
): Verifier {
  return { name, appliesTo, run: async (ctx) => run(ctx.selectedTaskId) };
}

describe('runPlanExecLoop: signature and telemetry', () => {
  it('runs the planner then executors until the plan drains', async () => {
    const runtime = new FakeRuntime([planner(), exec(PLAN_A_DONE), exec(PLAN_AB_DONE)]);
    const result = await runPlanExecLoop(config(), runtime);
    expect(result.finalStatus).toBe('completed');
    expect(result.planIterCount).toBe(1);
    expect(result.execIterCount).toBe(2);
    expect(result.trajectoryPaths).toEqual([
      'iters/plan/trajectory.json',
      'iters/exec-0001/trajectory.json',
      'iters/exec-0002/trajectory.json',
    ]);
    expect(result.tasksFinal.map((t) => [t.id, t.status])).toEqual([
      ['a', 'done'],
      ['b', 'done'],
    ]);

    expect(runtime.requests.map((r) => r.prompt)).toEqual([
      'PLAN',
      '<<<harness-control>>>\nselected_task_id: a\n<<<end>>>\n\nEXEC\n\nEND',
      '<<<harness-control>>>\nselected_task_id: b\n<<<end>>>\n\nEXEC\n\nEND',
    ]);
    expect(runtime.requests[0]?.systemPrompt).toBe('# agents\n');
    expect(runtime.requests[0]?.cwd).toBe(path.join(root, 'run'));
    expect(runtime.requests[1]?.logDir).toBe(path.join(root, 'run', 'iters', 'exec-0001'));

    expect(await read('iters/plan/plan.before.md')).toBe('');
    expect(await read('iters/plan/plan.after.md')).toBe(PLAN_AB);
    expect(await read('iters/exec-0001/plan.before.md')).toBe(PLAN_AB);
    expect(await read('iters/exec-0001/plan.after.md')).toBe(PLAN_A_DONE);
    expect(await readJson('iters/exec-0001/metadata.json')).toMatchObject({
      iterId: 'exec-0001',
      iterKind: 'exec',
      runtime: 'fake',
      selectedTaskId: 'a',
      completedTaskIds: ['a'],
      blockedTaskIds: [],
      addedTaskIds: [],
    });
    expect(await readJson('iters/exec-0001/checks/protocol.json')).toEqual({
      iterId: 'exec-0001',
      passed: true,
      violations: [],
    });
    const summary = await readJson('run.json');
    expect(summary).toMatchObject({
      finalStatus: 'completed',
      execIterCount: 2,
      configSnapshot: {
        maxIters: 5,
        timeoutMs: 60_000,
        model: MODEL,
        tools: [],
        verifiers: [],
      },
    });
    const history = (summary.configSnapshot as { resumeHistory: unknown[] }).resumeHistory;
    expect(history).toHaveLength(1);
  });

  it('stamps the trajectory with the sha of the prompt the harness sent', async () => {
    const runtime = new FakeRuntime([planner(PLAN_ONE), exec(PLAN_ONE_DONE)]);
    await runPlanExecLoop(config(), runtime);
    const trajectory = await readJson('iters/exec-0001/trajectory.json');
    const { sha256 } = await import('@shop-gym/agent');
    expect(trajectory.promptSha256).toBe(sha256(runtime.requests[1]?.prompt as string));
  });

  it('forwards runtime events with the iteration id', async () => {
    const seen: string[] = [];
    const runtime = new FakeRuntime([planner(PLAN_ONE), exec(PLAN_ONE_DONE)]);
    await runPlanExecLoop(
      config({ onEvent: (iterId, event) => seen.push(`${iterId}:${event.kind}`) }),
      runtime,
    );
    expect(seen).toContain('plan:message');
    expect(seen).toContain('exec-0001:message');
  });

  it('rejects invalid configs before touching disk', async () => {
    await expect(runPlanExecLoop(config({ maxIters: 0 }), new FakeRuntime())).rejects.toThrow(
      'maxIters must be a positive integer',
    );
    await expect(fs.stat(path.join(root, 'run'))).rejects.toThrow();
  });
});

describe('runPlanExecLoop: terminal failures', () => {
  it('maps a runtime exception to runtime_error', async () => {
    const result = await runPlanExecLoop(config(), new ThrowingRuntime());
    expect(result.finalStatus).toBe('runtime_error');
    expect(result.planIterCount).toBe(0);
    expect(await listIters()).toEqual(['plan']);
    await expect(read('iters/plan/trajectory.json')).rejects.toThrow();
    expect((await readJson('run.json')).finalStatus).toBe('runtime_error');
  });

  it('maps an error status to runtime_error', async () => {
    const runtime = new FakeRuntime([planner(), { status: 'error', error: 'boom' }]);
    const result = await runPlanExecLoop(config(), runtime);
    expect(result.finalStatus).toBe('runtime_error');
    expect(result.execIterCount).toBe(0);
  });

  it('maps a planner abort to timeout', async () => {
    const result = await runPlanExecLoop(config(), new FakeRuntime([{ status: 'aborted' }]));
    expect(result.finalStatus).toBe('timeout');
    expect(result.planIterCount).toBe(0);
  });

  it('quarantines an executor timeout, skips the task, and keeps going', async () => {
    const runtime = new FakeRuntime([
      planner(),
      { status: 'aborted' },
      exec(PLAN_AB_DONE.replace('[x] a', '[ ] a')),
    ]);
    const result = await runPlanExecLoop(config(), runtime);
    expect(result.finalStatus).toBe('timeout');
    expect(result.execIterCount).toBe(1);
    expect(result.trajectoryPaths).toEqual([
      'iters/plan/trajectory.json',
      'iters/exec-0001/trajectory.json',
    ]);
    expect(await listIters()).toEqual(['exec-0001', 'exec-0001.aborted-1', 'plan']);
    expect(await read('iters/exec-0001.aborted-1/aborted.txt')).toMatch(
      /^aborted_at: .*\nreason: timeout\n$/,
    );
    expect(runtime.requests[2]?.prompt).toContain('selected_task_id: b');
  });

  it('returns budget_exhausted when tasks remain', async () => {
    const runtime = new FakeRuntime([planner(), exec(PLAN_A_DONE)]);
    const result = await runPlanExecLoop(config({ maxIters: 1 }), runtime);
    expect(result.finalStatus).toBe('budget_exhausted');
    expect(result.execIterCount).toBe(1);
  });

  it('returns invalid_plan when the planner writes duplicate ids', async () => {
    const runtime = new FakeRuntime([planner('## Tasks\n- [ ] a\n- [ ] a\n')]);
    const result = await runPlanExecLoop(config(), runtime);
    expect(result.finalStatus).toBe('invalid_plan');
    expect(result.planIterCount).toBe(1);
    expect(result.tasksFinal).toEqual([]);
  });

  it('fails the planner on a seed violation', async () => {
    const seed = path.join(root, 'seed');
    await fs.mkdir(seed);
    await fs.writeFile(path.join(seed, 'fixed.txt'), 'v1');
    const runtime = new FakeRuntime([
      { writeFiles: { 'plan.md': PLAN_AB, 'artifact/fixed.txt': 'v2' } },
    ]);
    const result = await runPlanExecLoop(config({ artifactSeedDir: seed }), runtime);
    expect(result.finalStatus).toBe('protocol_violation');
    expect(await readJson('iters/plan/checks/protocol.json')).toEqual({
      iterId: 'plan',
      passed: false,
      violations: ['seed_mutated: fixed.txt'],
    });
  });
});

describe('runPlanExecLoop: blocked-and-continue', () => {
  it('force-blocks a task whose iteration violates protocol and continues', async () => {
    const runtime = new FakeRuntime([
      planner(),
      exec(PLAN_AB),
      exec(
        `## Tasks\n\n- [!] a [priority: 2] ${NOTE_PREFIX} protocol_violation: selected task 'a' is not terminal in after snapshot (status='pending')\n- [x] b\n`,
      ),
    ]);
    const result = await runPlanExecLoop(config(), runtime);
    expect(result.finalStatus).toBe('completed');
    expect(result.execIterCount).toBe(2);
    expect(result.tasksFinal.map((t) => [t.id, t.status])).toEqual([
      ['a', 'blocked'],
      ['b', 'done'],
    ]);
    const blocked = `## Tasks\n\n- [!] a [priority: 2] ${NOTE_PREFIX} protocol_violation: selected task 'a' is not terminal in after snapshot (status='pending')\n- [ ] b\n`;
    expect(await read('iters/exec-0001/plan.after.md')).toBe(blocked);
    expect(await read('iters/exec-0002/plan.before.md')).toBe(blocked);
    expect(await readJson('iters/exec-0001/checks/protocol.json')).toMatchObject({ passed: false });
    expect(runtime.requests[2]?.prompt).toContain('selected_task_id: b');
  });

  it('force-blocks a task whose iteration leaves plan.md unparseable', async () => {
    const runtime = new FakeRuntime([
      planner(),
      exec('## Tasks\n- [ ] a\n- [ ] a\n'),
      exec(
        `## Tasks\n\n- [!] a [priority: 2] ${NOTE_PREFIX} invalid_plan: duplicate task id: 'a'\n- [x] b\n`,
      ),
    ]);
    const result = await runPlanExecLoop(config(), runtime);
    expect(result.finalStatus).toBe('completed');
    expect(result.tasksFinal.find((t) => t.id === 'a')?.note).toBe(
      "invalid_plan: duplicate task id: 'a'",
    );
  });

  it('blocks the task on an executor seed violation and continues', async () => {
    const seed = path.join(root, 'seed');
    await fs.mkdir(path.join(seed, 'data'), { recursive: true });
    await fs.writeFile(path.join(seed, 'data', 'fixed.txt'), 'v1');
    const runtime = new FakeRuntime([
      planner(),
      { writeFiles: { 'plan.md': PLAN_A_DONE, 'artifact/data/extra.txt': 'new' } },
      exec(
        `## Tasks\n\n- [!] a [priority: 2] ${NOTE_PREFIX} protocol_violation: seed_extended: data/extra.txt\n- [x] b\n`,
      ),
    ]);
    const result = await runPlanExecLoop(config({ artifactSeedDir: seed }), runtime);
    expect(result.finalStatus).toBe('completed');
    expect(result.tasksFinal.find((t) => t.id === 'a')?.status).toBe('blocked');
  });
});

describe('runPlanExecLoop: verifiers', () => {
  it('a passing verifier keeps [x] and records a per-verifier file', async () => {
    const runtime = new FakeRuntime([planner(), exec(PLAN_A_DONE), exec(PLAN_AB_DONE)]);
    const result = await runPlanExecLoop(
      config({ verifiers: [verifier('ok', () => ({ verdict: 'pass' }))] }),
      runtime,
    );
    expect(result.finalStatus).toBe('completed');
    expect(result.verifierRuns.map((r) => [r.iterId, r.verdict])).toEqual([
      ['exec-0001', 'pass'],
      ['exec-0002', 'pass'],
    ]);
    expect(await readJson('iters/exec-0001/checks/verifiers/ok.json')).toMatchObject({
      verdict: 'pass',
      taskId: 'a',
    });
    const summary = await readJson('run.json');
    expect((summary.verifierRuns as unknown[]).length).toBe(2);
  });

  it('a failing verifier reopens the task and the next prompt sees the feedback', async () => {
    let calls = 0;
    const runtime = new FakeRuntime([
      planner(),
      exec(PLAN_A_DONE),
      exec(PLAN_A_DONE),
      exec(PLAN_AB_DONE),
    ]);
    const flaky = verifier('flaky', () =>
      ++calls === 1 ? { verdict: 'fail', feedback: 'fix a' } : { verdict: 'pass' },
    );
    const result = await runPlanExecLoop(config({ verifiers: [flaky] }), runtime);
    expect(result.finalStatus).toBe('completed');
    expect(await read('iters/exec-0001/plan.after.md')).toBe(PLAN_A_DONE);
    expect(await read('iters/exec-0002/plan.before.md')).toBe(
      PLAN_A_DONE.replace('[x] a', '[~] a'),
    );
    expect(runtime.requests[2]?.prompt).toBe(
      '<<<harness-control>>>\nselected_task_id: a\n<<<end>>>\n\nEXEC\n## flaky\n\nfix a\n\nEND',
    );
    expect(runtime.requests[3]?.prompt).not.toContain('fix a');
  });

  it('truncates feedback only when rendering into the prompt', async () => {
    const runtime = new FakeRuntime([planner(), exec(PLAN_A_DONE), exec(PLAN_AB_DONE)]);
    let calls = 0;
    const loud = verifier('loud', () =>
      ++calls === 1 ? { verdict: 'fail', feedback: 'y'.repeat(100) } : { verdict: 'pass' },
    );
    await runPlanExecLoop(config({ verifiers: [loud], verifierFeedbackMaxChars: 20 }), runtime);
    expect(await read('iters/exec-0001/checks/verifiers/feedback.md')).toContain('y'.repeat(100));
    expect(runtime.requests[2]?.prompt).toContain(`## loud\n\n${'y'.repeat(11)}\n[...truncated]`);
  });

  it('an error verdict does not block', async () => {
    const runtime = new FakeRuntime([planner(), exec(PLAN_A_DONE), exec(PLAN_AB_DONE)]);
    const result = await runPlanExecLoop(
      config({ verifiers: [verifier('err', () => ({ verdict: 'error', feedback: 'oops' }))] }),
      runtime,
    );
    expect(result.finalStatus).toBe('completed');
    expect(result.execIterCount).toBe(2);
  });

  it('does not inject feedback when the prompt lacks the placeholder', async () => {
    const runtime = new FakeRuntime([
      planner(),
      exec(PLAN_A_DONE),
      exec(PLAN_A_DONE),
      exec(PLAN_AB_DONE),
    ]);
    let calls = 0;
    const once = verifier('once', () =>
      ++calls === 1 ? { verdict: 'fail', feedback: 'fix a' } : { verdict: 'pass' },
    );
    await runPlanExecLoop(
      config({ prompts: { planner: 'PLAN', execute: 'EXEC' }, verifiers: [once] }),
      runtime,
    );
    expect(runtime.requests[2]?.prompt).toBe(
      '<<<harness-control>>>\nselected_task_id: a\n<<<end>>>\n\nEXEC',
    );
  });
});

describe('runPlanExecLoop: resume', () => {
  it('continues after a timeout without replanning', async () => {
    const first = new FakeRuntime([planner(), exec(PLAN_A_DONE), { status: 'aborted' }]);
    const r1 = await runPlanExecLoop(config(), first);
    expect(r1.finalStatus).toBe('timeout');

    const second = new FakeRuntime([exec(PLAN_AB_DONE)]);
    const r2 = await runPlanExecLoop(config(), second);
    expect(r2.finalStatus).toBe('completed');
    expect(r2.planIterCount).toBe(1);
    expect(r2.execIterCount).toBe(2);
    expect(second.requests).toHaveLength(1);
    expect(second.requests[0]?.prompt).toContain('selected_task_id: b');
    expect(await listIters()).toEqual(['exec-0001', 'exec-0002', 'exec-0002.aborted-1', 'plan']);
    const history = (
      (await readJson('run.json')).configSnapshot as { resumeHistory: { finalStatus: string }[] }
    ).resumeHistory;
    expect(history.map((h) => h.finalStatus)).toEqual(['timeout', 'completed']);
  });

  it('quarantines a partial executor dir left behind by a crash', async () => {
    await runPlanExecLoop(config({ maxIters: 1 }), new FakeRuntime([planner(), exec(PLAN_A_DONE)]));
    const partial = path.join(root, 'run', 'iters', 'exec-0002');
    await fs.mkdir(partial);
    await fs.writeFile(path.join(partial, 'plan.before.md'), PLAN_A_DONE);
    await fs.writeFile(path.join(root, 'run', 'run.json'), 'not json');

    const result = await runPlanExecLoop(config(), new FakeRuntime([exec(PLAN_AB_DONE)]), {
      force: true,
    });
    expect(result.finalStatus).toBe('completed');
    expect(await listIters()).toEqual(['exec-0001', 'exec-0002', 'exec-0002.aborted-1', 'plan']);
    expect(await read('iters/exec-0002.aborted-1/aborted.txt')).toMatch(
      /^resume_at: .*\nprior_final_status: budget_exhausted\n$/,
    );
  });

  it('uses a unique counter when quarantining the same id twice', async () => {
    const r1 = await runPlanExecLoop(
      config(),
      new FakeRuntime([planner(PLAN_ONE), { status: 'aborted' }]),
    );
    expect(r1.finalStatus).toBe('timeout');
    const r2 = await runPlanExecLoop(config(), new FakeRuntime([{ status: 'aborted' }]));
    expect(r2.finalStatus).toBe('timeout');
    expect(await listIters()).toEqual(['exec-0001.aborted-1', 'exec-0001.aborted-2', 'plan']);
  });

  it('is a no-op after a completed run', async () => {
    await runPlanExecLoop(config(), new FakeRuntime([planner(PLAN_ONE), exec(PLAN_ONE_DONE)]));
    const again = new FakeRuntime();
    const result = await runPlanExecLoop(config(), again);
    expect(result.finalStatus).toBe('completed');
    expect(again.requests).toHaveLength(0);
  });

  it('refuses after protocol_violation or runtime_error unless forced', async () => {
    await runPlanExecLoop(config(), new ThrowingRuntime());
    await expect(runPlanExecLoop(config(), new FakeRuntime())).rejects.toThrow(ResumeRefusedError);
    const forced = await runPlanExecLoop(
      config(),
      new FakeRuntime([planner(PLAN_ONE), exec(PLAN_ONE_DONE)]),
      { force: true },
    );
    expect(forced.finalStatus).toBe('completed');
    expect(await listIters()).toEqual(['exec-0001', 'plan', 'plan.aborted-1']);
  });

  it('continues after budget_exhausted with a fresh budget', async () => {
    const r1 = await runPlanExecLoop(
      config({ maxIters: 1 }),
      new FakeRuntime([planner(), exec(PLAN_A_DONE)]),
    );
    expect(r1.finalStatus).toBe('budget_exhausted');
    const r2 = await runPlanExecLoop(
      config({ maxIters: 1 }),
      new FakeRuntime([exec(PLAN_AB_DONE)]),
    );
    expect(r2.finalStatus).toBe('completed');
    expect(r2.execIterCount).toBe(2);
  });

  it('rejects a resume with drifted prompts', async () => {
    await runPlanExecLoop(config({ maxIters: 1 }), new FakeRuntime([planner(), exec(PLAN_A_DONE)]));
    await expect(
      runPlanExecLoop(
        config({ prompts: { planner: 'OTHER', execute: 'EXEC' } }),
        new FakeRuntime(),
      ),
    ).rejects.toThrow(ResumeMismatchError);
  });
});
