/**
 * `sandbox_contract` verifier for backend tasks.
 *
 * (a) The read-only backend paths (`src/data/schema.ts`, `src/sandbox/**`,
 *     `tests/contract/**`) must match the template byte for byte, using the
 *     per-file digests recorded in `backend/template.json` at seeding.
 * (b) The contract suite `tests/contract` must pass. The suite boots its own
 *     server over the template fixture (`tests/fixtures/sandbox_shop_v0`),
 *     not the run's dataset; it proves the agent kept the sandbox contract,
 *     not that the dataset is well formed.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { globToRegExp } from '../owned_files.js';
import { TEMPLATE_JSON, type TemplateFingerprint } from '../seed.js';
import { sha256Hex, snapshotTree } from '../tree.js';
import { BACKEND_DIRNAME } from './backend_commands.js';
import { type CommandRunner, argvLabel, renderCommandFailure, runCommand } from './subprocess.js';
import { isBackendTask } from './tasks.js';

export const SANDBOX_CONTRACT_NAME = 'sandbox_contract';
/** Relative to the backend copy. */
export const READ_ONLY_BACKEND_GLOBS: readonly string[] = [
  'src/data/schema.ts',
  'src/sandbox/**',
  'tests/contract/**',
];
const CONTRACT_ARGV: readonly string[] = ['pnpm', 'exec', 'vitest', 'run', 'tests/contract'];
const CONTRACT_TIMEOUT_MS = 300_000;

export interface ReadOnlyDrift {
  readonly path: string;
  readonly kind: 'modified' | 'deleted' | 'added';
}

/** Compare the read-only paths of `backendDir` against the seeded fingerprint. */
export async function readOnlyDrift(
  backendDir: string,
  fingerprint: TemplateFingerprint,
): Promise<ReadOnlyDrift[]> {
  const patterns = READ_ONLY_BACKEND_GLOBS.map(globToRegExp);
  const isReadOnly = (rel: string) => patterns.some((re) => re.test(rel));
  const drift: ReadOnlyDrift[] = [];
  for (const [rel, digest] of Object.entries(fingerprint.files)) {
    if (!isReadOnly(rel)) {
      continue;
    }
    const content = await fs.readFile(path.join(backendDir, rel)).catch(() => undefined);
    if (content === undefined) {
      drift.push({ path: rel, kind: 'deleted' });
    } else if (sha256Hex(content) !== digest) {
      drift.push({ path: rel, kind: 'modified' });
    }
  }
  const current = await snapshotTree(backendDir);
  for (const rel of Object.keys(current)) {
    if (isReadOnly(rel) && !(rel in fingerprint.files)) {
      drift.push({ path: rel, kind: 'added' });
    }
  }
  return drift.sort((a, b) => a.path.localeCompare(b.path));
}

export function sandboxContractVerifier(runner: CommandRunner = runCommand): Verifier {
  return {
    name: SANDBOX_CONTRACT_NAME,
    appliesTo: isBackendTask,
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const backendDir = path.join(ctx.artifactDir, BACKEND_DIRNAME);
      const fingerprint = JSON.parse(
        await fs.readFile(path.join(backendDir, TEMPLATE_JSON), 'utf-8'),
      ) as TemplateFingerprint;
      const drift = await readOnlyDrift(backendDir, fingerprint);
      if (drift.length > 0) {
        return {
          verdict: 'fail',
          feedback: [
            '`sandbox_contract`: read-only backend paths differ from the template.',
            'Restore them exactly; the sandbox contract is not negotiable.',
            '',
            ...drift.map((d) => `- \`backend/${d.path}\` (${d.kind})`),
          ].join('\n'),
          details: { drift },
        };
      }
      const result = await runner(CONTRACT_ARGV, {
        cwd: backendDir,
        timeoutMs: CONTRACT_TIMEOUT_MS,
      });
      const label = argvLabel(CONTRACT_ARGV);
      if (result.timedOut) {
        return {
          verdict: 'fail',
          feedback: `\`${label}\` exceeded the verifier timeout of ${CONTRACT_TIMEOUT_MS}ms.`,
          details: { drift: [], timeoutMs: CONTRACT_TIMEOUT_MS },
        };
      }
      if (result.exitCode !== 0) {
        return {
          verdict: 'fail',
          feedback: renderCommandFailure(label, result),
          details: { drift: [], exitCode: result.exitCode },
        };
      }
      return { verdict: 'pass', details: { drift: [], exitCode: 0 } };
    },
  };
}
