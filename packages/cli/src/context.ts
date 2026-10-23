/**
 * Shared CLI context: repository root discovery, credential loading, the
 * default model, and the error type for expected failures.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { type Credentials, loadCredentials } from '@shop-gym/core';

/** Default `provider/model-id` for every LLM-backed subcommand. */
export const DEFAULT_MODEL = 'openai/gpt-5.5';

/** An expected failure: reported as one line on stderr, no stack trace. */
export class CliError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CliError';
  }
}

/**
 * Repository root: the nearest ancestor of `start` (then of this module)
 * that contains `pnpm-workspace.yaml`.
 *
 * @throws CliError when no ancestor qualifies.
 */
export function findRepoRoot(start: string = process.cwd()): string {
  const candidates = [start, path.dirname(fileURLToPath(import.meta.url))];
  for (const candidate of candidates) {
    const found = walkUp(candidate);
    if (found !== undefined) {
      return found;
    }
  }
  throw new CliError(`pnpm-workspace.yaml not found above ${start}; run inside the shop-gym repo`);
}

function walkUp(start: string): string | undefined {
  let dir = path.resolve(start);
  for (;;) {
    if (fs.existsSync(path.join(dir, 'pnpm-workspace.yaml'))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    dir = parent;
  }
}

/** Credentials from `<repoRoot>/.env` merged under the process environment. */
export function cliCredentials(repoRoot: string): Credentials {
  return loadCredentials(repoRoot, process.env);
}
