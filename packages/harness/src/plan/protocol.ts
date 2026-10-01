/**
 * Deterministic protocol checks run after every executor iteration.
 *
 * They enforce the executor contract on the post-iteration `plan.md`: the
 * selected task is present and terminal, no other task became terminal,
 * added tasks are pending, done tasks stay done, and ids stay unique.
 * Violation strings are stable and grep-friendly.
 */

import { z } from 'zod';

import { TERMINAL_STATUSES, type Task, type TaskList, reprIds } from './tasks.js';

/** Outcome of the harness-side checks, persisted to `checks/protocol.json`. */
export const protocolCheckResultSchema = z.object({
  iterId: z.string(),
  passed: z.boolean(),
  violations: z.array(z.string()),
});

export type ProtocolCheckResult = z.infer<typeof protocolCheckResultSchema>;

export interface ProtocolCheckInput {
  readonly iterId: string;
  readonly before: TaskList;
  readonly after: TaskList;
  readonly selectedTaskId: string;
}

/** Validate the executor contract against the pre and post snapshots. */
export function runProtocolChecks(input: ProtocolCheckInput): ProtocolCheckResult {
  const { iterId, before, after, selectedTaskId } = input;
  const beforeById = new Map(before.map((task) => [task.id, task]));
  const afterById = new Map(after.map((task) => [task.id, task]));
  const violations = [
    ...checkUniqueIds(after),
    ...checkSelectedTerminal(selectedTaskId, afterById),
    ...checkNoResurrection(beforeById, afterById),
    ...checkOnlySelectedNewlyTerminal(selectedTaskId, beforeById, after),
    ...checkAddedTasksPending(beforeById, after),
  ];
  return { iterId, passed: violations.length === 0, violations };
}

/** Concatenate the violations of several results into one, skipping absent ones. */
export function mergeProtocolResults(
  iterId: string,
  results: readonly (ProtocolCheckResult | undefined)[],
): ProtocolCheckResult {
  const violations = results.flatMap((result) => result?.violations ?? []);
  return { iterId, passed: violations.length === 0, violations };
}

function checkUniqueIds(after: TaskList): string[] {
  const counts = new Map<string, number>();
  for (const task of after) {
    counts.set(task.id, (counts.get(task.id) ?? 0) + 1);
  }
  const duplicates = [...counts.entries()]
    .filter(([, count]) => count > 1)
    .map(([id]) => id)
    .sort();
  return duplicates.length === 0
    ? []
    : [`duplicate task ids in after snapshot: ${reprIds(duplicates)}`];
}

function checkSelectedTerminal(selectedTaskId: string, afterById: Map<string, Task>): string[] {
  const selected = afterById.get(selectedTaskId);
  if (selected === undefined) {
    return [`selected task '${selectedTaskId}' is missing from after snapshot`];
  }
  if (!TERMINAL_STATUSES.has(selected.status)) {
    return [
      `selected task '${selectedTaskId}' is not terminal in after snapshot (status='${selected.status}')`,
    ];
  }
  return [];
}

function checkNoResurrection(
  beforeById: Map<string, Task>,
  afterById: Map<string, Task>,
): string[] {
  const resurrected: string[] = [];
  for (const [id, prev] of beforeById) {
    if (prev.status === 'done' && afterById.get(id)?.status !== 'done') {
      resurrected.push(id);
    }
  }
  return resurrected.length === 0
    ? []
    : [`resurrected [x] task ids: ${reprIds(resurrected.sort())}`];
}

function checkOnlySelectedNewlyTerminal(
  selectedTaskId: string,
  beforeById: Map<string, Task>,
  after: TaskList,
): string[] {
  const others: string[] = [];
  for (const task of after) {
    if (task.id === selectedTaskId || !TERMINAL_STATUSES.has(task.status)) {
      continue;
    }
    const prev = beforeById.get(task.id);
    if (prev !== undefined && TERMINAL_STATUSES.has(prev.status)) {
      continue;
    }
    others.push(task.id);
  }
  return others.length === 0
    ? []
    : [`non-selected tasks newly marked terminal: ${reprIds(others.sort())}`];
}

function checkAddedTasksPending(beforeById: Map<string, Task>, after: TaskList): string[] {
  const addedNonPending = after
    .filter((task) => !beforeById.has(task.id) && task.status !== 'pending')
    .map((task) => task.id)
    .sort();
  return addedNonPending.length === 0
    ? []
    : [`newly added tasks are not PENDING: ${reprIds(addedNonPending)}`];
}
