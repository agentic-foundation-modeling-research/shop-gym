/**
 * The backend sidecar: the seeded `artifact/backend` copy served as a child
 * process against `artifact/data`, so the agent and the verifiers talk to
 * the same GraphQL endpoint the finished shop will expose.
 *
 * The copy is launched with `node --import tsx src/cli.ts <dataDir> <port>`,
 * the same entry its `shop-backend` script uses, so agent edits take effect
 * on restart without a build step. Between `start()` and `stop()`,
 * `ensureCurrent()` re-hashes the copy's `src/` and `package.json` and
 * restarts only when the digest moved, or launches again when an earlier
 * launch failed, so a fixed edit brings the sidecar back. Operations are
 * serialised, so concurrent callers never race a restart.
 */

import { type ChildProcess, spawn } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as net from 'node:net';
import * as path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import { hashSnapshot, snapshotTree } from './tree.js';
import { commandEnv } from './verifiers/subprocess.js';

export class SidecarError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SidecarError';
  }
}

export interface SidecarLaunchOptions {
  readonly backendDir: string;
  readonly dataDir: string;
  readonly port: number;
  readonly url: string;
  readonly logPath: string;
  readonly healthTimeoutMs: number;
}

/** A running sidecar process; `stop()` must resolve once it has exited. */
export interface SidecarProcess {
  stop(): Promise<void>;
}

/** Starts a process and resolves once `/health` answers. */
export type SidecarLaunch = (options: SidecarLaunchOptions) => Promise<SidecarProcess>;

export interface BackendSidecarOptions {
  readonly backendDir: string;
  readonly dataDir: string;
  readonly port: number;
  readonly logPath: string;
  readonly healthTimeoutMs?: number;
  /** Process seam; defaults to spawning the copy's CLI. */
  readonly launch?: SidecarLaunch;
}

const DEFAULT_HEALTH_TIMEOUT_MS = 15_000;
const HEALTH_POLL_MS = 100;
const STOP_GRACE_MS = 3_000;

export class BackendSidecar {
  readonly url: string;
  private readonly launch: SidecarLaunch;
  private readonly healthTimeoutMs: number;
  private process: SidecarProcess | undefined;
  private sourceHash: string | undefined;
  /** Between `start()` and `stop()`; `process` is unset while active only after a failed launch. */
  private active = false;
  private queue: Promise<unknown> = Promise.resolve();

  constructor(private readonly options: BackendSidecarOptions) {
    this.url = `http://127.0.0.1:${options.port}`;
    this.launch = options.launch ?? spawnSidecar;
    this.healthTimeoutMs = options.healthTimeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
  }

  get running(): boolean {
    return this.process !== undefined;
  }

  /** Start the process; a no-op when already running. */
  start(): Promise<void> {
    return this.serialise(async () => {
      this.active = true;
      if (this.process !== undefined) {
        return;
      }
      this.sourceHash = await this.currentHash();
      this.process = await this.launchProcess();
    });
  }

  /** Stop the process; a no-op when not running. Later `ensureCurrent()` calls do nothing. */
  stop(): Promise<void> {
    return this.serialise(async () => {
      this.active = false;
      const current = this.process;
      this.process = undefined;
      await current?.stop();
    });
  }

  /**
   * Restart when `src/` or `package.json` changed since the last launch, or
   * launch again when the last launch failed. A no-op outside `start()` /
   * `stop()`.
   *
   * @returns Whether a launch happened.
   * @throws SidecarError when the launch fails; the next call tries again.
   */
  ensureCurrent(): Promise<boolean> {
    return this.serialise(async () => {
      if (!this.active) {
        return false;
      }
      const hash = await this.currentHash();
      if (this.process !== undefined) {
        if (hash === this.sourceHash) {
          return false;
        }
        const current = this.process;
        this.process = undefined;
        await current.stop();
      }
      this.sourceHash = hash;
      this.process = await this.launchProcess();
      return true;
    });
  }

  private launchProcess(): Promise<SidecarProcess> {
    return this.launch({
      backendDir: this.options.backendDir,
      dataDir: this.options.dataDir,
      port: this.options.port,
      url: this.url,
      logPath: this.options.logPath,
      healthTimeoutMs: this.healthTimeoutMs,
    });
  }

  private async currentHash(): Promise<string> {
    const src = await snapshotTree(path.join(this.options.backendDir, 'src'));
    const pkg = await snapshotTree(this.options.backendDir, [
      'src',
      'tests',
      'node_modules',
      'dist',
      'scripts',
    ]);
    return hashSnapshot({ ...prefix(src, 'src/'), 'package.json': pkg['package.json'] ?? '' });
  }

  private serialise<T>(op: () => Promise<T>): Promise<T> {
    const next = this.queue.then(op, op);
    this.queue = next.catch(() => undefined);
    return next;
  }
}

function prefix(snapshot: Readonly<Record<string, string>>, head: string): Record<string, string> {
  return Object.fromEntries(Object.entries(snapshot).map(([rel, digest]) => [head + rel, digest]));
}

/** An unused TCP port on the loopback interface. */
export async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => {
        if (address === null || typeof address === 'string') {
          reject(new SidecarError('could not allocate a port'));
          return;
        }
        resolve(address.port);
      });
    });
  });
}

/** Default launch: spawn the copy's CLI, append its output to `logPath`, poll `/health`. */
export const spawnSidecar: SidecarLaunch = async (options) => {
  await fs.mkdir(path.dirname(options.logPath), { recursive: true });
  const log = await fs.open(options.logPath, 'a');
  const child = spawn(
    process.execPath,
    ['--import', 'tsx', 'src/cli.ts', options.dataDir, String(options.port)],
    { cwd: options.backendDir, stdio: ['ignore', log.fd, log.fd], env: commandEnv() },
  );
  const exited = new Promise<number | null>((resolve) => {
    child.once('exit', (code) => resolve(code));
  });
  const stopper = { stop: () => stopProcess(child, exited, log) };
  try {
    await waitForHealth(options.url, options.healthTimeoutMs, exited, options.logPath);
  } catch (error) {
    await stopper.stop();
    throw error;
  }
  return stopper;
};

async function waitForHealth(
  url: string,
  timeoutMs: number,
  exited: Promise<number | null>,
  logPath: string,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let done = false;
  const exit = exited.then((code) => {
    done = true;
    return code;
  });
  while (Date.now() < deadline) {
    if (done) {
      throw new SidecarError(
        `sidecar exited with code ${await exit} before /health; see ${logPath}`,
      );
    }
    const healthy = await fetch(`${url}/health`)
      .then((response) => response.ok)
      .catch(() => false);
    if (healthy) {
      return;
    }
    await sleep(HEALTH_POLL_MS);
  }
  throw new SidecarError(`sidecar did not answer /health within ${timeoutMs}ms; see ${logPath}`);
}

async function stopProcess(
  child: ChildProcess,
  exited: Promise<number | null>,
  log: fs.FileHandle,
): Promise<void> {
  try {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill('SIGTERM');
      const grace = sleep(STOP_GRACE_MS).then(() => 'timeout' as const);
      if ((await Promise.race([exited, grace])) === 'timeout') {
        child.kill('SIGKILL');
        await exited;
      }
    }
  } finally {
    await log.close();
  }
}
