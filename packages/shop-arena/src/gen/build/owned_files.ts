/**
 * Which `artifact/` paths each build task may change.
 *
 * Ownership follows the two template copies: backend tasks (`gen_backend`,
 * `backend_*`) own `backend/`, every other task owns `storefront/`. Two kinds
 * of violation exist:
 *
 * - `protected`: the path is read-only for every task (backend contract
 *   files, template fingerprints, `storefront/.env`, anything outside the
 *   two template copies, and all of `backend/` when backend generation is
 *   off).
 * - `not_owned`: the path is in the copy the other kind of task owns.
 *
 * Paths are POSIX-style and relative to `artifact/`. Globs support `**`
 * (any depth), `*` (within one segment) and `?`.
 */

import { isBackendTask } from './verifiers/tasks.js';

export type ViolationKind = 'protected' | 'not_owned';

export interface OwnedFileViolation {
  readonly path: string;
  readonly kind: ViolationKind;
}

export interface OwnedFileOptions {
  /** Backend generation is on; when off, all of `backend/` is protected. */
  readonly genBackend: boolean;
}

/** Read-only for every task, including `gen_backend`. */
export const PROTECTED_GLOBS: readonly string[] = [
  'backend/src/data/schema.ts',
  'backend/src/sandbox/**',
  'backend/tests/contract/**',
  'backend/template.json',
  'storefront/template.json',
  'storefront/.env',
];

const STOREFRONT_PREFIX = 'storefront/';
const BACKEND_PREFIX = 'backend/';

/** Compile one glob into an anchored RegExp. */
export function globToRegExp(glob: string): RegExp {
  let source = '';
  for (let i = 0; i < glob.length; i += 1) {
    const char = glob[i];
    if (char === '*') {
      if (glob[i + 1] === '*') {
        i += 1;
        if (glob[i + 1] === '/') {
          i += 1;
          source += '(?:.*/)?';
        } else {
          source += '.*';
        }
      } else {
        source += '[^/]*';
      }
    } else if (char === '?') {
      source += '[^/]';
    } else if (char !== undefined) {
      source += char.replace(/[.+^${}()|[\]\\]/g, '\\$&');
    }
  }
  return new RegExp(`^${source}$`);
}

function matchesAny(rel: string, globs: readonly string[]): boolean {
  return globs.some((glob) => globToRegExp(glob).test(rel));
}

/**
 * Classify every changed path for `taskId`.
 *
 * @param taskId Selected task id of the iteration.
 * @param changedPaths Paths relative to `artifact/`, POSIX separators.
 * @param options Whether backend generation is on for the run.
 * @returns Violations in input order; empty when every path is allowed.
 */
export function ownedFileViolations(
  taskId: string,
  changedPaths: readonly string[],
  options: OwnedFileOptions,
): OwnedFileViolation[] {
  const owned = isBackendTask(taskId) ? BACKEND_PREFIX : STOREFRONT_PREFIX;
  const violations: OwnedFileViolation[] = [];
  for (const rel of changedPaths) {
    const inBackend = rel.startsWith(BACKEND_PREFIX);
    if (
      matchesAny(rel, PROTECTED_GLOBS) ||
      (inBackend && !options.genBackend) ||
      (!inBackend && !rel.startsWith(STOREFRONT_PREFIX))
    ) {
      violations.push({ path: rel, kind: 'protected' });
    } else if (!rel.startsWith(owned)) {
      violations.push({ path: rel, kind: 'not_owned' });
    }
  }
  return violations;
}
