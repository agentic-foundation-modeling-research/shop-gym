/**
 * Hosting a published shop: its own `backend/` served on `<shopDir>/data`
 * plus the storefront, both detached with pid, port and log bookkeeping
 * under `<repoRoot>/.run/shops/<name>/`.
 */

import { randomBytes } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { build, publish } from '@shop-gym/shop-arena';

type ShopManifest = publish.ShopManifest;

import { CliError } from '../context.js';
import {
  type CommandRunner,
  type SpawnDetached,
  killTree,
  pidAlive,
  portFree,
  runCommand,
  spawnDetached,
  waitForHealth,
} from './process.js';
import {
  type HostState,
  type ProcessState,
  listStates,
  readBuildRecord,
  readState,
  removeState,
  shopRunDir,
  writeBuildRecord,
  writeState,
} from './state.js';

export interface HostDeps {
  readonly runner: CommandRunner;
  readonly spawn: SpawnDetached;
  readonly freePort: () => Promise<number>;
  readonly log: (line: string) => void;
}

export const defaultHostDeps: HostDeps = {
  runner: runCommand,
  spawn: spawnDetached,
  freePort: build.freePort,
  log: (line) => process.stderr.write(`${line}\n`),
};

export interface StartOptions {
  readonly repoRoot: string;
  /** Shop directory, or a name under `<repoRoot>/outputs/shops/`. */
  readonly shop: string;
  /** Storefront port; a free port when omitted. */
  readonly port?: number;
  /** Start even when `shop.json` records a final status other than `completed`. */
  readonly force: boolean;
}

const BACKEND_HEALTH_MS = 30_000;
const STOREFRONT_HEALTH_MS = 60_000;

const COMPONENTS = [
  { name: 'backend', output: path.join('dist', 'cli.js') },
  { name: 'storefront', output: path.join('dist', 'server', 'index.js') },
] as const;

/** `shop` as a directory if it is one, else `<repoRoot>/outputs/shops/<shop>`. */
export function resolveShopDir(repoRoot: string, shop: string): string {
  const asPath = path.resolve(shop);
  const looksLikePath = shop.includes(path.sep) || shop.startsWith('.');
  return looksLikePath ? asPath : path.join(repoRoot, 'outputs', 'shops', shop);
}

export async function startShop(options: StartOptions, deps: HostDeps): Promise<HostState> {
  const shopDir = resolveShopDir(options.repoRoot, options.shop);
  const manifest = await readManifest(shopDir);
  const name = path.basename(shopDir);
  const dataDir = path.join(shopDir, 'data');
  if (!(await exists(dataDir))) {
    throw new CliError(`${dataDir} is missing`);
  }
  if (manifest.finalStatus !== 'completed' && !options.force) {
    throw new CliError(
      `${name} finished with status ${manifest.finalStatus}; pass --force to host it anyway`,
    );
  }
  const runDir = shopRunDir(options.repoRoot, name);
  const existing = await readState(runDir);
  if (
    existing !== undefined &&
    (pidAlive(existing.backend.pid) || pidAlive(existing.storefront.pid))
  ) {
    throw new CliError(`${name} is already running at ${existing.storefront.url}; use restart`);
  }
  await ensureBuilt(shopDir, manifest, runDir, deps);

  if (options.port !== undefined && !(await portFree(options.port))) {
    throw new CliError(`port ${options.port} is already bound; pick another or omit it`);
  }
  const storefrontPort = options.port ?? (await deps.freePort());
  const backendPort = await deps.freePort();

  const backend = await launch(deps, {
    command: process.execPath,
    args: [path.join('dist', 'cli.js'), dataDir, String(backendPort)],
    cwd: path.join(shopDir, 'backend'),
    env: { ...process.env },
    logPath: path.join(runDir, 'backend.log'),
    port: backendPort,
    timeoutMs: BACKEND_HEALTH_MS,
  });
  deps.log(`[host] backend    ${backend.url}  (pid ${backend.pid})`);

  let storefront: ProcessState;
  try {
    storefront = await launch(deps, {
      command: process.execPath,
      args: ['server.mjs'],
      cwd: path.join(shopDir, 'storefront'),
      env: {
        ...process.env,
        NODE_ENV: 'production',
        PORT: String(storefrontPort),
        PUBLIC_STORE_DOMAIN: backend.url,
        SHOP_BACKEND_URL: backend.url,
        SESSION_SECRET: process.env.SESSION_SECRET ?? randomBytes(32).toString('hex'),
      },
      logPath: path.join(runDir, 'storefront.log'),
      port: storefrontPort,
      timeoutMs: STOREFRONT_HEALTH_MS,
    });
  } catch (error) {
    await killTree(backend.pid);
    throw error;
  }
  deps.log(`[host] storefront ${storefront.url}  (pid ${storefront.pid})`);

  const state: HostState = {
    name,
    shopDir,
    startedAt: new Date().toISOString(),
    backend,
    storefront,
  };
  await writeState(runDir, state);
  return state;
}

/** Stop a tracked shop; `false` when it was not tracked. */
export async function stopShop(repoRoot: string, name: string): Promise<boolean> {
  const runDir = shopRunDir(repoRoot, name);
  const state = await readState(runDir);
  if (state === undefined) {
    return false;
  }
  await killTree(state.storefront.pid);
  await killTree(state.backend.pid);
  await removeState(runDir);
  return true;
}

/** Stop every tracked shop; returns the names stopped. */
export async function stopAll(repoRoot: string): Promise<string[]> {
  const names = (await listStates(repoRoot)).map((state) => state.name);
  for (const name of names) {
    await stopShop(repoRoot, name);
  }
  return names;
}

export async function restartShop(
  repoRoot: string,
  name: string,
  deps: HostDeps,
): Promise<HostState> {
  const state = await readState(shopRunDir(repoRoot, name));
  if (state === undefined) {
    throw new CliError(`${name} is not tracked; use start`);
  }
  await stopShop(repoRoot, name);
  return startShop(
    { repoRoot, shop: state.shopDir, port: state.storefront.port, force: true },
    deps,
  );
}

export type ShopStatus = 'running' | 'partial' | 'dead' | 'available';

export interface ShopRow {
  readonly name: string;
  readonly status: ShopStatus;
  readonly storefrontUrl: string;
  readonly backendUrl: string;
  readonly pids: string;
}

/** Tracked shops, plus (with `all`) published shops under `outputs/shops/` that are not tracked. */
export async function listShops(repoRoot: string, all: boolean): Promise<ShopRow[]> {
  const rows = (await listStates(repoRoot)).map(rowFromState);
  if (!all) {
    return rows;
  }
  const tracked = new Set(rows.map((row) => row.name));
  const shopsDir = path.join(repoRoot, 'outputs', 'shops');
  const entries = await fs.readdir(shopsDir, { withFileTypes: true }).catch(() => []);
  for (const entry of entries.filter((e) => e.isDirectory()).sort()) {
    if (tracked.has(entry.name)) {
      continue;
    }
    if (await exists(path.join(shopsDir, entry.name, publish.SHOP_JSON))) {
      rows.push({
        name: entry.name,
        status: 'available',
        storefrontUrl: '-',
        backendUrl: '-',
        pids: '-',
      });
    }
  }
  return rows;
}

function rowFromState(state: HostState): ShopRow {
  const storefrontUp = pidAlive(state.storefront.pid);
  const backendUp = pidAlive(state.backend.pid);
  const status: ShopStatus =
    storefrontUp && backendUp ? 'running' : storefrontUp || backendUp ? 'partial' : 'dead';
  return {
    name: state.name,
    status,
    storefrontUrl: state.storefront.url,
    backendUrl: state.backend.url,
    pids: `${state.storefront.pid}/${state.backend.pid}`,
  };
}

async function readManifest(shopDir: string): Promise<ShopManifest> {
  if (!(await exists(path.join(shopDir, publish.SHOP_JSON)))) {
    throw new CliError(`${shopDir} has no ${publish.SHOP_JSON}; is it a published shop?`);
  }
  return publish.readShopManifest(shopDir);
}

/**
 * `pnpm install --ignore-workspace` and `pnpm build` each component whose
 * build output is missing or predates the manifest recorded in `build.json`.
 */
async function ensureBuilt(
  shopDir: string,
  manifest: ShopManifest,
  runDir: string,
  deps: HostDeps,
): Promise<void> {
  const record = await readBuildRecord(runDir);
  const current = {
    publishedAt: manifest.publishedAt,
    storefront: manifest.templates.storefront.contentHash,
    backend: manifest.templates.backend.contentHash,
  };
  const recordFresh =
    record !== undefined &&
    record.publishedAt === current.publishedAt &&
    record.storefront === current.storefront &&
    record.backend === current.backend;
  const buildLog = path.join(runDir, 'build.log');
  for (const component of COMPONENTS) {
    const dir = path.join(shopDir, component.name);
    if (recordFresh && (await exists(path.join(dir, component.output)))) {
      continue;
    }
    for (const argv of [
      ['pnpm', 'install', '--ignore-workspace', '--prefer-offline'],
      ['pnpm', 'build'],
    ]) {
      deps.log(`[host] ${component.name}: ${argv.join(' ')}`);
      const result = await deps.runner(argv, dir);
      await fs.mkdir(runDir, { recursive: true });
      await fs.appendFile(
        buildLog,
        `[${component.name}] ${argv.join(' ')} -> exit ${result.exitCode}\n${result.output}\n`,
      );
      if (result.exitCode !== 0) {
        throw new CliError(
          `${argv.join(' ')} failed in ${dir} (exit ${result.exitCode}); see ${buildLog}\n${tail(result.output)}`,
        );
      }
    }
  }
  await writeBuildRecord(runDir, current);
}

async function launch(
  deps: HostDeps,
  spec: {
    command: string;
    args: readonly string[];
    cwd: string;
    env: NodeJS.ProcessEnv;
    logPath: string;
    port: number;
    timeoutMs: number;
  },
): Promise<ProcessState> {
  const url = `http://127.0.0.1:${spec.port}`;
  const pid = await deps.spawn(spec);
  try {
    await waitForHealth(url, pid, spec.timeoutMs, spec.logPath);
  } catch (error) {
    await killTree(pid);
    throw error;
  }
  return { pid, port: spec.port, url, logPath: spec.logPath };
}

async function exists(file: string): Promise<boolean> {
  return fs
    .access(file)
    .then(() => true)
    .catch(() => false);
}

function tail(text: string, lines = 20): string {
  return text.trimEnd().split('\n').slice(-lines).join('\n');
}
