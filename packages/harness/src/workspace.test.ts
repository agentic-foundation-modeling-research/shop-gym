import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import {
  ResumeMismatchError,
  Workspace,
  type WorkspaceConfig,
  WorkspaceError,
} from './workspace.js';

let root: string;
let config: WorkspaceConfig;
beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'ws-'));
  config = {
    runDir: path.join(root, 'run'),
    agentsMd: '# agents\n',
    prompts: { planner: 'plan', execute: 'exec {{verifier_feedback}}' },
  };
});

describe('Workspace.create', () => {
  it('lays out the run dir', async () => {
    const ws = await Workspace.create(config);
    expect(await fs.readFile(ws.agentsMd, 'utf-8')).toBe('# agents\n');
    expect(await fs.readFile(ws.plannerPrompt, 'utf-8')).toBe('plan');
    expect(await fs.readFile(ws.executePrompt, 'utf-8')).toBe('exec {{verifier_feedback}}');
    expect(await fs.readFile(ws.planMd, 'utf-8')).toBe('');
    expect((await fs.stat(ws.itersDir)).isDirectory()).toBe(true);
    expect((await fs.stat(ws.artifactDir)).isDirectory()).toBe(true);
    expect(ws.seedManifest).toBeUndefined();
  });

  it('refuses a non-empty run dir', async () => {
    await fs.mkdir(config.runDir, { recursive: true });
    await fs.writeFile(path.join(config.runDir, 'junk'), '');
    await expect(Workspace.create(config)).rejects.toThrow(WorkspaceError);
  });

  it('copies the seed into artifact/ and persists a manifest', async () => {
    const seed = path.join(root, 'seed');
    await fs.mkdir(path.join(seed, 'data'), { recursive: true });
    await fs.writeFile(path.join(seed, 'data', 'x.json'), '{}');
    const ws = await Workspace.create({ ...config, artifactSeedDir: seed });
    expect(await fs.readFile(path.join(ws.artifactDir, 'data', 'x.json'), 'utf-8')).toBe('{}');
    expect(ws.seedManifest?.seededRoots).toEqual(['data']);
    const persisted = JSON.parse(await fs.readFile(ws.seedManifestPath, 'utf-8'));
    expect(persisted).toEqual(ws.seedManifest);
  });

  it('rejects a seed containing symlinks', async () => {
    const seed = path.join(root, 'seed');
    await fs.mkdir(seed);
    await fs.writeFile(path.join(seed, 'a'), 'a');
    await fs.symlink(path.join(seed, 'a'), path.join(seed, 'b'));
    await expect(Workspace.create({ ...config, artifactSeedDir: seed })).rejects.toThrow(
      WorkspaceError,
    );
  });
});

describe('Workspace.open', () => {
  it('reopens a matching workspace', async () => {
    await Workspace.create(config);
    const ws = await Workspace.open(config.runDir, config);
    expect(ws.runDir).toBe(config.runDir);
  });

  it('rejects prompt drift with the field name', async () => {
    await Workspace.create(config);
    const drifted = { ...config, prompts: { ...config.prompts, planner: 'other' } };
    const error = await Workspace.open(config.runDir, drifted).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ResumeMismatchError);
    expect((error as ResumeMismatchError).field).toBe('prompts.planner');
  });

  it('rejects a missing iters dir', async () => {
    const ws = await Workspace.create(config);
    await fs.rmdir(ws.itersDir);
    await expect(Workspace.open(config.runDir, config)).rejects.toMatchObject({
      field: 'iters_dir',
    });
  });

  it('rejects seed presence drift in both directions', async () => {
    const seed = path.join(root, 'seed');
    await fs.mkdir(seed);
    await fs.writeFile(path.join(seed, 'a'), 'a');
    await Workspace.create({ ...config, artifactSeedDir: seed });
    await expect(Workspace.open(config.runDir, config)).rejects.toMatchObject({
      field: 'seed_manifest',
    });
    const other = { ...config, runDir: path.join(root, 'run2') };
    await Workspace.create(other);
    await expect(
      Workspace.open(other.runDir, { ...other, artifactSeedDir: seed }),
    ).rejects.toMatchObject({
      field: 'seed_manifest',
    });
  });

  it('rejects a changed seed directory', async () => {
    const seed = path.join(root, 'seed');
    await fs.mkdir(seed);
    await fs.writeFile(path.join(seed, 'a'), 'a');
    const seeded = { ...config, artifactSeedDir: seed };
    await Workspace.create(seeded);
    await fs.writeFile(path.join(seed, 'a'), 'changed');
    await expect(Workspace.open(config.runDir, seeded)).rejects.toMatchObject({
      field: 'seed_manifest',
    });
  });
});

describe('snapshotPlan', () => {
  it('copies plan.md and refuses to overwrite unless asked', async () => {
    const ws = await Workspace.create(config);
    await ws.writePlan('## Tasks\n- [ ] a\n');
    const target = path.join(ws.itersDir, 'x', 'plan.before.md');
    await ws.snapshotPlan(target);
    expect(await fs.readFile(target, 'utf-8')).toBe('## Tasks\n- [ ] a\n');
    await expect(ws.snapshotPlan(target)).rejects.toThrow('snapshot target already exists');
    await ws.writePlan('## Tasks\n- [x] a\n');
    await ws.snapshotPlan(target, true);
    expect(await fs.readFile(target, 'utf-8')).toBe('## Tasks\n- [x] a\n');
  });
});
