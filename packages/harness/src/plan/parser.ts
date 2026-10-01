/**
 * Parser and helpers for the `plan.md` snapshot format.
 *
 * Structural invariants enforced here: a single `## Tasks` section, one task
 * per top-level checkbox item, ids matching `[a-z0-9_]+` and unique within a
 * snapshot, a status marker from `{[ ], [~], [x], [!]}`, an optional
 * `[priority: N]` tag and an optional note trailer introduced by U+2014.
 */

import { type Task, type TaskList, type TaskStatus, reprIds } from './tasks.js';

/** Raised when `plan.md` violates a parser invariant or a `diff` rule. */
export class InvalidPlanError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'InvalidPlanError';
  }
}

/** Executor-visible state change between two snapshots. */
export interface PlanDiff {
  readonly completedTaskIds: readonly string[];
  readonly blockedTaskIds: readonly string[];
  /** Ids present in `after` but absent from `before`, in `after` order. */
  readonly addedTaskIds: readonly string[];
}

const STATUS_BY_MARKER: Readonly<Record<string, TaskStatus>> = {
  ' ': 'pending',
  '~': 'in_progress',
  x: 'done',
  '!': 'blocked',
};
const TASKS_HEADING_RE = /^##\s+Tasks\s*$/;
const OTHER_HEADING_RE = /^##\s+\S/;
const TASK_LINE_RE = /^-\s+\[(?<marker>.)\]\s+(?<id>\S+)\s*(?<rest>.*)$/;
const ID_RE = /^[a-z0-9_]+$/;
const PRIORITY_RE = /\[priority:\s*(-?\d+)\]/;
/** The note separator. Kept as an escape so the grammar is explicit about the byte. */
export const NOTE_PREFIX = '\u2014';

/** Split text into lines the way the grammar expects (LF, CRLF, or CR). */
export function splitLines(text: string): string[] {
  const lines = text.split(/\r\n|\r|\n/);
  if (lines.length > 0 && lines[lines.length - 1] === '') {
    lines.pop();
  }
  return lines;
}

/**
 * Parse a `plan.md` snapshot.
 *
 * @throws InvalidPlanError on any structural violation.
 */
export function parse(text: string): TaskList {
  const tasks: Task[] = [];
  const seen = new Set<string>();
  for (const raw of extractTasksSection(splitLines(text))) {
    if (!raw.startsWith('-')) {
      continue;
    }
    const match = TASK_LINE_RE.exec(raw);
    if (match?.groups === undefined) {
      throw new InvalidPlanError(`malformed task line: ${JSON.stringify(raw)}`);
    }
    const marker = match.groups.marker ?? '';
    const status = STATUS_BY_MARKER[marker];
    if (status === undefined) {
      throw new InvalidPlanError(
        `unknown status marker [${marker}] in line: ${JSON.stringify(raw)}`,
      );
    }
    const id = match.groups.id ?? '';
    if (!ID_RE.test(id)) {
      throw new InvalidPlanError(
        `invalid task id ${JSON.stringify(id)} in line: ${JSON.stringify(raw)}`,
      );
    }
    if (seen.has(id)) {
      throw new InvalidPlanError(`duplicate task id: '${id}'`);
    }
    seen.add(id);
    const { priority, note } = parseRest(match.groups.rest ?? '');
    tasks.push({ id, status, priority, note });
  }
  return tasks;
}

/**
 * The highest-priority retryable task, or `undefined` when none remain.
 *
 * Pending and in-progress tasks are retryable. Ties on priority go to the
 * earlier task in source order.
 */
export function selectNext(tasks: TaskList): Task | undefined {
  let best: Task | undefined;
  for (const task of tasks) {
    if (task.status !== 'pending' && task.status !== 'in_progress') {
      continue;
    }
    if (best === undefined || task.priority > best.priority) {
      best = task;
    }
  }
  return best;
}

/**
 * Diff two snapshots.
 *
 * @throws InvalidPlanError when an id that was done in `before` is missing
 *   or not done in `after`.
 */
export function diff(before: TaskList, after: TaskList): PlanDiff {
  const beforeById = new Map(before.map((task) => [task.id, task]));
  const afterById = new Map(after.map((task) => [task.id, task]));
  const resurrected: string[] = [];
  for (const [id, prev] of beforeById) {
    if (prev.status !== 'done') {
      continue;
    }
    if (afterById.get(id)?.status !== 'done') {
      resurrected.push(id);
    }
  }
  if (resurrected.length > 0) {
    throw new InvalidPlanError(`resurrected [x] task ids: ${reprIds(resurrected.sort())}`);
  }
  const completed: string[] = [];
  const blocked: string[] = [];
  const added: string[] = [];
  for (const task of after) {
    const prev = beforeById.get(task.id);
    if (prev === undefined) {
      added.push(task.id);
    } else if (task.status === 'done' && prev.status !== 'done') {
      completed.push(task.id);
    } else if (task.status === 'blocked' && prev.status !== 'blocked') {
      blocked.push(task.id);
    }
  }
  return { completedTaskIds: completed, blockedTaskIds: blocked, addedTaskIds: added };
}

function extractTasksSection(lines: readonly string[]): string[] {
  let inSection = false;
  let sawSection = false;
  const out: string[] = [];
  for (const line of lines) {
    if (TASKS_HEADING_RE.test(line)) {
      if (sawSection) {
        throw new InvalidPlanError("multiple '## Tasks' sections in plan.md");
      }
      inSection = true;
      sawSection = true;
      continue;
    }
    if (inSection && OTHER_HEADING_RE.test(line)) {
      inSection = false;
      continue;
    }
    if (inSection) {
      out.push(line);
    }
  }
  if (!sawSection) {
    throw new InvalidPlanError("plan.md is missing the '## Tasks' section");
  }
  return out;
}

function parseRest(rawRest: string): { priority: number; note: string | null } {
  let rest = rawRest.trim();
  let priority = 0;
  const match = PRIORITY_RE.exec(rest);
  if (match !== null) {
    priority = Number.parseInt(match[1] ?? '0', 10);
    rest = (rest.slice(0, match.index) + rest.slice(match.index + match[0].length)).trim();
  }
  if (rest === '') {
    return { priority, note: null };
  }
  if (!rest.startsWith(NOTE_PREFIX)) {
    throw new InvalidPlanError(`unexpected trailing content ${JSON.stringify(rest)} on task line`);
  }
  const note = rest.slice(NOTE_PREFIX.length).trim();
  return { priority, note: note === '' ? null : note };
}
