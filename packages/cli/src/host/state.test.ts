import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  type HostState,
  listStates,
  readBuildRecord,
  readState,
  removeState,
  shopRunDir,
  writeBuildRecord,
  writeState,
} from './state.js';

const STATE: HostState = {
  name: 'shop',
  shopDir: '/shops/shop',
  startedAt: '2026-01-01T00:00:00.000Z',
  backend: { pid: 11, port: 4001, url: 'http://127.0.0.1:4001', logPath: '/l/backend.log' },
  storefront: { pid: 12, port: 3001, url: 'http://127.0.0.1:3001', logPath: '/l/storefront.log' },
};

describe('host state', () => {
  it('round-trips state.json, lists tracked shops and removes state', async () => {
    const repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'host-state-'));
    const runDir = shopRunDir(repoRoot, 'shop');
    expect(runDir).toBe(path.join(repoRoot, '.run', 'shops', 'shop'));
    expect(await readState(runDir)).toBeUndefined();
    expect(await listStates(repoRoot)).toEqual([]);

    await writeState(runDir, STATE);
    await writeState(shopRunDir(repoRoot, 'alpha'), { ...STATE, name: 'alpha' });
    expect(await readState(runDir)).toEqual(STATE);
    expect((await listStates(repoRoot)).map((s) => s.name)).toEqual(['alpha', 'shop']);

    await removeState(runDir);
    expect(await readState(runDir)).toBeUndefined();
    await removeState(runDir);
  });

  it('rejects a malformed state file', async () => {
    const repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'host-state-'));
    const runDir = shopRunDir(repoRoot, 'shop');
    await fs.mkdir(runDir, { recursive: true });
    await fs.writeFile(path.join(runDir, 'state.json'), '{"name":"shop"}');
    await expect(readState(runDir)).rejects.toThrow();
  });

  it('round-trips the build record', async () => {
    const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'host-build-'));
    expect(await readBuildRecord(runDir)).toBeUndefined();
    const record = { publishedAt: 't', storefront: 'h1', backend: 'h2' };
    await writeBuildRecord(runDir, record);
    expect(await readBuildRecord(runDir)).toEqual(record);
  });
});
