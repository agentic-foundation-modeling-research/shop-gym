/**
 * The Site state graph: an LLM completion that turns the finished parts
 * and the merged Capabilities into the graph of `site_graph.json`.
 *
 * A finished part is the `parts/<task_id>.md` of a Plan task that
 * `plan.md` marks done. The prompt gets each one with no Styling lines,
 * under its Plan task id. After each part come the browser actions of
 * each executor Iteration of its Plan task, in run order. A Plan task
 * with no Iteration, for example one whose part was written outside the
 * harness, has only its part. The reply must be one JSON object, bare or
 * in one fenced block. It must pass the core graph checks, and each
 * transition must name a finished part as its source. A reply that fails
 * a check gets one repair completion with its problems.
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
import { type IterationActions, readIterationActions } from './trajectory-digest.js';

/** The part of one finished Plan task, with no Styling lines, and the actions of its Iterations. */
export interface FinishedPart {
  readonly taskId: string;
  /** The part with no Styling lines and no blank end. */
  readonly text: string;
  /** The executor Iterations that selected the Plan task, in run order. */
  readonly iterations: readonly IterationActions[];
}

/** The graph prompt, and the repair prompt that follows it in the one repair call. */
export interface GraphPrompts {
  readonly graph: string;
  /** Has the `{{REPLY}}` and `{{PROBLEMS}}` placeholders. */
  readonly repair: string;
}

/** The graph reply is not one JSON object. */
export class SiteGraphReplyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SiteGraphReplyError';
  }
}

const STYLING_RE = /^\s*- \*\*Styling:\*\*/;
/** A reply that is one fenced block, optionally tagged `json`. */
const FENCED_RE = /^```(?:json)?[ \t]*\n([\s\S]*)\n```$/;
const PLACEHOLDER_RE = /\{\{([A-Z_]+)\}\}/g;

/**
 * A part with no Styling lines (with their wrapped lines) and no blank
 * end. A wrapped line has more indent than its Styling bullet. The
 * Styling lines tell how the storefront looks, not how a shopper moves
 * through it.
 */
function withoutStyling(part: string): string {
  const kept: string[] = [];
  /** The indent of the Styling bullet that the last lines belong to, if any. */
  let stylingIndent: number | null = null;
  for (const line of part.split(/\r?\n/)) {
    const indent = line.search(/\S/);
    if (STYLING_RE.test(line)) {
      stylingIndent = indent;
    } else if (stylingIndent === null || indent <= stylingIndent) {
      stylingIndent = null;
      kept.push(line);
    }
  }
  return kept.join('\n').trimEnd();
}

/**
 * The finished parts of the harness run in `runDir`, in plan order: each
 * Plan task that `plan.md` marks done and that has a part, with the
 * browser actions of the executor Iterations that selected the task. The
 * plan, and not the run summary, decides, so a part written outside the
 * harness counts when its task is marked done.
 *
 * @throws InvalidPlanError when `plan.md` is not a valid plan.
 */
export async function readFinishedParts(runDir: string): Promise<FinishedPart[]> {
  const tasks = parse(readFileSync(join(runDir, 'plan.md'), 'utf8'));
  const iterations = await readIterationActions(runDir);
  return tasks.flatMap((task) => {
    const path = join(runDir, 'artifact', 'parts', `${task.id}.md`);
    if (task.status !== 'done' || !existsSync(path)) return [];
    return [
      {
        taskId: task.id,
        text: withoutStyling(readFileSync(path, 'utf8')),
        iterations: iterations.filter((iteration) => iteration.taskId === task.id),
      },
    ];
  });
}

/** The `<actions>` block of one executor Iteration. */
function actionsBlock(iteration: IterationActions): string {
  const { taskId, iterId, start, lines } = iteration;
  return [
    `<actions task="${taskId}" iteration="${iterId}" start="${start}">`,
    ...lines,
    '</actions>',
  ].join('\n');
}

function codeList(values: readonly string[]): string {
  return values.map((value) => `\`${value}\``).join(', ');
}

/**
 * `template` with each `{{NAME}}` placeholder filled from `values` in one
 * pass, so a placeholder in a value is not filled again.
 *
 * @throws Error when `template` has an unknown placeholder.
 */
function fillPlaceholders(template: string, values: Readonly<Record<string, string>>): string {
  return template.replace(PLACEHOLDER_RE, (placeholder, name: string) => {
    const value = values[name];
    if (value === undefined) throw new Error(`a graph prompt has an unknown ${placeholder}`);
    return value;
  });
}

/**
 * The graph prompt: `template` with the closed lists, the capabilities
 * and the parts filled in.
 *
 * @throws Error when `template` has an unknown placeholder.
 */
function buildGraphPrompt(
  template: string,
  capabilities: Capabilities,
  parts: readonly FinishedPart[],
): string {
  return fillPlaceholders(template, {
    PAGE_TYPES: codeList(PAGE_TYPES),
    OVERLAY_KINDS: codeList(OVERLAY_KINDS),
    TRIGGERS: codeList(TRANSITION_TRIGGERS),
    EFFECTS: codeList(TRANSITION_EFFECTS),
    CAPABILITIES: JSON.stringify(capabilities, null, 2),
    PARTS: parts
      .map((part) =>
        [
          `<part task="${part.taskId}">\n${part.text}\n</part>`,
          ...part.iterations.map(actionsBlock),
        ].join('\n'),
      )
      .join('\n\n'),
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

/** The problems of a failed graph check, one `- ` line each. */
function problemLines(error: SiteGraphReplyError | SiteGraphValidationError): string {
  const problems = error instanceof SiteGraphValidationError ? error.problems : [error.message];
  return problems.map((problem) => `- ${problem}`).join('\n');
}

/**
 * Writes the graph with one completion and checks the reply. When the
 * reply fails a check, one repair completion gets the graph prompt, then
 * the `repair` prompt with the reply and its problems, and its reply is
 * checked the same way. There is no second repair.
 *
 * @throws SiteGraphReplyError when the repair reply is not one JSON
 *   object.
 * @throws SiteGraphValidationError that lists every problem of the first
 *   check that the repair reply fails: the schema, the graph rules, or the
 *   sources.
 */
export async function renderSiteGraph(
  llm: LlmClient,
  model: ModelRef,
  prompts: GraphPrompts,
  capabilities: Capabilities,
  parts: readonly FinishedPart[],
  log: (line: string) => void,
  signal?: AbortSignal,
): Promise<SiteGraph> {
  const complete = async (prompt: string): Promise<string> => {
    const completion = await llm.complete(signal ? { model, prompt, signal } : { model, prompt });
    return completion.text;
  };
  const sources = new Set(parts.map((part) => part.taskId));
  const prompt = buildGraphPrompt(prompts.graph, capabilities, parts);
  const reply = await complete(prompt);
  try {
    return parseGraphReply(reply, sources);
  } catch (error) {
    if (!(error instanceof SiteGraphReplyError || error instanceof SiteGraphValidationError)) {
      throw error;
    }
    log(`the graph reply failed its checks; asking once for a repair:\n${error.message}`);
    const repair = fillPlaceholders(prompts.repair, {
      REPLY: reply.trim(),
      PROBLEMS: problemLines(error),
    });
    return parseGraphReply(await complete(`${prompt}\n${repair}`), sources);
  }
}
