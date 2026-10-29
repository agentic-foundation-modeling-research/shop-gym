/**
 * Process primitives for the host: detached spawning with log files,
 * liveness, process-group termination, `/health` polling, port probing,
 * and a foreground command runner for `pnpm install` / `pnpm build`.
 */

import { spawn } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as net from 'node:net';
import * as path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import { build } from '@shop-gym/shop-arena';

import { CliError } from '../context.js';

export interface SpawnSpec {
  readonly command: string;
  readonly args: readonly string[];
  readonly cwd: string;
  readonly env: NodeJS.ProcessEnv;
  /** Truncated, then receives stdout and stderr. */
  readonly logPath: string;
}

/** Starts a detached process and resolves with its pid once it has spawned. */
export type SpawnDetached = (spec: SpawnSpec) => Promise<number>;

export const spawnDetached: SpawnDetached = async (spec) => {
  await fs.mkdir(path.dirname(spec.logPath), { recursive: true });
  const log = await fs.open(spec.logPath, 'w');
  try {
    const child = spawn(spec.command, [...spec.args], {
      cwd: spec.cwd,
      env: spec.env,
      detached: true,
      stdio: ['ignore', log.fd, log.fd],
    });
    const pid = await new Promise<number>((resolve, reject) => {
      child.once('spawn', () => {
        if (child.pid === undefined) {
          reject(new Error('spawn returned no pid'));
        } else {
          resolve(child.pid);
        }
      });
      child.once('error', reject);
    });
    child.unref();
    return pid;
  } finally {
    await log.close();
  }
};

export function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'EPERM';
  }
}

const KILL_GRACE_MS = 3_000;
const KILL_POLL_MS = 50;

/** SIGTERM the process group (falling back to the pid), then SIGKILL after a grace period. */
export async function killTree(pid: number, graceMs = KILL_GRACE_MS): Promise<void> {
  if (!pidAlive(pid)) {
    return;
  }
  signal(pid, 'SIGTERM');
  if (await waitForExit(pid, graceMs)) {
    return;
  }
  signal(pid, 'SIGKILL');
  await waitForExit(pid, graceMs);
}

function signal(pid: number, sig: NodeJS.Signals): void {
  try {
    process.kill(-pid, sig);
  } catch {
    try {
      process.kill(pid, sig);
    } catch {
      // Already gone.
    }
  }
}

async function waitForExit(pid: number, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!pidAlive(pid)) {
      return true;
    }
    await sleep(KILL_POLL_MS);
  }
  return !pidAlive(pid);
}

const HEALTH_POLL_MS = 200;

/**
 * Poll `<url>/health` until it answers 2xx.
 *
 * @throws CliError when `pid` exits first or `timeoutMs` elapses.
 */
export async function waitForHealth(
  url: string,
  pid: number,
  timeoutMs: number,
  logPath: string,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const healthy = await fetch(`${url}/health`, { signal: AbortSignal.timeout(2_000) })
      .then((response) => response.ok)
      .catch(() => false);
    if (healthy) {
      return;
    }
    if (!pidAlive(pid)) {
      throw new CliError(`${url} exited before answering /health; see ${logPath}`);
    }
    await sleep(HEALTH_POLL_MS);
  }
  throw new CliError(`${url} did not answer /health within ${timeoutMs}ms; see ${logPath}`);
}

/** `true` when nothing is listening on `port`. */
export function portFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)));
  });
}

export interface CommandResult {
  readonly exitCode: number | null;
  /** stdout followed by stderr. */
  readonly output: string;
}

/** Runs a command to completion; never throws on a non-zero exit. */
export type CommandRunner = (argv: readonly string[], cwd: string) => Promise<CommandResult>;

const COMMAND_TIMEOUT_MS = 15 * 60_000;

/** The build loop's runner: nothing the command starts outlives its exit or timeout. */
export const runCommand: CommandRunner = async (argv, cwd) => {
  const result = await build.runCommand(argv, { cwd, timeoutMs: COMMAND_TIMEOUT_MS });
  return { exitCode: result.exitCode, output: `${result.stdout}${result.stderr}` };
};
