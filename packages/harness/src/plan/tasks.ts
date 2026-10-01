/**
 * Typed view of the `## Tasks` section of `plan.md`.
 *
 * Statuses map one-to-one onto the GFM checkbox markers the harness
 * understands: `[ ]` pending, `[~]` in progress, `[x]` done, `[!]` blocked.
 */

export type TaskStatus = 'pending' | 'in_progress' | 'done' | 'blocked';

/** One row of the `## Tasks` section. */
export interface Task {
  /** Unique id matching `[a-z0-9_]+`. */
  readonly id: string;
  readonly status: TaskStatus;
  /** Selection weight, higher wins. Defaults to 0. */
  readonly priority: number;
  /** Free-form trailer after the note separator, or `null`. */
  readonly note: string | null;
}

/** Tasks of one snapshot in source order. */
export type TaskList = readonly Task[];

export const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set(['done', 'blocked']);

/** The task with `id`, or `undefined`. */
export function taskById(tasks: TaskList, id: string): Task | undefined {
  return tasks.find((task) => task.id === id);
}

/**
 * Render ids the way Python's `repr(list[str])` does, e.g. `['a', 'b']`.
 * Protocol violation strings keep this format so telemetry stays
 * byte-compatible with the v1.0 harness.
 */
export function reprIds(ids: readonly string[]): string {
  return `[${ids.map((id) => `'${id}'`).join(', ')}]`;
}
