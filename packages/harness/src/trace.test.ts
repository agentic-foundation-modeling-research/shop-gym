import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { FakeRuntime } from '@shop-gym/agent/testing';
import { describe, expect, it } from 'vitest';

import { runPlanExecLoop } from './loop.js';
import { renderIterDir, renderTrajectory } from './trace.js';

describe('trace', () => {
  it('renders a trajectory and an iteration dir', async () => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'trace-'));
    const runtime = new FakeRuntime([
      { writeFiles: { 'plan.md': '## Tasks\n- [ ] a\n' }, reply: 'planned' },
      { writeFiles: { 'plan.md': '## Tasks\n- [x] a\n' }, reply: 'done' },
    ]);
    await runPlanExecLoop(
      {
        runDir: path.join(root, 'run'),
        prompts: { planner: 'PLAN', execute: 'EXEC' },
        agentsMd: 'A',
        maxIters: 2,
        timeoutMs: 1000,
        model: { provider: 'fake', id: 'scripted' },
        tools: [],
      },
      runtime,
    );
    const text = await renderIterDir(path.join(root, 'run', 'iters', 'exec-0001'));
    expect(text).toContain('iter: exec-0001 (exec)');
    expect(text).toContain('task: a  completed=[a]');
    expect(text).toContain('runtime: fake  model: fake/scripted');
    expect(text).toContain('assistant> done');

    const short = renderTrajectory(
      {
        runtime: 'x',
        model: { provider: 'p', id: 'm' },
        startedAt: '2026-01-01T00:00:00.000Z',
        endedAt: '2026-01-01T00:00:01.000Z',
        promptSha256: 'abc',
        usage: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
        steps: [
          {
            kind: 'tool_call',
            callId: 'c1',
            tool: 'echo',
            arguments: { text: 'x'.repeat(50) },
            timestamp: '2026-01-01T00:00:00.500Z',
          },
        ],
      },
      { maxChars: 10 },
    );
    expect(short).toContain('[    0.5s] call echo {"text":"x... [');
  });
});
