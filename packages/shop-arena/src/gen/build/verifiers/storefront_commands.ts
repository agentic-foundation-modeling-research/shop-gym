/**
 * Command-backed storefront verifiers: `typecheck` runs `pnpm typecheck`
 * and `build` runs `pnpm build` inside `artifact/storefront`. Both apply
 * to storefront tasks and fail with the captured output.
 */

import * as path from 'node:path';

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { type CommandRunner, argvLabel, renderCommandFailure, runCommand } from './subprocess.js';
import { isStorefrontTask } from './task_routes.js';

export const STOREFRONT_DIRNAME = 'storefront';
const TYPECHECK_TIMEOUT_MS = 180_000;
const BUILD_TIMEOUT_MS = 300_000;

export interface StorefrontCommandVerifierOptions {
  readonly name: string;
  readonly argv: readonly string[];
  readonly timeoutMs: number;
  readonly runner?: CommandRunner;
}

/** A verifier that passes when `argv` exits 0 inside `artifact/storefront`. */
export function storefrontCommandVerifier(options: StorefrontCommandVerifierOptions): Verifier {
  const runner = options.runner ?? runCommand;
  return {
    name: options.name,
    appliesTo: isStorefrontTask,
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const label = argvLabel(options.argv);
      const result = await runner(options.argv, {
        cwd: path.join(ctx.artifactDir, STOREFRONT_DIRNAME),
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

export function storefrontTypecheckVerifier(runner?: CommandRunner): Verifier {
  return storefrontCommandVerifier({
    name: 'typecheck',
    argv: ['pnpm', 'typecheck'],
    timeoutMs: TYPECHECK_TIMEOUT_MS,
    ...(runner !== undefined ? { runner } : {}),
  });
}

export function storefrontBuildVerifier(runner?: CommandRunner): Verifier {
  return storefrontCommandVerifier({
    name: 'build',
    argv: ['pnpm', 'build'],
    timeoutMs: BUILD_TIMEOUT_MS,
    ...(runner !== undefined ? { runner } : {}),
  });
}
