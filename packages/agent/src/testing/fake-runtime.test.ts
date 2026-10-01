import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeAll, describe, expect, it } from 'vitest';

import { type ConformanceScenario, conformanceCases } from './conformance.js';
import { FakeRuntime, type FakeScript } from './fake-runtime.js';

const MODEL = { provider: 'fake', id: 'scripted' };

const SCRIPTS: Record<ConformanceScenario, FakeScript> = {
  reply: { reply: 'PONG' },
  tool: { toolCalls: [{ tool: 'echo', arguments: { text: 'ping' } }], reply: 'DONE' },
  abort: { reply: 'PONG' },
};

describe('FakeRuntime', () => {
  let cwd: string;
  beforeAll(async () => {
    cwd = await fs.mkdtemp(path.join(os.tmpdir(), 'fake-rt-'));
  });

  describe('conformance', () => {
    for (const conformanceCase of conformanceCases) {
      it(conformanceCase.name, () =>
        conformanceCase.run({ cwd, model: MODEL, runtime: (s) => new FakeRuntime([SCRIPTS[s]]) }));
    }
  });

  it('writes scripted files under cwd and records the request', async () => {
    const runtime = new FakeRuntime([
      { writeFiles: { 'plan.md': '- [ ] a\n', 'nested/x.txt': 'x' } },
    ]);
    const result = await runtime.run({
      cwd,
      systemPrompt: 's',
      prompt: 'p',
      tools: [],
      model: MODEL,
      signal: new AbortController().signal,
    });
    expect(result.status).toBe('completed');
    expect(await fs.readFile(path.join(cwd, 'plan.md'), 'utf-8')).toBe('- [ ] a\n');
    expect(await fs.readFile(path.join(cwd, 'nested/x.txt'), 'utf-8')).toBe('x');
    expect(runtime.requests).toHaveLength(1);
  });

  it('reports error when the script calls a tool the request lacks', async () => {
    const runtime = new FakeRuntime([{ toolCalls: [{ tool: 'missing', arguments: {} }] }]);
    const result = await runtime.run({
      cwd,
      systemPrompt: 's',
      prompt: 'p',
      tools: [],
      model: MODEL,
      signal: new AbortController().signal,
    });
    expect(result.status).toBe('error');
    expect(result.error).toMatch(/unknown tool/);
    expect(result.trajectory.steps.at(-2)).toMatchObject({ kind: 'tool_result', isError: true });
  });
});
