/**
 * Command-backed backend verifiers: `backend_typecheck` runs `pnpm typecheck`
 * and `backend_test` runs `pnpm test` inside `artifact/backend`. Both apply
 * to backend tasks only and fail with the captured output.
 */

import * as path from 'node:path';

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { type CommandRunner, argvLabel, renderCommandFailure, runCommand } from './subprocess.js';
import { isBackendTask } from './tasks.js';

export const BACKEND_DIRNAME = 'backend';
const TYPECHECK_TIMEOUT_MS = 180_000;
const TEST_TIMEOUT_MS = 300_000;

export interface BackendCommandVerifierOptions {
  readonly name: string;
  readonly argv: readonly string[];
  readonly timeoutMs: number;
  readonly runner?: CommandRunner;
}

/** A verifier that passes when `argv` exits 0 inside `artifact/backend`. */
export function backendCommandVerifier(options: BackendCommandVerifierOptions): Verifier {
  const runner = options.runner ?? runCommand;
  return {
    name: options.name,
    appliesTo: isBackendTask,
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const label = argvLabel(options.argv);
      const result = await runner(options.argv, {
        cwd: path.join(ctx.artifactDir, BACKEND_DIRNAME),
        timeoutMs: options.timeoutMs,
      });
      if (result.timedOut) {
        return {
          verdict: 'fail',
          feedback: `\`${label}\` exceeded the verifier timeout of ${options.timeoutMs}ms.`,
          details: { argv: options.argv, timeoutMs: options.timeoutMs },
        };
      }
      if (result.exitCode === 0) {
        return { verdict: 'pass', details: { argv: options.argv, exitCode: 0 } };
      }
      return {
        verdict: 'fail',
        feedback: renderCommandFailure(label, result),
        details: { argv: options.argv, exitCode: result.exitCode },
      };
    },
  };
}

export function backendTypecheckVerifier(runner?: CommandRunner): Verifier {
  return backendCommandVerifier({
    name: 'backend_typecheck',
    argv: ['pnpm', 'typecheck'],
    timeoutMs: TYPECHECK_TIMEOUT_MS,
    ...(runner !== undefined ? { runner } : {}),
  });
}

export function backendTestVerifier(runner?: CommandRunner): Verifier {
  return backendCommandVerifier({
    name: 'backend_test',
    argv: ['pnpm', 'test'],
    timeoutMs: TEST_TIMEOUT_MS,
    ...(runner !== undefined ? { runner } : {}),
  });
}
