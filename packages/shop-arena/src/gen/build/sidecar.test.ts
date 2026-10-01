import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { BackendSidecar, type SidecarLaunchOptions, freePort } from './sidecar.js';

let backendDir: string;
let launches: SidecarLaunchOptions[];
let stops: number;

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
});

function sidecar(): BackendSidecar {
  return new BackendSidecar({
    backendDir,
    dataDir: '/data',
    port: 4555,
    logPath: path.join(backendDir, '..', 'sidecar.log'),
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
    expect(await s.restartIfChanged()).toBe(false);
    await fs.writeFile(path.join(backendDir, 'node_modules', 'x', 'i.js'), '2');
    expect(await s.restartIfChanged()).toBe(false);
    await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'export const a = 2;\n');
    expect(await s.restartIfChanged()).toBe(true);
    expect(stops).toBe(1);
    expect(launches).toHaveLength(2);
    expect(await s.restartIfChanged()).toBe(false);
    await fs.writeFile(path.join(backendDir, 'package.json'), '{"name":"c"}\n');
    expect(await s.restartIfChanged()).toBe(true);
    expect(launches).toHaveLength(3);
    await s.stop();
  });

  it('serialises concurrent restarts', async () => {
    const s = sidecar();
    await s.start();
    await fs.writeFile(path.join(backendDir, 'src', 'schema', 'shop.ts'), 'changed');
    const results = await Promise.all([s.restartIfChanged(), s.restartIfChanged()]);
    expect(results).toEqual([true, false]);
    expect(launches).toHaveLength(2);
  });

  it('does nothing when stopped', async () => {
    const s = sidecar();
    expect(await s.restartIfChanged()).toBe(false);
    await s.stop();
    expect(launches).toHaveLength(0);
  });
});

describe('freePort', () => {
  it('returns a usable port number', async () => {
    const port = await freePort();
    expect(port).toBeGreaterThan(0);
    expect(port).toBeLessThan(65536);
  });
});
