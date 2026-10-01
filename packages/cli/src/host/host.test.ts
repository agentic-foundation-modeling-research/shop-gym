import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { build } from '@shop-gym/shop-arena';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CliError } from '../context.js';
import {
  type HostDeps,
  listShops,
  resolveShopDir,
  restartShop,
  startShop,
  stopAll,
  stopShop,
} from './host.js';
import { type CommandResult, killTree, pidAlive, spawnDetached } from './process.js';
import { readBuildRecord, readState, shopRunDir, writeBuildRecord } from './state.js';

const SERVER = `
const http = require('node:http');
const port = Number(process.env.PORT ?? process.argv[3]);
http.createServer((req, res) => res.end(req.url === '/health' ? 'ok' : 'hi')).listen(port, '127.0.0.1');
`;

const MANIFEST = {
  name: 'shop',
  templates: {
    storefront: { name: 'storefront', commit: null, contentHash: 'sf1', files: {}, seededAt: 't' },
    backend: { name: 'shop_backend', commit: null, contentHash: 'be1', files: {}, seededAt: 't' },
  },
  genBackend: false,
  publishedAt: '2026-01-01T00:00:00.000Z',
  finalStatus: 'completed',
};

let repoRoot: string;
let shopDir: string;
let script: string;
let commands: string[][];
let deps: HostDeps;

async function write(file: string, content = ''): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, content);
}

async function writeManifest(overrides: Partial<typeof MANIFEST> = {}): Promise<void> {
  await write(path.join(shopDir, 'shop.json'), JSON.stringify({ ...MANIFEST, ...overrides }));
}

async function markBuilt(): Promise<void> {
  await write(path.join(shopDir, 'backend', 'dist', 'cli.js'));
  await write(path.join(shopDir, 'storefront', 'dist', 'server', 'index.js'));
  await writeBuildRecord(shopRunDir(repoRoot, 'shop'), {
    publishedAt: MANIFEST.publishedAt,
    storefront: 'sf1',
    backend: 'be1',
  });
}

beforeEach(async () => {
  repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'host-'));
  shopDir = path.join(repoRoot, 'outputs', 'shops', 'shop');
  script = path.join(repoRoot, 'server.cjs');
  await fs.writeFile(script, SERVER);
  await write(path.join(shopDir, 'data', 'store.json'), '{}');
  await write(path.join(shopDir, 'backend', 'package.json'), '{}');
  await write(path.join(shopDir, 'storefront', 'package.json'), '{}');
  await writeManifest();
  commands = [];
  deps = {
    runner: async (argv): Promise<CommandResult> => {
      commands.push([...argv]);
      return { exitCode: 0, output: `ran ${argv.join(' ')}` };
    },
    // Serve every component with the fake http server; the backend port is argv[2] of the real spec.
    spawn: (spec) =>
      spawnDetached({
        ...spec,
        command: process.execPath,
        args: [script, '-', spec.args[2] ?? ''],
      }),
    freePort: build.freePort,
    log: () => undefined,
  };
});

afterEach(async () => {
  await stopAll(repoRoot);
});

describe('resolveShopDir', () => {
  it('treats names as outputs/shops entries and paths as paths', () => {
    expect(resolveShopDir('/r', 'shop')).toBe(path.join('/r', 'outputs', 'shops', 'shop'));
    expect(resolveShopDir('/r', './shop')).toBe(path.resolve('./shop'));
    expect(resolveShopDir('/r', '/abs/shop')).toBe('/abs/shop');
  });
});

describe('startShop', () => {
  it('skips install/build when the record is fresh, starts both processes and tracks them', async () => {
    await markBuilt();
    const state = await startShop({ repoRoot, shop: 'shop', force: false }, deps);
    expect(commands).toEqual([]);
    expect(state.name).toBe('shop');
    expect(pidAlive(state.backend.pid)).toBe(true);
    expect(pidAlive(state.storefront.pid)).toBe(true);
    expect((await fetch(`${state.storefront.url}/health`)).ok).toBe(true);
    expect((await fetch(`${state.backend.url}/health`)).ok).toBe(true);
    expect(await readState(shopRunDir(repoRoot, 'shop'))).toEqual(state);
    expect(await listShops(repoRoot, false)).toEqual([
      {
        name: 'shop',
        status: 'running',
        storefrontUrl: state.storefront.url,
        backendUrl: state.backend.url,
        pids: `${state.storefront.pid}/${state.backend.pid}`,
      },
    ]);

    expect(await stopShop(repoRoot, 'shop')).toBe(true);
    expect(pidAlive(state.backend.pid)).toBe(false);
    expect(pidAlive(state.storefront.pid)).toBe(false);
    expect(await readState(shopRunDir(repoRoot, 'shop'))).toBeUndefined();
    expect(await stopShop(repoRoot, 'shop')).toBe(false);
  });

  it('honours an explicit storefront port and refuses a bound one', async () => {
    await markBuilt();
    const port = await build.freePort();
    const state = await startShop({ repoRoot, shop: 'shop', port, force: false }, deps);
    expect(state.storefront.port).toBe(port);
    expect(state.backend.port).not.toBe(port);
    await stopShop(repoRoot, 'shop');

    const server = await import('node:http').then((http) => http.createServer());
    await new Promise<void>((resolve) => server.listen(port, '127.0.0.1', resolve));
    try {
      await expect(startShop({ repoRoot, shop: 'shop', port, force: false }, deps)).rejects.toThrow(
        `port ${port} is already bound`,
      );
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it('installs and builds both components when the record is stale or output is missing', async () => {
    await startShop({ repoRoot, shop: 'shop', force: false }, deps);
    expect(commands).toEqual([
      ['pnpm', 'install', '--ignore-workspace', '--prefer-offline'],
      ['pnpm', 'build'],
      ['pnpm', 'install', '--ignore-workspace', '--prefer-offline'],
      ['pnpm', 'build'],
    ]);
    expect(await readBuildRecord(shopRunDir(repoRoot, 'shop'))).toEqual({
      publishedAt: MANIFEST.publishedAt,
      storefront: 'sf1',
      backend: 'be1',
    });
    const log = await fs.readFile(path.join(shopRunDir(repoRoot, 'shop'), 'build.log'), 'utf-8');
    expect(log).toContain('[backend] pnpm build -> exit 0');
    await stopShop(repoRoot, 'shop');

    // A republish (new publishedAt) invalidates the record even though dist exists.
    await markBuilt();
    await writeManifest({ publishedAt: '2026-02-01T00:00:00.000Z' });
    commands = [];
    await startShop({ repoRoot, shop: 'shop', force: false }, deps);
    expect(commands).toHaveLength(4);
  });

  it('surfaces a failed build with the log path', async () => {
    const failing: HostDeps = {
      ...deps,
      runner: async (argv) =>
        argv[1] === 'build'
          ? { exitCode: 1, output: 'tsc: error TS1234' }
          : { exitCode: 0, output: '' },
    };
    await expect(startShop({ repoRoot, shop: 'shop', force: false }, failing)).rejects.toThrow(
      /pnpm build failed in .*backend \(exit 1\); see .*build\.log\ntsc: error TS1234/,
    );
  });

  it('refuses an incomplete shop unless --force, and an already running shop', async () => {
    await markBuilt();
    await writeManifest({ finalStatus: 'refused' });
    await expect(startShop({ repoRoot, shop: 'shop', force: false }, deps)).rejects.toThrow(
      'shop finished with status refused; pass --force',
    );
    const state = await startShop({ repoRoot, shop: 'shop', force: true }, deps);
    await expect(startShop({ repoRoot, shop: 'shop', force: true }, deps)).rejects.toThrow(
      'already running',
    );
    await killTree(state.storefront.pid);
    await killTree(state.backend.pid);
  });

  it('rejects a directory without shop.json or data', async () => {
    await expect(startShop({ repoRoot, shop: 'missing', force: false }, deps)).rejects.toThrow(
      /has no shop\.json/,
    );
    await fs.rm(path.join(shopDir, 'data'), { recursive: true });
    await expect(startShop({ repoRoot, shop: 'shop', force: false }, deps)).rejects.toBeInstanceOf(
      CliError,
    );
  });

  it('kills the backend when the storefront fails to come up', async () => {
    await markBuilt();
    const backendPids: number[] = [];
    const broken: HostDeps = {
      ...deps,
      spawn: async (spec) => {
        if (spec.args[0] === 'server.mjs') {
          return spawnDetached({
            ...spec,
            command: process.execPath,
            args: ['-e', 'process.exit(1)'],
          });
        }
        const pid = await deps.spawn(spec);
        backendPids.push(pid);
        return pid;
      },
    };
    await expect(startShop({ repoRoot, shop: 'shop', force: false }, broken)).rejects.toThrow(
      /exited before answering \/health/,
    );
    expect(backendPids).toHaveLength(1);
    expect(pidAlive(backendPids[0] ?? -1)).toBe(false);
    expect(await readState(shopRunDir(repoRoot, 'shop'))).toBeUndefined();
  });
});

describe('restartShop and listShops', () => {
  it('restarts on the same storefront port and lists available shops with -a', async () => {
    await markBuilt();
    await write(
      path.join(repoRoot, 'outputs', 'shops', 'other', 'shop.json'),
      JSON.stringify(MANIFEST),
    );
    await write(path.join(repoRoot, 'outputs', 'shops', 'junk', 'readme.md'));
    await expect(restartShop(repoRoot, 'shop', deps)).rejects.toThrow('not tracked');

    const first = await startShop({ repoRoot, shop: 'shop', force: false }, deps);
    const second = await restartShop(repoRoot, 'shop', deps);
    expect(second.storefront.port).toBe(first.storefront.port);
    expect(second.storefront.pid).not.toBe(first.storefront.pid);
    expect(pidAlive(first.storefront.pid)).toBe(false);

    const rows = await listShops(repoRoot, true);
    expect(rows.map((r) => [r.name, r.status])).toEqual([
      ['shop', 'running'],
      ['other', 'available'],
    ]);
    expect(await stopAll(repoRoot)).toEqual(['shop']);
    expect(await listShops(repoRoot, false)).toEqual([]);
  });

  it('marks shops whose processes died', async () => {
    await markBuilt();
    const state = await startShop({ repoRoot, shop: 'shop', force: false }, deps);
    await killTree(state.backend.pid);
    expect((await listShops(repoRoot, false))[0]?.status).toBe('partial');
    await killTree(state.storefront.pid);
    expect((await listShops(repoRoot, false))[0]?.status).toBe('dead');
  });
});
