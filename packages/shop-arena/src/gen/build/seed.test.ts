import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../../templates.js';
import { SeedError, defaultBackendTemplateDir, seedTemplate, templateFingerprint } from './seed.js';
import { type CommandRunner, runCommand } from './verifiers/subprocess.js';

const TRACKED = ['package.json', 'tsconfig.json', 'src/data/schema.ts', 'src/sandbox/episode.ts'];

/** Answers `git` with a fixed file list and records every other command. */
function fakeRunner(calls: string[][], tracked: readonly string[] = TRACKED): CommandRunner {
  return async (argv) => {
    calls.push([...argv]);
    if (argv[0] === 'git' && argv[1] === 'ls-files') {
      return { exitCode: 0, stdout: `${tracked.join('\0')}\0`, stderr: '', timedOut: false };
    }
    if (argv[0] === 'git' && argv[1] === 'rev-parse') {
      return { exitCode: 0, stdout: 'abc123\n', stderr: '', timedOut: false };
    }
    return { exitCode: 0, stdout: '', stderr: '', timedOut: false };
  };
}

describe('templateFingerprint', () => {
  it('hashes the tracked files and records the commit', async () => {
    const fp = await templateFingerprint(defaultBackendTemplateDir(), fakeRunner([]));
    expect(fp.name).toBe('shop_backend');
    expect(fp.commit).toBe('abc123');
    expect(fp.dirty).toBe(false);
    expect(Object.keys(fp.files).sort()).toEqual([...TRACKED].sort());
    expect(fp.contentHash).toMatch(/^[0-9a-f]{64}$/);
  });

  it('flags tracked changes since the commit, not untracked files', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'template-'));
    const git = async (...args: string[]): Promise<void> => {
      const result = await runCommand(['git', ...args], {
        cwd: dir,
        timeoutMs: 30_000,
        env: {
          GIT_CONFIG_GLOBAL: '/dev/null',
          GIT_CONFIG_NOSYSTEM: '1',
          GIT_AUTHOR_NAME: 'test',
          GIT_AUTHOR_EMAIL: 'test@localhost',
          GIT_COMMITTER_NAME: 'test',
          GIT_COMMITTER_EMAIL: 'test@localhost',
        },
      });
      expect(result.exitCode).toBe(0);
    };
    await fs.writeFile(path.join(dir, 'package.json'), '{}\n');
    await git('init', '--quiet', '--initial-branch=main');
    await git('add', 'package.json');
    await git('commit', '--quiet', '-m', 'template');
    await fs.writeFile(path.join(dir, 'scratch.md'), 'not tracked\n');
    const clean = await templateFingerprint(dir);
    expect(clean.commit).toMatch(/^[0-9a-f]{40}$/);
    expect(clean.dirty).toBe(false);

    await fs.writeFile(path.join(dir, 'package.json'), '{"name":"edited"}\n');
    const edited = await templateFingerprint(dir);
    expect(edited.commit).toBe(clean.commit);
    expect(edited.dirty).toBe(true);
    expect(edited.contentHash).not.toBe(clean.contentHash);
  });
});

describe('seedTemplate', () => {
  it('copies exactly the tracked files, detaches tsconfig, writes template.json, installs', async () => {
    const destDir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'seed-')), 'backend');
    const calls: string[][] = [];
    const fp = await seedTemplate({
      templateDir: defaultBackendTemplateDir(),
      destDir,
      runner: fakeRunner(calls),
    });
    const copied = (await fs.readdir(destDir, { recursive: true })).filter(
      (rel) => !rel.includes(path.sep) || rel.endsWith('.ts'),
    );
    expect(copied.sort()).toEqual(
      [
        'package.json',
        'tsconfig.json',
        'tsconfig.base.json',
        'template.json',
        'src',
        'src/data/schema.ts',
        'src/sandbox/episode.ts',
      ].sort(),
    );
    const tsconfig = JSON.parse(
      await fs.readFile(path.join(destDir, 'tsconfig.json'), 'utf-8'),
    ) as {
      extends: string;
    };
    expect(tsconfig.extends).toBe('./tsconfig.base.json');
    const written = JSON.parse(await fs.readFile(path.join(destDir, 'template.json'), 'utf-8')) as {
      commit: string;
      dirty: boolean;
      contentHash: string;
    };
    expect(written.commit).toBe(fp.commit);
    expect(written.dirty).toBe(false);
    expect(written.contentHash).toBe(fp.contentHash);
    expect(calls.at(-1)).toEqual(['pnpm', 'install', '--ignore-workspace', '--prefer-offline']);
    await expect(
      seedTemplate({ templateDir: defaultBackendTemplateDir(), destDir, runner: fakeRunner([]) }),
    ).rejects.toThrow(SeedError);
  });

  it('freezes the lockfile when the template tracks one', async () => {
    const destDir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'seed-')), 'storefront');
    const calls: string[][] = [];
    await seedTemplate({
      templateDir: STOREFRONT_TEMPLATE_DIR,
      destDir,
      runner: fakeRunner(calls, ['package.json', 'pnpm-lock.yaml']),
    });
    expect(calls.at(-1)).toEqual([
      'pnpm',
      'install',
      '--ignore-workspace',
      '--prefer-offline',
      '--frozen-lockfile',
    ]);
  });

  it('fails when the install exits non-zero', async () => {
    const destDir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'seed-')), 'backend');
    const runner: CommandRunner = async (argv, options) => {
      if (argv[0] === 'pnpm') {
        return { exitCode: 1, stdout: '', stderr: 'boom', timedOut: false };
      }
      return fakeRunner([])(argv, options);
    };
    await expect(
      seedTemplate({ templateDir: defaultBackendTemplateDir(), destDir, runner }),
    ).rejects.toThrow(/pnpm install failed/);
  });
});
