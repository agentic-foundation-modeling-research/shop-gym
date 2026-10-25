/**
 * The storefront sidecar: the seeded `artifact/storefront` copy served as a
 * child process against the backend sidecar, so the HTTP verifiers and the
 * visual judge see the pages a shopper would.
 *
 * The copy is served in production mode (`pnpm build`, then
 * `node server.mjs` with `NODE_ENV=production`) rather than through the
 * Vite dev middleware: the built output is what `host` will serve, it has
 * no HMR or lazy-compile latency to confuse screenshots, and a build error
 * surfaces as a start failure instead of a half-rendered page.
 * `restartIfChanged()` re-hashes the copy (ignoring `node_modules`,
 * `build` and other generated trees) and rebuilds and restarts only when
 * the digest moved. Operations are serialised, so concurrent callers never
 * race a restart.
 */

import { type ChildProcess, spawn } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import { SidecarError, type SidecarProcess } from './sidecar.js';
import { hashSnapshot, snapshotTree } from './tree.js';
import { type CommandRunner, runCommand } from './verifiers/subprocess.js';

export interface StorefrontLaunchOptions {
  readonly storefrontDir: string;
  readonly backendUrl: string;
  readonly port: number;
  readonly url: string;
  readonly logPath: string;
  readonly healthTimeoutMs: number;
}

/** Builds and starts the storefront; resolves once `/health` answers. */
export type StorefrontLaunch = (options: StorefrontLaunchOptions) => Promise<SidecarProcess>;

export interface StorefrontSidecarOptions {
  readonly storefrontDir: string;
  readonly backendUrl: string;
  readonly port: number;
  readonly logPath: string;
  readonly healthTimeoutMs?: number;
  /** Process seam; defaults to `pnpm build` followed by `node server.mjs`. */
  readonly launch?: StorefrontLaunch;
}

const DEFAULT_HEALTH_TIMEOUT_MS = 30_000;
const BUILD_TIMEOUT_MS = 300_000;
const HEALTH_POLL_MS = 100;
const STOP_GRACE_MS = 3_000;

export class StorefrontSidecar {
  readonly url: string;
  private readonly launch: StorefrontLaunch;
  private readonly healthTimeoutMs: number;
  private process: SidecarProcess | undefined;
  private sourceHash: string | undefined;
  private queue: Promise<unknown> = Promise.resolve();

  constructor(private readonly options: StorefrontSidecarOptions) {
    this.url = `http://127.0.0.1:${options.port}`;
    this.launch = options.launch ?? spawnStorefront;
    this.healthTimeoutMs = options.healthTimeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
  }

  get running(): boolean {
    return this.process !== undefined;
  }

  /** Build and start the process; a no-op when already running. */
  start(): Promise<void> {
    return this.serialise(async () => {
      if (this.process !== undefined) {
        return;
      }
      this.sourceHash = await this.currentHash();
      this.process = await this.launchProcess();
    });
  }

  /** Stop the process; a no-op when not running. */
  stop(): Promise<void> {
    return this.serialise(async () => {
      const current = this.process;
      this.process = undefined;
      await current?.stop();
    });
  }

  /** Rebuild and restart when the copy changed since the last start. */
  restartIfChanged(): Promise<boolean> {
    return this.serialise(async () => {
      if (this.process === undefined) {
        return false;
      }
      return this.relaunchIfChanged();
    });
  }

  /**
   * Bring the served tree up to date: start when stopped, otherwise
   * rebuild and restart when the copy changed. The build-loop verifiers
   * call this before their first request so the storefront is only built
   * once a task needs it.
   */
  ensureCurrent(): Promise<void> {
    return this.serialise(async () => {
      if (this.process === undefined) {
        this.sourceHash = await this.currentHash();
        this.process = await this.launchProcess();
        return;
      }
      await this.relaunchIfChanged();
    });
  }

  /** Caller holds the queue and `this.process` is set. */
  private async relaunchIfChanged(): Promise<boolean> {
    const hash = await this.currentHash();
    if (hash === this.sourceHash) {
      return false;
    }
    const current = this.process;
    this.process = undefined;
    await current?.stop();
    this.sourceHash = hash;
    this.process = await this.launchProcess();
    return true;
  }

  private launchProcess(): Promise<SidecarProcess> {
    return this.launch({
      storefrontDir: this.options.storefrontDir,
      backendUrl: this.options.backendUrl,
      port: this.options.port,
      url: this.url,
      logPath: this.options.logPath,
      healthTimeoutMs: this.healthTimeoutMs,
    });
  }

  private async currentHash(): Promise<string> {
    return hashSnapshot(await snapshotTree(this.options.storefrontDir));
  }

  private serialise<T>(op: () => Promise<T>): Promise<T> {
    const next = this.queue.then(op, op);
    this.queue = next.catch(() => undefined);
    return next;
  }
}

/** Default launch: `pnpm build`, then `node server.mjs` in production mode, logging to `logPath`. */
export const spawnStorefront: StorefrontLaunch = (options) => launchWithRunner(runCommand, options);

/** `spawnStorefront` with an injectable build runner. */
export async function launchWithRunner(
  runner: CommandRunner,
  options: StorefrontLaunchOptions,
): Promise<SidecarProcess> {
  await fs.mkdir(path.dirname(options.logPath), { recursive: true });
  const build = await runner(['pnpm', 'build'], {
    cwd: options.storefrontDir,
    timeoutMs: BUILD_TIMEOUT_MS,
  });
  await fs.appendFile(
    options.logPath,
    `[build] exit ${build.exitCode}\n${build.stdout}${build.stderr}\n`,
  );
  if (build.exitCode !== 0) {
    throw new SidecarError(
      `storefront build failed (exit ${build.exitCode}); see ${options.logPath}\n${tail(build.stderr || build.stdout)}`,
    );
  }
  const log = await fs.open(options.logPath, 'a');
  const child = spawn(process.execPath, ['server.mjs'], {
    cwd: options.storefrontDir,
    stdio: ['ignore', log.fd, log.fd],
    env: {
      ...process.env,
      NODE_ENV: 'production',
      PORT: String(options.port),
      PUBLIC_STORE_DOMAIN: options.backendUrl,
      SHOP_BACKEND_URL: options.backendUrl,
    },
  });
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
}

const TAIL_CHARS = 1500;

function tail(text: string): string {
  return text.length <= TAIL_CHARS ? text : text.slice(-TAIL_CHARS);
}

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
        `storefront exited with code ${await exit} before /health; see ${logPath}`,
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
  throw new SidecarError(`storefront did not answer /health within ${timeoutMs}ms; see ${logPath}`);
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
