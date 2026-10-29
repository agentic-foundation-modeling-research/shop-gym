/**
 * `owned_files` verifier: classifies every `artifact/` path the iteration
 * changed against the owned-file rules. Protected paths fail the iteration;
 * edits in the template copy the other kind of task owns are advisory.
 */

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import {
  type OwnedFileOptions,
  type OwnedFileViolation,
  ownedFileViolations,
} from '../owned_files.js';

export const OWNED_FILES_NAME = 'owned_files';

/** What the current iteration changed, e.g. `ArtifactCheckpoints`. */
export interface ChangedPaths {
  /** Sorted POSIX paths relative to `artifact/`, changed since the last kept iteration. */
  changedPaths(): Promise<readonly string[]>;
}

export class OwnedFilesVerifier implements Verifier {
  readonly name = OWNED_FILES_NAME;

  constructor(
    private readonly changes: ChangedPaths,
    private readonly options: OwnedFileOptions,
  ) {}

  appliesTo(_taskId: string): boolean {
    return true;
  }

  async run(ctx: VerifierContext): Promise<VerifierResult> {
    const changed = await this.changes.changedPaths();
    const violations = ownedFileViolations(ctx.selectedTaskId, changed, this.options);
    const details = { changedPaths: changed, violations };
    if (violations.length === 0) {
      return { verdict: 'pass', details };
    }
    const verdict = violations.some((v) => v.kind === 'protected') ? 'fail' : 'advisory';
    return { verdict, feedback: renderViolations(ctx.selectedTaskId, violations), details };
  }
}

function renderViolations(taskId: string, violations: readonly OwnedFileViolation[]): string {
  const lines = [
    `\`owned_files\`: ${violations.length} path(s) outside what \`${taskId}\` may edit.`,
  ];
  const protectedPaths = violations.filter((v) => v.kind === 'protected');
  const notOwned = violations.filter((v) => v.kind === 'not_owned');
  if (protectedPaths.length > 0) {
    lines.push(
      '',
      'Protected paths (read-only for this run; restore them to the template content):',
      ...protectedPaths.map((v) => `- \`${v.path}\``),
    );
  }
  if (notOwned.length > 0) {
    lines.push(
      '',
      'Paths in the other template copy (storefront tasks edit `storefront/`, backend tasks edit `backend/`):',
      ...notOwned.map((v) => `- \`${v.path}\``),
    );
  }
  return lines.join('\n');
}
