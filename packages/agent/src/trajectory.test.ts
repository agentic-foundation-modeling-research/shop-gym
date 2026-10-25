import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  TrajectoryRecorder,
  type TrajectoryStep,
  readTrajectory,
  sha256,
  trajectorySchema,
  writeTrajectory,
} from './trajectory.js';

const MODEL = { provider: 'openai', id: 'gpt-5.5' };
const USAGE = { input: 3, output: 2, cacheRead: 1, cacheWrite: 0, costUsd: 0.5 };

describe('TrajectoryRecorder', () => {
  it('stamps steps and notifies the listener in order', () => {
    const seen: TrajectoryStep[] = [];
    const recorder = new TrajectoryRecorder('fake', MODEL, sha256('p'), (s) => seen.push(s));
    recorder.record({ kind: 'message', role: 'user', text: 'p' });
    recorder.record({ kind: 'thought', text: 'hmm' });
    const trajectory = recorder.finish();
    expect(seen.map((s) => s.kind)).toEqual(['message', 'thought']);
    expect(trajectory.steps).toEqual(seen);
    expect(() => trajectorySchema.parse(trajectory)).not.toThrow();
  });

  it('sums usage over assistant messages', () => {
    const recorder = new TrajectoryRecorder('fake', MODEL, sha256('p'));
    recorder.record({ kind: 'message', role: 'assistant', text: 'a', usage: USAGE });
    recorder.record({ kind: 'message', role: 'assistant', text: 'b', usage: USAGE });
    recorder.record({ kind: 'message', role: 'user', text: 'no usage' });
    expect(recorder.finish().usage).toEqual({
      input: 6,
      output: 4,
      cacheRead: 2,
      cacheWrite: 0,
      costUsd: 1,
    });
  });
});

describe('trajectorySchema', () => {
  it('rejects an unknown step kind', () => {
    const recorder = new TrajectoryRecorder('fake', MODEL, sha256('p'));
    const bad = {
      ...recorder.finish(),
      steps: [{ kind: 'dance', timestamp: new Date().toISOString() }],
    };
    expect(trajectorySchema.safeParse(bad).success).toBe(false);
  });

  it('rejects a prompt hash that is not hex sha256', () => {
    const bad = { ...new TrajectoryRecorder('fake', MODEL, 'abc').finish() };
    expect(trajectorySchema.safeParse(bad).success).toBe(false);
  });
});

describe('writeTrajectory / readTrajectory', () => {
  it('round-trips through disk, creating parent dirs', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'traj-'));
    const file = path.join(dir, 'iters', '001', 'trajectory.json');
    const recorder = new TrajectoryRecorder('fake', MODEL, sha256('p'));
    recorder.record({ kind: 'tool_call', callId: 'c1', tool: 'echo', arguments: { text: 'x' } });
    const written = recorder.finish();
    await writeTrajectory(file, written);
    expect(await readTrajectory(file)).toEqual(written);
  });
});
