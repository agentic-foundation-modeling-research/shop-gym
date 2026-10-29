/**
 * The run-dir file tools against real directories and symlinks: a path may
 * go through a symlink only when the symlink stays in the run directory.
 */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { ToolContent, ToolContext, ToolResult } from '@shop-gym/agent';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fileTools, resolveInside } from './files.js';

let base: string;
let run: string;
let outside: string;

beforeEach(async () => {
  base = await fs.mkdtemp(path.join(os.tmpdir(), 'shopgym-files-'));
  run = path.join(base, 'run');
  outside = path.join(base, 'outside');
  await fs.mkdir(run);
  await fs.mkdir(outside);
  await fs.writeFile(path.join(outside, 'secret.txt'), 'secret');
});

afterEach(async () => {
  await fs.rm(base, { recursive: true, force: true });
});

function call(name: string, params: Record<string, unknown>): Promise<ToolResult> {
  const tool = fileTools().find((t) => t.name === name);
  if (tool === undefined) throw new Error(`no tool ${name}`);
  const ctx: ToolContext = { cwd: run, callId: 'call-1', signal: new AbortController().signal };
  return tool.execute(params, ctx);
}

function text(content: readonly ToolContent[]): string {
  return content
    .filter((c): c is Extract<ToolContent, { type: 'text' }> => c.type === 'text')
    .map((c) => c.text)
    .join('\n');
}

describe('resolveInside', () => {
  it('resolves a path that does not exist yet', () => {
    expect(resolveInside(run, 'a/b/c.txt')).toBe(path.join(run, 'a', 'b', 'c.txt'));
  });

  it('refuses a path that leaves the run directory', () => {
    expect(() => resolveInside(run, '../outside/secret.txt')).toThrow(
      'path escapes the run directory: ../outside/secret.txt',
    );
  });

  it('accepts a run directory reached through a symlink', async () => {
    const link = path.join(base, 'run-link');
    await fs.symlink(run, link);
    expect(resolveInside(link, 'plan.md')).toBe(path.join(link, 'plan.md'));
  });
});

describe('fileTools', () => {
  it('reads through a symlink that stays in the run directory', async () => {
    const pkg = path.join(run, 'node_modules', '.pnpm', 'pkg');
    await fs.mkdir(pkg, { recursive: true });
    await fs.writeFile(path.join(pkg, 'index.d.ts'), 'export {};');
    await fs.symlink(pkg, path.join(run, 'node_modules', 'pkg'));
    const result = await call('read_file', { path: 'node_modules/pkg/index.d.ts' });
    expect(result.isError).toBeUndefined();
    expect(text(result.content)).toBe('export {};');
  });

  it('refuses to read a file through a symlink that leaves the run directory', async () => {
    await fs.symlink(path.join(outside, 'secret.txt'), path.join(run, 'leak'));
    const result = await call('read_file', { path: 'leak' });
    expect(result.isError).toBe(true);
    expect(text(result.content)).toBe(
      'Error: path escapes the run directory through a symlink: leak',
    );
  });

  it('refuses to list a directory through a symlink that leaves the run directory', async () => {
    await fs.symlink(outside, path.join(run, 'out'));
    const result = await call('list_dir', { path: 'out' });
    expect(result.isError).toBe(true);
    expect(text(result.content)).not.toContain('secret.txt');
  });

  it('refuses to write under a symlink that leaves the run directory', async () => {
    await fs.symlink(outside, path.join(run, 'out'));
    const result = await call('write_file', { path: 'out/new/file.txt', content: 'x' });
    expect(result.isError).toBe(true);
    await expect(fs.readdir(outside)).resolves.toEqual(['secret.txt']);
  });

  it('refuses to write through a broken symlink', async () => {
    await fs.symlink(path.join(outside, 'created.txt'), path.join(run, 'dangling'));
    const result = await call('write_file', { path: 'dangling', content: 'x' });
    expect(result.isError).toBe(true);
    expect(text(result.content)).toBe('Error: path goes through a broken symlink: dangling');
    await expect(fs.readdir(outside)).resolves.toEqual(['secret.txt']);
  });
});
