/**
 * `owned_files` verifier: diffs `artifact/` against the snapshot taken
 * after the previous iteration and classifies every changed path with the
 * owned-file table. Protected paths fail the iteration; edits in another
 * task's slice are advisory, since the agent can only move forward.
 */

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { type OwnedFileViolation, ownedFileViolations } from '../owned_files.js';
import { type TreeSnapshot, diffTrees, snapshotTree } from '../tree.js';

export const OWNED_FILES_NAME = 'owned_files';

export class OwnedFilesVerifier implements Verifier {
  readonly name = OWNED_FILES_NAME;
  private baseline: TreeSnapshot | undefined;

  appliesTo(_taskId: string): boolean {
    return true;
  }

  /** Record the current `artifact/` content as the baseline for the next run. */
  async prime(artifactDir: string): Promise<void> {
    this.baseline = await snapshotTree(artifactDir);
  }

  async run(ctx: VerifierContext): Promise<VerifierResult> {
    const before = this.baseline ?? {};
    const after = await snapshotTree(ctx.artifactDir);
    this.baseline = after;
    const changed = diffTrees(before, after);
    const violations = ownedFileViolations(ctx.selectedTaskId, changed);
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
  const crossSlice = violations.filter((v) => v.kind === 'cross_slice');
  if (protectedPaths.length > 0) {
    lines.push(
      '',
      'Protected paths (read-only for every task; restore them to the template content):',
      ...protectedPaths.map((v) => `- \`${v.path}\``),
    );
  }
  if (crossSlice.length > 0) {
    lines.push(
      '',
      "Paths in another task's slice (leave them to that task or to `visual_fix`):",
      ...crossSlice.map((v) => `- \`${v.path}\``),
    );
  }
  return lines.join('\n');
}
