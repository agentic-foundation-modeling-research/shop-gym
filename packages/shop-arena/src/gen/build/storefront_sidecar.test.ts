import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { SidecarError } from './sidecar.js';
import {
  type StorefrontLaunchOptions,
  StorefrontSidecar,
  launchWithRunner,
} from './storefront_sidecar.js';
import type { CommandResult } from './verifiers/subprocess.js';

let storefrontDir: string;
let launches: StorefrontLaunchOptions[];
let stops: number;

beforeEach(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'storefront-sidecar-'));
  storefrontDir = path.join(root, 'storefront');
  await fs.mkdir(path.join(storefrontDir, 'app'), { recursive: true });
  await fs.mkdir(path.join(storefrontDir, 'node_modules', 'x'), { recursive: true });
  await fs.writeFile(path.join(storefrontDir, 'app', 'root.tsx'), 'export const a = 1;\n');
  await fs.writeFile(path.join(storefrontDir, 'node_modules', 'x', 'i.js'), '1');
  launches = [];
  stops = 0;
});

function sidecar(): StorefrontSidecar {
  return new StorefrontSidecar({
    storefrontDir,
    backendUrl: 'http://127.0.0.1:4555',
    port: 4777,
    logPath: path.join(storefrontDir, '..', 'storefront.log'),
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

describe('launchWithRunner', () => {
  it('runs pnpm build in the storefront copy and fails on a non-zero exit', async () => {
    const calls: { argv: string[]; cwd: string }[] = [];
    const failed: CommandResult = { exitCode: 1, stdout: '', stderr: 'boom', timedOut: false };
    const logPath = path.join(storefrontDir, '..', 'storefront.log');
    await expect(
      launchWithRunner(
        async (argv, options) => {
          calls.push({ argv: [...argv], cwd: options.cwd });
          return failed;
        },
        {
          storefrontDir,
          backendUrl: 'http://127.0.0.1:4555',
          port: 4777,
          url: 'http://127.0.0.1:4777',
          logPath,
          healthTimeoutMs: 1000,
        },
      ),
    ).rejects.toBeInstanceOf(SidecarError);
    expect(calls).toEqual([{ argv: ['pnpm', 'build'], cwd: storefrontDir }]);
    expect(await fs.readFile(logPath, 'utf-8')).toContain('boom');
  });
});
