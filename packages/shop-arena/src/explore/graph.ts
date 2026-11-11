/**
 * The Site state graph: one LLM completion that turns the finished parts
 * and the merged Capabilities into the graph of `site_graph.json`.
 *
 * A finished part is the `parts/<task_id>.md` of a Plan task that
 * `plan.md` marks done. The prompt gets only the H2 and H3 headings and
 * the Behavior lines of each one, under its Plan task id. The reply must
 * be one JSON object, bare or in one fenced block. It must pass the core
 * graph checks, and each transition must name a finished part as its
 * source. There is no retry.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import type { LlmClient, ModelRef } from '@shop-gym/agent';
import {
  OVERLAY_KINDS,
  PAGE_TYPES,
  type SiteGraph,
  SiteGraphValidationError,
  TRANSITION_EFFECTS,
  TRANSITION_TRIGGERS,
  parseSiteGraph,
} from '@shop-gym/core';
import { parse } from '@shop-gym/harness';

import type { Capabilities } from './capabilities.js';

/** The outline of the part of one finished Plan task. */
export interface FinishedPart {
  readonly taskId: string;
  /** The H2 and H3 headings and the Behavior lines of the part, in order. */
  readonly outline: string;
}

/** The graph reply is not one JSON object. */
export class SiteGraphReplyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SiteGraphReplyError';
  }
}

const HEADING_RE = /^#{2,3}\s/;
const BEHAVIOR_RE = /^\s*- \*\*Behavior:\*\*/;
/** A wrapped bullet goes on in indented lines. */
const CONTINUATION_RE = /^\s+\S/;
/** A reply that is one fenced block, optionally tagged `json`. */
const FENCED_RE = /^```(?:json)?[ \t]*\n([\s\S]*)\n```$/;
const PLACEHOLDER_RE = /\{\{([A-Z_]+)\}\}/g;

/** The H2 and H3 headings and the Behavior lines (with their wrapped lines) of a part. */
function partOutline(part: string): string {
  const kept: string[] = [];
  let inBehavior = false;
  for (const line of part.split(/\r?\n/)) {
    if (HEADING_RE.test(line) || BEHAVIOR_RE.test(line)) {
      kept.push(line.trimEnd());
      inBehavior = BEHAVIOR_RE.test(line);
    } else if (inBehavior && CONTINUATION_RE.test(line)) {
      kept.push(line.trimEnd());
    } else {
      inBehavior = false;
    }
  }
  return kept.join('\n');
}

/**
 * The finished parts of the harness run in `runDir`, in plan order: each
 * Plan task that `plan.md` marks done and that has a part. The plan, and
 * not the run summary, decides, so a part written outside the harness
 * counts when its task is marked done.
 *
 * @throws InvalidPlanError when `plan.md` is not a valid plan.
 */
export function readFinishedParts(runDir: string): FinishedPart[] {
  const tasks = parse(readFileSync(join(runDir, 'plan.md'), 'utf8'));
  return tasks.flatMap((task) => {
    const path = join(runDir, 'artifact', 'parts', `${task.id}.md`);
    if (task.status !== 'done' || !existsSync(path)) return [];
    return [{ taskId: task.id, outline: partOutline(readFileSync(path, 'utf8')) }];
  });
}

function codeList(values: readonly string[]): string {
  return values.map((value) => `\`${value}\``).join(', ');
}

/**
 * The graph prompt: `template` with its placeholders filled in one pass,
 * so a placeholder in the parts is not filled again.
 *
 * @throws Error when `template` has an unknown placeholder.
 */
function buildGraphPrompt(
  template: string,
  capabilities: Capabilities,
  parts: readonly FinishedPart[],
): string {
  const values: Readonly<Record<string, string>> = {
    PAGE_TYPES: codeList(PAGE_TYPES),
    OVERLAY_KINDS: codeList(OVERLAY_KINDS),
    TRIGGERS: codeList(TRANSITION_TRIGGERS),
    EFFECTS: codeList(TRANSITION_EFFECTS),
    CAPABILITIES: JSON.stringify(capabilities, null, 2),
    PARTS: parts
      .map((part) => `<part task="${part.taskId}">\n${part.outline}\n</part>`)
      .join('\n\n'),
  };
  return template.replace(PLACEHOLDER_RE, (placeholder, name: string) => {
    const value = values[name];
    if (value === undefined) throw new Error(`the graph prompt has an unknown ${placeholder}`);
    return value;
  });
}

/**
 * Reads the graph from a reply: one JSON object, bare or in one fenced
 * block. The checks run in this order: the core schema, the core graph
 * rules, and then the sources. Each transition must name one of `sources`
 * as its source. The first check that fails stops the parse.
 *
 * @throws SiteGraphReplyError when the reply is not one JSON object.
 * @throws SiteGraphValidationError that lists every problem of the first
 *   check that fails.
 */
function parseGraphReply(reply: string, sources: ReadonlySet<string>): SiteGraph {
  const trimmed = reply.trim();
  const body = FENCED_RE.exec(trimmed)?.[1] ?? trimmed;
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new SiteGraphReplyError(
      `the graph reply is not one JSON object, bare or in one fenced block: ${reason}`,
    );
  }
  const graph = parseSiteGraph(value);
  const problems = graph.transitions.flatMap((transition, index) =>
    sources.has(transition.source)
      ? []
      : [
          `transitions[${index}].source names no finished part: ${JSON.stringify(transition.source)}`,
        ],
  );
  if (problems.length > 0) throw new SiteGraphValidationError(problems);
  return graph;
}

/**
 * Writes the graph with one completion and checks the reply. There is no
 * retry.
 *
 * @throws SiteGraphReplyError when the reply is not one JSON object.
 * @throws SiteGraphValidationError that lists every problem of the first
 *   check that fails: the schema, the graph rules, or the sources.
 */
export async function renderSiteGraph(
  llm: LlmClient,
  model: ModelRef,
  template: string,
  capabilities: Capabilities,
  parts: readonly FinishedPart[],
  signal?: AbortSignal,
): Promise<SiteGraph> {
  const prompt = buildGraphPrompt(template, capabilities, parts);
  const completion = await llm.complete(signal ? { model, prompt, signal } : { model, prompt });
  return parseGraphReply(completion.text, new Set(parts.map((part) => part.taskId)));
}
