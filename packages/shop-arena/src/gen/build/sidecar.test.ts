import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { BackendSidecar, SidecarError, type SidecarLaunchOptions, freePort } from './sidecar.js';

let backendDir: string;
let launches: SidecarLaunchOptions[];
let stops: number;
/** Launches that throw before the fake process starts. */
let failLaunches: number;

beforeEach(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'sidecar-'));
  backendDir = path.join(root, 'backend');
  await fs.mkdir(path.join(backendDir, 'src', 'schema'), { recursive: true });
  await fs.mkdir(path.join(backendDir, 'node_modules', 'x'), { recursive: true });
  await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'export const a = 1;\n');
  await fs.writeFile(path.join(backendDir, 'package.json'), '{"name":"b"}\n');
  await fs.writeFile(path.join(backendDir, 'node_modules', 'x', 'i.js'), '1');
  launches = [];
  stops = 0;
  failLaunches = 0;
});

function sidecar(): BackendSidecar {
  return new BackendSidecar({
    backendDir,
    dataDir: '/data',
    port: 4555,
    logPath: path.join(backendDir, '..', 'sidecar.log'),
    launch: async (options) => {
      launches.push(options);
      if (failLaunches > 0) {
        failLaunches -= 1;
        throw new SidecarError('sidecar exited with code 1 before /health');
      }
      return {
        stop: async () => {
          stops += 1;
        },
      };
    },
  });
}

describe('BackendSidecar', () => {
  it('starts once and exposes the loopback URL', async () => {
    const s = sidecar();
    await s.start();
    await s.start();
    expect(s.url).toBe('http://127.0.0.1:4555');
    expect(launches).toHaveLength(1);
    expect(launches[0]).toMatchObject({ backendDir, dataDir: '/data', port: 4555 });
    expect(s.running).toBe(true);
    await s.stop();
    expect(stops).toBe(1);
    expect(s.running).toBe(false);
  });

  it('restarts only when src or package.json changed', async () => {
    const s = sidecar();
    await s.start();
    expect(await s.ensureCurrent()).toBe(false);
    await fs.writeFile(path.join(backendDir, 'node_modules', 'x', 'i.js'), '2');
    expect(await s.ensureCurrent()).toBe(false);
    await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'export const a = 2;\n');
    expect(await s.ensureCurrent()).toBe(true);
    expect(stops).toBe(1);
    expect(launches).toHaveLength(2);
    expect(await s.ensureCurrent()).toBe(false);
    await fs.writeFile(path.join(backendDir, 'package.json'), '{"name":"c"}\n');
    expect(await s.ensureCurrent()).toBe(true);
    expect(launches).toHaveLength(3);
    await s.stop();
  });

  it('serialises concurrent restarts', async () => {
    const s = sidecar();
    await s.start();
    await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'changed');
    const results = await Promise.all([s.ensureCurrent(), s.ensureCurrent()]);
    expect(results).toEqual([true, false]);
    expect(launches).toHaveLength(2);
  });

  it('launches again after a failed restart, even when nothing changed since', async () => {
    const s = sidecar();
    await s.start();
    await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'broken');
    failLaunches = 2;
    await expect(s.ensureCurrent()).rejects.toThrow(SidecarError);
    expect(s.running).toBe(false);
    await expect(s.ensureCurrent()).rejects.toThrow(SidecarError);
    await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'fixed');
    expect(await s.ensureCurrent()).toBe(true);
    expect(s.running).toBe(true);
    expect(await s.ensureCurrent()).toBe(false);
    expect(launches).toHaveLength(4);
    await s.stop();
  });

  it('launches again after a failed start', async () => {
    const s = sidecar();
    failLaunches = 1;
    await expect(s.start()).rejects.toThrow(SidecarError);
    expect(await s.ensureCurrent()).toBe(true);
    expect(s.running).toBe(true);
    await s.stop();
  });

  it('does nothing before start and after stop', async () => {
    const s = sidecar();
    expect(await s.ensureCurrent()).toBe(false);
    await s.start();
    await s.stop();
    await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'changed');
    expect(await s.ensureCurrent()).toBe(false);
    expect(launches).toHaveLength(1);
  });
});

describe('freePort', () => {
  it('returns a usable port number', async () => {
    const port = await freePort();
    expect(port).toBeGreaterThan(0);
    expect(port).toBeLessThan(65536);
  });
});
