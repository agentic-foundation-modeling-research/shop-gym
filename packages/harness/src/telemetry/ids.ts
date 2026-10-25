/** Iteration ids and per-iteration directories under `iters/`. */

import * as path from 'node:path';

/** Id of the single planner iteration. */
export const PLAN_ITER_ID = 'plan';
const EXEC_ITER_ID_RE = /^exec-\d{4}$/;

/** `exec-NNNN` for the n-th (1-indexed) executor iteration. */
export function execIterId(n: number): string {
  if (!Number.isInteger(n) || n < 1) {
    throw new RangeError(`executor iteration index must be >= 1, got ${n}`);
  }
  return `exec-${String(n).padStart(4, '0')}`;
}

/** True for `plan` and `exec-NNNN`. */
export function isIterDirName(name: string): boolean {
  return name === PLAN_ITER_ID || EXEC_ITER_ID_RE.test(name);
}

export function isExecIterId(name: string): boolean {
  return EXEC_ITER_ID_RE.test(name);
}

/** `<itersDir>/<iterId>`; the directory is not created. */
export function iterDirPath(itersDir: string, iterId: string): string {
  if (!isIterDirName(iterId)) {
    throw new RangeError(`unrecognised iter_id: '${iterId}'`);
  }
  return path.join(itersDir, iterId);
}
