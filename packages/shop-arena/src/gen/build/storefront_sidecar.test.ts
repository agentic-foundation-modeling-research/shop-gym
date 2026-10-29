import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import {
  StorefrontBuildError,
  type StorefrontLaunchOptions,
  StorefrontSidecar,
} from './storefront_sidecar.js';
import type { CommandResult } from './verifiers/subprocess.js';

const OK: CommandResult = { exitCode: 0, stdout: 'built', stderr: '', timedOut: false };
const FAILED: CommandResult = { exitCode: 1, stdout: '', stderr: 'boom', timedOut: false };

let storefrontDir: string;
let launches: StorefrontLaunchOptions[];
let stops: number;
let builds: { argv: string[]; cwd: string }[];
let buildResult: CommandResult;

beforeEach(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'storefront-sidecar-'));
  storefrontDir = path.join(root, 'storefront');
  await fs.mkdir(path.join(storefrontDir, 'app'), { recursive: true });
  await fs.mkdir(path.join(storefrontDir, 'node_modules', 'x'), { recursive: true });
  await fs.writeFile(path.join(storefrontDir, 'app', 'root.tsx'), 'export const a = 1;\n');
  await fs.writeFile(path.join(storefrontDir, 'node_modules', 'x', 'i.js'), '1');
  launches = [];
  stops = 0;
  builds = [];
  buildResult = OK;
});

function sidecar(): StorefrontSidecar {
  return new StorefrontSidecar({
    storefrontDir,
    backendUrl: 'http://127.0.0.1:4555',
    port: 4777,
    logPath: path.join(storefrontDir, '..', 'storefront.log'),
    runner: async (argv, options) => {
      builds.push({ argv: [...argv], cwd: options.cwd });
      return buildResult;
    },
    launch: async (options) => {
      launches.push(options);
      return {
        stop: async () => {
          stops += 1;
        },
      };
    },
  });
}

describe('StorefrontSidecar', () => {
  it('starts once with the backend URL and port', async () => {
    const s = sidecar();
    await s.start();
    await s.start();
    expect(s.url).toBe('http://127.0.0.1:4777');
    expect(launches).toHaveLength(1);
    expect(launches[0]).toMatchObject({
      storefrontDir,
      backendUrl: 'http://127.0.0.1:4555',
      port: 4777,
      url: 'http://127.0.0.1:4777',
    });
    expect(builds).toEqual([{ argv: ['pnpm', 'build'], cwd: storefrontDir }]);
    expect(s.running).toBe(true);
  });

  it('restarts only when storefront sources changed', async () => {
    const s = sidecar();
    await s.start();
    expect(await s.restartIfChanged()).toBe(false);
    await fs.writeFile(path.join(storefrontDir, 'node_modules', 'x', 'i.js'), '2');
    expect(await s.restartIfChanged()).toBe(false);
    await fs.writeFile(path.join(storefrontDir, 'app', 'root.tsx'), 'export const a = 2;\n');
    expect(await s.restartIfChanged()).toBe(true);
    expect(launches).toHaveLength(2);
    expect(stops).toBe(1);
    expect(await s.restartIfChanged()).toBe(false);
  });

  it('ensureCurrent starts when stopped and restarts only on change', async () => {
    const s = sidecar();
    await s.ensureCurrent();
    expect(launches).toHaveLength(1);
    await s.ensureCurrent();
    expect(launches).toHaveLength(1);
    await fs.writeFile(path.join(storefrontDir, 'app', 'root.tsx'), 'export const a = 3;\n');
    await s.ensureCurrent();
    expect(launches).toHaveLength(2);
    expect(stops).toBe(1);
    expect(s.running).toBe(true);
  });

  it('stops cleanly and does nothing when not running', async () => {
    const s = sidecar();
    expect(await s.restartIfChanged()).toBe(false);
    await s.stop();
    await s.start();
    await s.stop();
    await s.stop();
    expect(stops).toBe(1);
    expect(s.running).toBe(false);
  });
});

describe('StorefrontSidecar builds', () => {
  it('builds each version of the copy once across build() and ensureCurrent()', async () => {
    const s = sidecar();
    expect(await s.build()).toEqual(OK);
    expect(s.running).toBe(false);
    await s.ensureCurrent();
    await s.ensureCurrent();
    expect(builds).toHaveLength(1);
    expect(launches).toHaveLength(1);

    await fs.writeFile(path.join(storefrontDir, 'app', 'root.tsx'), 'export const a = 4;\n');
    await s.build();
    expect(stops).toBe(1);
    expect(s.running).toBe(false);
    await s.ensureCurrent();
    expect(builds).toHaveLength(2);
    expect(launches).toHaveLength(2);
    expect(await fs.readFile(path.join(storefrontDir, '..', 'storefront.log'), 'utf-8')).toContain(
      '[build] exit 0\nbuilt',
    );
  });

  it('keeps a failed build until the copy changes', async () => {
    const s = sidecar();
    buildResult = FAILED;
    expect(await s.build()).toEqual(FAILED);
    const error = await s.ensureCurrent().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(StorefrontBuildError);
    expect((error as StorefrontBuildError).result).toEqual(FAILED);
    expect((error as StorefrontBuildError).message).toContain('boom');
    await expect(s.start()).rejects.toBeInstanceOf(StorefrontBuildError);
    expect(builds).toHaveLength(1);
    expect(launches).toHaveLength(0);

    buildResult = OK;
    await fs.writeFile(path.join(storefrontDir, 'app', 'root.tsx'), 'export const a = 5;\n');
    await s.ensureCurrent();
    expect(builds).toHaveLength(2);
    expect(launches).toHaveLength(1);
  });
});
