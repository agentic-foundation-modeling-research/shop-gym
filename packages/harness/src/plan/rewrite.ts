/**
 * Line-level rewrites of `plan.md` text that the harness applies itself.
 *
 * Both functions are pure: they take the file text and return the new text.
 * Task briefs, priorities, and unrelated lines are preserved byte for byte.
 */

import { NOTE_PREFIX } from './parser.js';

const TASK_LINE_RE = /^(?<lead>-\s+\[)(?<marker>.)(?<gap>\]\s+)(?<id>\S+)(?<rest>.*)$/;
const PRIORITY_TAG_RE = /\[priority:\s*-?\d+\]/;

/**
 * Rewrite `[x]` or `[!]` back to `[~]` for `taskId` so the executor loop
 * re-selects it. Used when a verifier returns FAIL. Returns the text
 * unchanged when the task is absent or not terminal.
 */
export function reopenTask(text: string, taskId: string): string {
  return mapLines(text, (line) => {
    const match = TASK_LINE_RE.exec(line);
    const groups = match?.groups;
    if (groups === undefined || groups.id !== taskId) {
      return line;
    }
    if (groups.marker !== 'x' && groups.marker !== '!') {
      return line;
    }
    return `${groups.lead}~${groups.gap}${groups.id}${groups.rest}`;
  });
}

/**
 * Force-mark `taskId` as `[!]` blocked with `note` as its trailer, keeping
 * an existing `[priority: N]` tag. Returns `undefined` when the line that
 * owns `taskId` cannot be found.
 */
export function blockTask(text: string, taskId: string, note: string): string | undefined {
  let rewritten = false;
  const out = mapLines(text, (line) => {
    const match = TASK_LINE_RE.exec(line);
    const groups = match?.groups;
    if (groups === undefined || groups.id !== taskId) {
      return line;
    }
    rewritten = true;
    const priorityTag = PRIORITY_TAG_RE.exec(groups.rest ?? '')?.[0];
    const priority = priorityTag === undefined ? '' : ` ${priorityTag}`;
    return `${groups.lead}!${groups.gap}${groups.id}${priority} ${NOTE_PREFIX} ${note}`;
  });
  return rewritten ? out : undefined;
}

/** Apply `fn` to each non-empty line, preserving the original line terminators. */
function mapLines(text: string, fn: (line: string) => string): string {
  const parts = text.split(/(\r\n|\r|\n)/);
  return parts.map((part, i) => (i % 2 === 0 && part !== '' ? fn(part) : part)).join('');
}
