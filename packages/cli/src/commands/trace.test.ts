import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { parseTraceArgs, run } from './trace.js';

const TRAJECTORY = {
  runtime: 'fake',
  model: { provider: 'p', id: 'm' },
  startedAt: '2026-01-01T00:00:00.000Z',
  endedAt: '2026-01-01T00:00:02.000Z',
  promptSha256: 'a'.repeat(64),
  usage: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
  steps: [
    {
      kind: 'message',
      role: 'assistant',
      text: 'x'.repeat(3000),
      timestamp: '2026-01-01T00:00:01.000Z',
    },
  ],
};

const METADATA = {
  iterId: 'exec-0001',
  iterKind: 'exec',
  runtime: 'fake',
  selectedTaskId: 'a',
  completedTaskIds: ['a'],
  blockedTaskIds: [],
  addedTaskIds: [],
  startedAt: '2026-01-01T00:00:00.000Z',
  endedAt: '2026-01-01T00:00:02.000Z',
};

describe('parseTraceArgs', () => {
  it('parses the iter dir and --full', () => {
    expect(parseTraceArgs(['d', '--full'])).toEqual({ help: false, iterDir: 'd', full: true });
  });

  it('requires exactly one iter dir', () => {
    expect(() => parseTraceArgs([])).toThrow('missing <iter_dir>');
    expect(() => parseTraceArgs(['a', 'b'])).toThrow('unexpected argument "b"');
  });
});

describe('trace run', () => {
  afterEach(() => vi.restoreAllMocks());

  it('renders a fixture iteration, truncating unless --full', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'trace-cli-'));
    await fs.writeFile(path.join(dir, 'trajectory.json'), JSON.stringify(TRAJECTORY));
    await fs.writeFile(path.join(dir, 'metadata.json'), JSON.stringify(METADATA));
    let out = '';
    vi.spyOn(process.stdout, 'write').mockImplementation((chunk) => {
      out += String(chunk);
      return true;
    });

    expect(await run([dir])).toBe(0);
    expect(out).toContain('iter: exec-0001 (exec)');
    expect(out).toContain('runtime: fake  model: p/m');
    expect(out).toContain('[1000 more chars]');

    out = '';
    expect(await run([dir, '--full'])).toBe(0);
    expect(out).not.toContain('more chars');
    expect(out).toContain('x'.repeat(3000));
  });
});
