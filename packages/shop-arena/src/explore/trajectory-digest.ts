/**
 * The trajectory digest of the graph step: one line for each browser
 * action of an executor Iteration, so that the graph prompt can show a
 * flow that the explorer did but did not write down.
 *
 * A line names the action, the element that it acted on, and the URL
 * after it. An element is its role and accessible name from the latest
 * snapshot that showed its ref. A line does not show the ref, typed text
 * or selected values. The URL has no scheme and no host, and each query
 * value is `{value}`, so the digest shows URL shapes and no session or
 * tracking data.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { type TrajectoryStep, readTrajectory } from '@shop-gym/agent';
import { iterDirPath, iterationMetadataSchema, scanIterDirs } from '@shop-gym/harness';
import { z } from 'zod';

import { START_STATE_FILENAME } from './browser.js';

/** The browser actions of one executor Iteration. */
export interface IterationActions {
  /** `exec-NNNN`. */
  readonly iterId: string;
  /** The Plan task that the Iteration selected. */
  readonly taskId: string;
  /** The URL shape of the page that the Iteration started on. */
  readonly start: string;
  /** One line for each browser action, in call order. */
  readonly lines: readonly string[];
}

type ToolCall = Extract<TrajectoryStep, { kind: 'tool_call' }>;
type ToolResult = Extract<TrajectoryStep, { kind: 'tool_result' }>;

/** The digest name of one action call. `element` gives the element of a `ref` argument. */
type Describe = (call: ToolCall, element: (ref: unknown) => string) => string;

/** How a digest line names each browser action, keyed by tool name. */
const ACTIONS: ReadonlyMap<string, Describe> = new Map<string, Describe>([
  ['navigate', () => 'navigate'],
  ['back', () => 'back'],
  ['click', (call, element) => `click ${element(call.arguments.ref)}`],
  ['hover', (call, element) => `hover ${element(call.arguments.ref)}`],
  ['select', (call, element) => `select ${element(call.arguments.ref)}`],
  [
    'type',
    (call, element) =>
      `type ${element(call.arguments.ref)}${call.arguments.submit === true ? ' and submit' : ''}`,
  ],
  ['press', (call) => `press ${JSON.stringify(String(call.arguments.key))}`],
]);

/**
 * The Browser tools whose result ends on a page. Their `URL:` line tells
 * the URL that the next action starts from.
 */
const PAGE_TOOLS: ReadonlySet<string> = new Set([...ACTIONS.keys(), 'scroll', 'wait', 'snapshot']);

/** The name of an element whose ref no earlier snapshot showed. */
const UNKNOWN_ELEMENT = 'unknown element';

/**
 * The key of an element line of a snapshot: a role, then maybe a JSON
 * name, as in `link "Video Games"`.
 */
const ELEMENT_KEY_RE = /^(\w+)(?: ("(?:[^"\\]|\\.)*"))?/;

/** The first `URL:` line of a Browser tool result: the page after the call. */
const RESULT_URL_RE = /^URL: (.*)$/m;

/** The shape of a URL that is not an http or https URL. */
const UNKNOWN_PATH = 'unknown path';

const startStateSchema = z.object({ url: z.string() });

/**
 * The shape of `url`: its path and query, with each query value changed
 * to `{value}`. The shape has no scheme, host or fragment.
 */
function urlShape(url: string | null): string {
  if (url === null || !URL.canParse(url)) return UNKNOWN_PATH;
  const { protocol, pathname, search } = new URL(url);
  if (protocol !== 'http:' && protocol !== 'https:') return UNKNOWN_PATH;
  const query = search
    .slice(1)
    .split('&')
    .filter((item) => item !== '')
    .map((item) => `${item.replace(/=.*/s, '')}={value}`);
  return query.length === 0 ? pathname : `${pathname}?${query.join('&')}`;
}

/** The origin and path of `url`, which tell two pages apart, or `null` when it is not a URL. */
function pageOf(url: string | null): string | null {
  if (url === null || !URL.canParse(url)) return null;
  const { origin, pathname } = new URL(url);
  return `${origin}${pathname}`;
}

/**
 * The role and name of the element with `ref` in `snapshots`, newest
 * first, or `unknown element` when no snapshot shows it. A snapshot line
 * is `- <role> "<name>" [attributes] [ref=<ref>]`; a key with `: ` or
 * `#` in it comes single-quoted, with each `'` doubled.
 */
function elementName(snapshots: readonly string[], ref: unknown): string {
  if (typeof ref !== 'string') return UNKNOWN_ELEMENT;
  const token = `[ref=${ref}]`;
  for (const snapshot of [...snapshots].reverse()) {
    const line = snapshot.split('\n').find((text) => text.includes(token));
    if (line === undefined) continue;
    let key = line.trimStart().replace(/^- /, '');
    if (key.startsWith("'")) key = key.slice(1).replaceAll("''", "'");
    const match = ELEMENT_KEY_RE.exec(key);
    const role = match?.[1];
    if (role === undefined) return UNKNOWN_ELEMENT;
    const name = match?.[2];
    return name === undefined ? role : `${role} ${name}`;
  }
  return UNKNOWN_ELEMENT;
}

/**
 * The digest lines of `steps`, an Iteration that started on `startUrl`.
 * A line is `<action> -> <URL shape after the action>`, then
 * `(path changed)` when the action went to another path, or `(failed)`
 * when the action failed or has no result.
 */
function digestLines(steps: readonly TrajectoryStep[], startUrl: string | null): string[] {
  const results = new Map<string, ToolResult>();
  for (const step of steps) {
    if (step.kind === 'tool_result') results.set(step.callId, step);
  }
  let url = startUrl;
  const snapshots: string[] = [];
  const lines: string[] = [];
  for (const step of steps) {
    if (step.kind !== 'tool_call' || !PAGE_TOOLS.has(step.tool)) continue;
    const result = results.get(step.callId);
    const failed = result === undefined || result.isError;
    const before = url;
    if (!failed) url = RESULT_URL_RE.exec(result.output)?.[1] ?? url;
    const describe = ACTIONS.get(step.tool);
    if (describe === undefined) {
      if (step.tool === 'snapshot' && !failed) snapshots.push(result.output);
      continue;
    }
    const changed = pageOf(before) !== null && pageOf(url) !== pageOf(before);
    const mark = failed ? ' (failed)' : changed ? ' (path changed)' : '';
    const action = describe(step, (ref) => elementName(snapshots, ref));
    lines.push(`${action} -> ${urlShape(url)}${mark}`);
  }
  return lines;
}

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, 'utf8'));
}

/**
 * The browser actions of each executor Iteration under `<runDir>/iters/`
 * that wrote a trajectory, in run order. An Iteration with no
 * `metadata.json` names no selected Plan task, so the digest does not
 * show it. An Iteration from a run before start states has no
 * `start_state.json`, so its start is `unknown path`.
 */
export async function readIterationActions(runDir: string): Promise<IterationActions[]> {
  const itersDir = join(runDir, 'iters');
  const iterations: IterationActions[] = [];
  for (const iterId of (await scanIterDirs(itersDir)).execIterIds) {
    const iterDir = iterDirPath(itersDir, iterId);
    const metadataPath = join(iterDir, 'metadata.json');
    if (!existsSync(metadataPath)) continue;
    const { selectedTaskId } = iterationMetadataSchema.parse(readJson(metadataPath));
    if (selectedTaskId === null) continue;
    const startPath = join(iterDir, START_STATE_FILENAME);
    const startUrl = existsSync(startPath) ? startStateSchema.parse(readJson(startPath)).url : null;
    const { steps } = await readTrajectory(join(iterDir, 'trajectory.json'));
    iterations.push({
      iterId,
      taskId: selectedTaskId,
      start: urlShape(startUrl),
      lines: digestLines(steps, startUrl),
    });
  }
  return iterations;
}
