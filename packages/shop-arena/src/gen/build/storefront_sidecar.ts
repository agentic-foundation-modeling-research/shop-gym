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
 *
 * The sidecar hashes the copy (ignoring `node_modules`, `build` and other
 * generated trees) and builds at most once per digest: `build()` runs the
 * build step alone (the `build` verifier), and `ensureCurrent()` builds
 * when needed, then serves that build. A build replaces the files the
 * server reads, so the server stops first. A failed build is kept for its
 * digest and returned again, without a new build, until the copy changes.
 * Operations are serialised, so concurrent callers never race a restart.
 */

import { type ChildProcess, spawn } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import { SidecarError, type SidecarProcess } from './sidecar.js';
import { hashSnapshot, snapshotTree } from './tree.js';
import {
  type CommandResult,
  type CommandRunner,
  commandEnv,
  runCommand,
} from './verifiers/subprocess.js';

export interface StorefrontLaunchOptions {
  readonly storefrontDir: string;
  readonly backendUrl: string;
  readonly port: number;
  readonly url: string;
  readonly logPath: string;
  readonly healthTimeoutMs: number;
}

/** Starts the built storefront; resolves once `/health` answers. */
export type StorefrontLaunch = (options: StorefrontLaunchOptions) => Promise<SidecarProcess>;

export const STOREFRONT_BUILD_ARGV: readonly string[] = ['pnpm', 'build'];
export const STOREFRONT_BUILD_TIMEOUT_MS = 300_000;

/** The copy did not build; `result` holds the build output. */
export class StorefrontBuildError extends SidecarError {
  constructor(
    readonly result: CommandResult,
    logPath: string,
  ) {
    super(
      `storefront build failed (${result.timedOut ? 'timed out' : `exit ${result.exitCode}`}); see ${logPath}\n${tail(result.stderr || result.stdout)}`,
    );
    this.name = 'StorefrontBuildError';
  }
}

export interface StorefrontSidecarOptions {
  readonly storefrontDir: string;
  readonly backendUrl: string;
  readonly port: number;
  readonly logPath: string;
  readonly healthTimeoutMs?: number;
  /** Runs `pnpm build`; defaults to `runCommand`. */
  readonly runner?: CommandRunner;
  /** Process seam; defaults to `node server.mjs` in production mode. */
  readonly launch?: StorefrontLaunch;
}

const DEFAULT_HEALTH_TIMEOUT_MS = 30_000;
const HEALTH_POLL_MS = 100;
const STOP_GRACE_MS = 3_000;

export class StorefrontSidecar {
  readonly url: string;
  private readonly runner: CommandRunner;
  private readonly launch: StorefrontLaunch;
  private readonly healthTimeoutMs: number;
  private process: SidecarProcess | undefined;
  /** Digest of the copy the running process was built from. */
  private servedHash: string | undefined;
  private lastBuild: { readonly hash: string; readonly result: CommandResult } | undefined;
  private queue: Promise<unknown> = Promise.resolve();

  constructor(private readonly options: StorefrontSidecarOptions) {
    this.url = `http://127.0.0.1:${options.port}`;
    this.runner = options.runner ?? runCommand;
    this.launch = options.launch ?? spawnStorefront;
    this.healthTimeoutMs = options.healthTimeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
  }

  get running(): boolean {
    return this.process !== undefined;
  }

  /** Build when needed and start; a no-op when already running. */
  start(): Promise<void> {
    return this.serialise(async () => {
      if (this.process === undefined) {
        await this.serve(await this.currentHash());
      }
    });
  }

  /** Stop the process; a no-op when not running. */
  stop(): Promise<void> {
    return this.serialise(() => this.stopProcess());
  }

  /** Rebuild and restart when the copy changed since the last start. */
  restartIfChanged(): Promise<boolean> {
    return this.serialise(async () => {
      if (this.process === undefined) {
        return false;
      }
      const hash = await this.currentHash();
      if (hash === this.servedHash) {
        return false;
      }
      await this.serve(hash);
      return true;
    });
  }

  /**
   * Build the copy unless the last build was of the same digest, and
   * resolve to that build's result. Does not start the server.
   */
  build(): Promise<CommandResult> {
    return this.serialise(async () => this.buildOnce(await this.currentHash()));
  }

  /**
   * Bring the served tree up to date: build when the copy changed, then
   * start or restart on that build. The build-loop verifiers call this
   * before their first request so the storefront is only built once a
   * task needs it.
   *
   * @throws StorefrontBuildError when the copy does not build.
   */
  ensureCurrent(): Promise<void> {
    return this.serialise(async () => {
      const hash = await this.currentHash();
      if (this.process === undefined || hash !== this.servedHash) {
        await this.serve(hash);
      }
    });
  }

  /** Caller holds the queue. Build `hash` when needed, then (re)start on it. */
  private async serve(hash: string): Promise<void> {
    const build = await this.buildOnce(hash);
    if (build.exitCode !== 0 || build.timedOut) {
      throw new StorefrontBuildError(build, this.options.logPath);
    }
    await this.stopProcess();
    this.process = await this.launch({
      storefrontDir: this.options.storefrontDir,
      backendUrl: this.options.backendUrl,
      port: this.options.port,
      url: this.url,
      logPath: this.options.logPath,
      healthTimeoutMs: this.healthTimeoutMs,
    });
    this.servedHash = hash;
  }

  /** Caller holds the queue. */
  private async buildOnce(hash: string): Promise<CommandResult> {
    if (this.lastBuild?.hash === hash) {
      return this.lastBuild.result;
    }
    await this.stopProcess();
    const result = await this.runner(STOREFRONT_BUILD_ARGV, {
      cwd: this.options.storefrontDir,
      timeoutMs: STOREFRONT_BUILD_TIMEOUT_MS,
    });
    await fs.mkdir(path.dirname(this.options.logPath), { recursive: true });
    await fs.appendFile(
      this.options.logPath,
      `[build] ${result.timedOut ? 'timed out' : `exit ${result.exitCode}`}\n${result.stdout}${result.stderr}\n`,
    );
    this.lastBuild = { hash, result };
    return result;
  }

  /** Caller holds the queue. */
  private async stopProcess(): Promise<void> {
    const current = this.process;
    this.process = undefined;
    await current?.stop();
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

/** Default launch: `node server.mjs` in production mode, logging to `logPath`. */
export const spawnStorefront: StorefrontLaunch = async (options) => {
  await fs.mkdir(path.dirname(options.logPath), { recursive: true });
  const log = await fs.open(options.logPath, 'a');
  const child = spawn(process.execPath, ['server.mjs'], {
    cwd: options.storefrontDir,
    stdio: ['ignore', log.fd, log.fd],
    env: commandEnv({
      NODE_ENV: 'production',
      PORT: String(options.port),
      PUBLIC_STORE_DOMAIN: options.backendUrl,
      SHOP_BACKEND_URL: options.backendUrl,
    }),
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
};

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
