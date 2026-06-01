/**
 * CI drift guard for `src/__generated__/resolvers-types.ts`.
 *
 * Snapshots the committed file, re-runs `graphql-codegen`, then compares the
 * regenerated content byte-for-byte against the snapshot. If they differ, the
 * SDL in `src/schema.ts` and the checked-in generated module are out of sync
 * — exit non-zero so CI fails. The pre-run snapshot is restored on mismatch
 * so the working tree is left untouched, preserving the fail signal for
 * `git diff` and review.
 *
 * Run by `pnpm --filter @shop-gym/shop-backend codegen:check`.
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = resolve(HERE, '..');
const GENERATED = resolve(PACKAGE_ROOT, 'src/__generated__/resolvers-types.ts');

function main(): void {
  if (!existsSync(GENERATED)) {
    console.error(`codegen-check: ${GENERATED} does not exist; run \`pnpm codegen\` first.`);
    process.exit(1);
  }

  const before = readFileSync(GENERATED, 'utf8');

  execFileSync('pnpm', ['exec', 'graphql-codegen', '--config', 'codegen.ts'], {
    cwd: PACKAGE_ROOT,
    stdio: 'inherit',
  });

  const after = readFileSync(GENERATED, 'utf8');

  if (before === after) {
    console.log('codegen-check: generated resolver types are up to date.');
    return;
  }

  // Restore the committed file so callers see the drift in `git diff`, not in
  // their working copy.
  writeFileSync(GENERATED, before, 'utf8');
  console.error(
    'codegen-check: SDL and generated resolver types are out of sync.\n' +
      '  Run `pnpm --filter @shop-gym/shop-backend codegen` and commit the result.',
  );
  process.exit(1);
}

main();
