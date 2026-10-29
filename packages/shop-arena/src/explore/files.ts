/**
 * File tools for the explore agent, scoped to the harness run directory.
 *
 * The pi runtime exposes only the tools a request names, so the executor
 * needs these three to read prefetched evidence and to write `plan.md`,
 * `artifact/parts/*`, and `artifact/evidence/*`. Every path is relative to
 * the run directory; anything resolving outside it, also through a
 * symlink, is refused.
 */

import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, relative, resolve, sep } from 'node:path';

import type { Tool, ToolResult } from '@shop-gym/agent';
import { type Static, type TSchema, Type } from '@sinclair/typebox';

/** Characters of a file returned per `read_file` call. */
const READ_MAX_CHARS = 60_000;

const PATH = Type.String({ description: 'Path relative to the run directory, e.g. "plan.md".' });

function textResult(text: string): ToolResult {
  return { content: [{ type: 'text', text }] };
}

function errorResult(error: unknown): ToolResult {
  const message = error instanceof Error ? error.message : String(error);
  return { content: [{ type: 'text', text: `Error: ${message}` }], isError: true };
}

/**
 * Resolves `path` under `root`; throws when it escapes, also through a
 * symlink. The deepest existing part of the path must resolve inside the
 * real `root`, and the rest must not exist yet, so a write creates plain
 * directories and files inside the run directory.
 */
export function resolveInside(root: string, path: string): string {
  const target = resolve(root, path);
  if (!isInside(root, target)) {
    throw new Error(`path escapes the run directory: ${path}`);
  }
  let existing = target;
  // `existsSync` follows symlinks, so it is false for a broken one.
  while (!existsSync(existing)) {
    if (lstatSync(existing, { throwIfNoEntry: false })?.isSymbolicLink() === true) {
      throw new Error(`path goes through a broken symlink: ${path}`);
    }
    existing = dirname(existing);
  }
  if (!isInside(realpathSync(root), realpathSync(existing))) {
    throw new Error(`path escapes the run directory through a symlink: ${path}`);
  }
  return target;
}

function isInside(root: string, target: string): boolean {
  const rel = relative(root, target);
  return rel !== '..' && !rel.startsWith(`..${sep}`) && resolve(root, rel) === target;
}

function defineTool<P extends TSchema>(
  name: string,
  description: string,
  parameters: P,
  run: (params: Static<P>, cwd: string) => ToolResult,
): Tool<P> {
  return {
    name,
    description,
    parameters,
    async execute(params, ctx) {
      try {
        return run(params, ctx.cwd);
      } catch (error) {
        return errorResult(error);
      }
    },
  };
}

/** `read_file`, `write_file`, and `list_dir`, all rooted at the run dir. */
export function fileTools(): readonly Tool[] {
  const readFile = defineTool(
    'read_file',
    `Read a UTF-8 text file under the run directory. Returns at most ${READ_MAX_CHARS} characters; pass "offset" to continue.`,
    Type.Object({
      path: PATH,
      offset: Type.Optional(Type.Integer({ minimum: 0, description: 'Character offset.' })),
    }),
    ({ path, offset }, cwd) => {
      const text = readFileSync(resolveInside(cwd, path), 'utf8');
      const start = offset ?? 0;
      const chunk = text.slice(start, start + READ_MAX_CHARS);
      const suffix =
        start + chunk.length < text.length
          ? `\n\n[truncated: ${text.length - start - chunk.length} more characters; next offset ${start + chunk.length}]`
          : '';
      return textResult(chunk + suffix);
    },
  );

  const writeFile = defineTool(
    'write_file',
    'Write a UTF-8 text file under the run directory, creating parent directories and replacing any existing content.',
    Type.Object({ path: PATH, content: Type.String({ description: 'Full file content.' }) }),
    ({ path, content }, cwd) => {
      const target = resolveInside(cwd, path);
      mkdirSync(dirname(target), { recursive: true });
      writeFileSync(target, content);
      return textResult(`Wrote ${Buffer.byteLength(content)} bytes to ${path}`);
    },
  );

  const listDir = defineTool(
    'list_dir',
    'List the entries of a directory under the run directory. Directories end with "/".',
    Type.Object({ path: Type.Optional(PATH) }),
    ({ path }, cwd) => {
      const target = resolveInside(cwd, path ?? '.');
      const entries = readdirSync(target)
        .sort()
        .map((name) => (statSync(resolve(target, name)).isDirectory() ? `${name}/` : name));
      return textResult(entries.length === 0 ? '(empty)' : entries.join('\n'));
    },
  );

  return [readFile, writeFile, listDir];
}
