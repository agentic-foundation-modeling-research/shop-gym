/**
 * Command-backed storefront verifiers: `typecheck` runs `pnpm typecheck`
 * inside `artifact/storefront`, and `build` asks the storefront sidecar to
 * build the copy, so the HTTP verifiers that follow serve that build
 * instead of building again. Both apply to storefront tasks and fail with
 * the captured output.
 */

import * as path from 'node:path';

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { STOREFRONT_BUILD_ARGV, STOREFRONT_BUILD_TIMEOUT_MS } from '../storefront_sidecar.js';
import {
  type CommandResult,
  type CommandRunner,
  argvLabel,
  renderCommandFailure,
  runCommand,
} from './subprocess.js';
import { isStorefrontTask } from './task_routes.js';

export const STOREFRONT_DIRNAME = 'storefront';
const TYPECHECK_TIMEOUT_MS = 180_000;

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
      const result = await runner(options.argv, {
        cwd: path.join(ctx.artifactDir, STOREFRONT_DIRNAME),
        timeoutMs: options.timeoutMs,
      });
      return commandVerdict(options.argv, options.timeoutMs, result);
    },
  };
}

/** Builds the storefront copy, e.g. `StorefrontSidecar`. */
export interface StorefrontBuilder {
  /** Resolves to the result of building the copy as it is now. */
  build(): Promise<CommandResult>;
}

export function storefrontTypecheckVerifier(runner?: CommandRunner): Verifier {
  return storefrontCommandVerifier({
    name: 'typecheck',
    argv: ['pnpm', 'typecheck'],
    timeoutMs: TYPECHECK_TIMEOUT_MS,
    ...(runner !== undefined ? { runner } : {}),
  });
}

export function storefrontBuildVerifier(builder: StorefrontBuilder): Verifier {
  return {
    name: 'build',
    appliesTo: isStorefrontTask,
    async run(): Promise<VerifierResult> {
      const result = await builder.build();
      return commandVerdict(STOREFRONT_BUILD_ARGV, STOREFRONT_BUILD_TIMEOUT_MS, result);
    },
  };
}

function commandVerdict(
  argv: readonly string[],
  timeoutMs: number,
  result: CommandResult,
): VerifierResult {
  const label = argvLabel(argv);
  if (result.timedOut) {
    return {
      verdict: 'fail',
      feedback: `\`${label}\` exceeded the verifier timeout of ${timeoutMs}ms.`,
      details: { argv, timeoutMs },
    };
  }
  if (result.exitCode === 0) {
    return { verdict: 'pass', details: { argv, exitCode: 0 } };
  }
  return {
    verdict: 'fail',
    feedback: renderCommandFailure(label, result),
    details: { argv, exitCode: result.exitCode },
  };
}
