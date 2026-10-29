import * as os from 'node:os';
import { setTimeout as sleep } from 'node:timers/promises';

import { describe, expect, it } from 'vitest';

import { runCommand } from './subprocess.js';

const OPTIONS = { cwd: os.tmpdir(), timeoutMs: 10_000 };

/** True while `pid` runs; an orphan can take a moment to be reaped after SIGKILL. */
async function alive(pid: number): Promise<boolean> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      process.kill(pid, 0);
    } catch {
      return false;
    }
    await sleep(50);
  }
  return true;
}

describe('runCommand', () => {
  it('returns the exit code and both streams', async () => {
    const result = await runCommand(['/bin/sh', '-c', 'echo out; echo err >&2; exit 3'], OPTIONS);

    expect(result).toEqual({ exitCode: 3, stdout: 'out\n', stderr: 'err\n', timedOut: false });
  });

  it('kills every process the command started when it times out', async () => {
    const result = await runCommand(['/bin/sh', '-c', 'sleep 30 & echo $!; wait'], {
      ...OPTIONS,
      timeoutMs: 500,
    });

    expect(result).toMatchObject({ exitCode: null, timedOut: true });
    expect(await alive(Number(result.stdout.trim()))).toBe(false);
  });

  it('kills a background process the command left behind when it exits', async () => {
    const started = Date.now();
    const result = await runCommand(['/bin/sh', '-c', 'sleep 30 & echo $!'], OPTIONS);

    expect(result).toMatchObject({ exitCode: 0, timedOut: false });
    expect(Date.now() - started).toBeLessThan(OPTIONS.timeoutMs);
    expect(await alive(Number(result.stdout.trim()))).toBe(false);
  });

  it('reports a program that cannot start without an exit code', async () => {
    const result = await runCommand(['/no/such/program'], OPTIONS);

    expect(result).toMatchObject({ exitCode: null, timedOut: false });
    expect(result.stderr).toContain('ENOENT');
  });

  it('kills a command whose output passes the buffer limit', async () => {
    const result = await runCommand(
      ['/bin/sh', '-c', 'head -c 17000000 /dev/zero; sleep 30'],
      OPTIONS,
    );

    expect(result).toMatchObject({ exitCode: null, timedOut: false });
    expect(result.stderr).toContain('stdout exceeded');
  });
});
