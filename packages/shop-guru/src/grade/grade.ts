/**
 * Grades one finished episode against its task's checks.
 *
 * Programmatic checks run first, in task order: `string_match` on the answer,
 * `url_match` on the final URL, `locator_probe` through the episode's browser
 * session, and `state_check` against the backend's episode snapshot. The
 * optional `llm_judge` runs last and sees the programmatic results.
 */

import { type LlmClient, type ModelRef, addUsage } from '@shop-gym/agent';
import { type BrowserSession, probe } from '@shop-gym/browser';
import type { Check, CheckResult, Task, Usage } from '@shop-gym/core';

import type { BackendClient } from '../backend.js';
import { ZERO_USAGE } from '../usage.js';
import { judge } from './judge.js';
import { type MatchResult, matchState, matchText, matchUrl, resolvePointer } from './matchers.js';

/** Which model judges `llm_judge` and `fuzzyMatch`. */
export interface Judge {
  readonly client: LlmClient;
  readonly model: ModelRef;
}

export interface GradeInput {
  readonly task: Task;
  readonly answer: string | null;
  readonly finalUrl: string | null;
  /** Storefront origin; relative check URLs resolve against it. */
  readonly baseUrl: string;
  /** Required by `locator_probe`; the page is probed as the agent left it. */
  readonly session?: BrowserSession;
  /** Required by `state_check`. */
  readonly backend?: BackendClient;
  /** Required by `llm_judge` and `fuzzyMatch`. Checks needing it fail without it. */
  readonly judge?: Judge;
  /** PNG of the final page, forwarded to the judge. */
  readonly screenshot?: Buffer;
  readonly signal?: AbortSignal;
}

export interface GradeResult {
  readonly passed: boolean;
  readonly checks: CheckResult[];
  /** Tokens spent by judge calls. */
  readonly usage: Usage;
}

/** Run every check of `input.task`; the episode passes when all of them pass. */
export async function grade(input: GradeInput): Promise<GradeResult> {
  const programmatic = input.task.eval.filter((c) => c.type !== 'llm_judge');
  const judges = input.task.eval.filter((c) => c.type === 'llm_judge');
  const checks: CheckResult[] = [];
  let usage = ZERO_USAGE;

  for (const check of programmatic) {
    const result = await runProgrammatic(check, input);
    if (result.usage !== undefined) usage = addUsage(usage, result.usage);
    checks.push({ check, passed: result.passed, detail: result.detail });
  }
  for (const check of judges) {
    if (check.type !== 'llm_judge') continue;
    const result = await runJudge(check.rubric, input, checks);
    if (result.usage !== undefined) usage = addUsage(usage, result.usage);
    checks.push({ check, passed: result.passed, detail: result.detail });
  }
  return { passed: checks.every((c) => c.passed), checks, usage };
}

type CheckOutcome = MatchResult & { readonly usage?: Usage };

async function runProgrammatic(check: Check, input: GradeInput): Promise<CheckOutcome> {
  switch (check.type) {
    case 'string_match':
      return runStringMatch(check, input);
    case 'url_match':
      if (input.finalUrl === null) return { passed: false, detail: 'no final url' };
      return matchUrl(input.finalUrl, check.url, check.rule, input.baseUrl);
    case 'locator_probe':
      return runLocatorProbe(check, input);
    case 'state_check':
      return runStateCheck(check, input);
    case 'llm_judge':
      throw new Error('llm_judge is not a programmatic check');
  }
}

async function runStringMatch(
  check: Extract<Check, { type: 'string_match' }>,
  input: GradeInput,
): Promise<CheckOutcome> {
  if (input.answer === null) return { passed: false, detail: 'no answer' };
  const literal = matchText(input.answer, check);
  if (!literal.passed || check.fuzzyMatch === undefined) return literal;
  const rubric = `The answer must convey the same information as: "${check.fuzzyMatch}". Wording may differ; facts may not.`;
  return runJudge(rubric, input, []);
}

async function runLocatorProbe(
  check: Extract<Check, { type: 'locator_probe' }>,
  input: GradeInput,
): Promise<CheckOutcome> {
  if (input.session === undefined) return { passed: false, detail: 'no browser session' };
  if (check.url !== 'last') {
    await input.session.page.goto(new URL(check.url, input.baseUrl).toString(), {
      waitUntil: 'domcontentloaded',
    });
  }
  const found = await probe(input.session, check.locator);
  if (found.count === 0) return { passed: false, detail: `"${check.locator}" matched nothing` };
  if (check.required.exactMatch !== undefined) {
    const wanted = check.required.exactMatch.trim();
    if (!found.texts.some((t) => t.trim() === wanted)) {
      return { passed: false, detail: `no element with text exactly "${wanted}"` };
    }
  }
  const combined = matchText(found.texts.join('\n'), { mustInclude: check.required.mustInclude });
  return { passed: combined.passed, detail: `${found.count} match(es); ${combined.detail}` };
}

async function runStateCheck(
  check: Extract<Check, { type: 'state_check' }>,
  input: GradeInput,
): Promise<CheckOutcome> {
  if (input.backend === undefined) return { passed: false, detail: 'no backend client' };
  const snapshot = await input.backend.state();
  const actual = resolvePointer(snapshot, check.path);
  if (actual === undefined) return { passed: false, detail: `nothing at ${check.path}` };
  return matchState(check.match, check.value, actual);
}

async function runJudge(
  rubric: string,
  input: GradeInput,
  priorChecks: readonly CheckResult[],
): Promise<CheckOutcome> {
  if (input.judge === undefined) return { passed: false, detail: 'no judge configured' };
  const verdict = await judge(input.judge.client, input.judge.model, {
    goal: input.task.goal,
    rubric,
    answer: input.answer,
    finalUrl: input.finalUrl,
    priorChecks,
    ...(input.screenshot === undefined ? {} : { screenshot: input.screenshot }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
  return { passed: verdict.passed, detail: verdict.reason, usage: verdict.usage };
}
