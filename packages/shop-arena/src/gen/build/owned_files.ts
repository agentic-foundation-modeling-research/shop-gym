/**
 * Which `artifact/` paths each build task may change.
 *
 * The table ports the storefront slices of the Python executor prompt onto
 * the files of `templates/storefront` and adds the backend paths that
 * `gen_backend` (and any `backend_*` follow-up) owns.
 * Two kinds of violation exist:
 *
 * - `protected`: the path is read-only for every task (backend contract
 *   files, template fingerprints, anything outside the two template copies).
 * - `cross_slice`: the path belongs to another task's slice.
 *
 * Paths are POSIX-style and relative to `artifact/`. Globs support `**`
 * (any depth), `*` (within one segment) and `?`.
 */

import { isBackendTask } from './verifiers/tasks.js';

export type ViolationKind = 'protected' | 'cross_slice';

export interface OwnedFileViolation {
  readonly path: string;
  readonly kind: ViolationKind;
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

/** Paths a backend task may change. */
export const BACKEND_TASK_GLOBS: readonly string[] = [
  'backend/src/schema/**',
  'backend/src/resolvers/**',
  'backend/src/state/**',
  'backend/src/__generated__/**',
  'backend/src/**/*.test.ts',
  'backend/src/data/loader.ts',
  'backend/src/data/types.ts',
  'backend/tests/fixtures/**',
  'backend/package.json',
  'backend/pnpm-lock.yaml',
];

/**
 * Shared by every storefront task: the template keeps its components in a
 * few shared files, GraphQL documents in `app/lib/queries.ts`, and the route
 * table in `app/routes.ts`.
 */
const STOREFRONT_SHARED_GLOBS: readonly string[] = [
  'storefront/app/components/**',
  'storefront/app/lib/**',
  'storefront/app/routes.ts',
  'storefront/public/**',
  'storefront/package.json',
  'storefront/pnpm-lock.yaml',
];

/** Per-task storefront slices, keyed to the route files of `templates/storefront`. */
export const STOREFRONT_TASK_GLOBS: Readonly<Record<string, readonly string[]>> = {
  gen_theme: ['storefront/app/styles/**', 'storefront/app/root.tsx'],
  gen_navigation: ['storefront/app/root.tsx'],
  gen_homepage: ['storefront/app/routes/home.tsx'],
  gen_collections: [
    'storefront/app/routes/collections.tsx',
    'storefront/app/routes/collection.tsx',
  ],
  gen_product: ['storefront/app/routes/product.tsx'],
  gen_cart_search: [
    'storefront/app/routes/cart.tsx',
    'storefront/app/routes/search.tsx',
    'storefront/app/routes/checkout*.tsx',
    'storefront/app/routes/account/**',
  ],
  gen_info_pages: ['storefront/app/routes/page.tsx', 'storefront/app/routes/policy.tsx'],
  visual_fix: ['storefront/**'],
};

/** Shop-specific tasks the planner appends may add routes anywhere under `app/`. */
const UNKNOWN_TASK_GLOBS: readonly string[] = ['storefront/app/**'];

/** Globs `taskId` may change, before protected paths are subtracted. */
export function allowedGlobs(taskId: string): readonly string[] {
  if (isBackendTask(taskId)) {
    return BACKEND_TASK_GLOBS;
  }
  const slice = STOREFRONT_TASK_GLOBS[taskId] ?? UNKNOWN_TASK_GLOBS;
  return [...slice, ...STOREFRONT_SHARED_GLOBS];
}

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
 * Classify every changed path against the table for `taskId`.
 *
 * @param taskId Selected task id of the iteration.
 * @param changedPaths Paths relative to `artifact/`, POSIX separators.
 * @returns Violations in input order; empty when every path is allowed.
 */
export function ownedFileViolations(
  taskId: string,
  changedPaths: readonly string[],
): OwnedFileViolation[] {
  const allowed = allowedGlobs(taskId);
  const violations: OwnedFileViolation[] = [];
  for (const rel of changedPaths) {
    if (matchesAny(rel, PROTECTED_GLOBS)) {
      violations.push({ path: rel, kind: 'protected' });
    } else if (!rel.startsWith('storefront/') && !rel.startsWith('backend/')) {
      violations.push({ path: rel, kind: 'protected' });
    } else if (!matchesAny(rel, allowed)) {
      violations.push({ path: rel, kind: 'cross_slice' });
    }
  }
  return violations;
}
