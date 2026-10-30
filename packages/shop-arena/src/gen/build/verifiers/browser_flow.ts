/**
 * What the browser flow verifiers share: run a fixed list of browser steps
 * (from `browser_steps.ts`) in one fresh browser episode against the served
 * storefront, stop at the first failure since later steps depend on it,
 * and turn the record into a verdict. The feedback names the step that
 * broke and lists every step that ran, so the executor sees where the
 * shopper got stuck.
 */

import { BrowserSession } from '@shop-gym/browser';
import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import type { StepOutcome } from './browser_steps.js';
import { type StorefrontTarget, prepareTarget } from './storefront_target.js';

type Page = BrowserSession['page'];

/** One step of a flow: run it on the episode's page, or skip it with a reason. */
export type FlowStep =
  | { readonly name: string; readonly run: (page: Page) => Promise<StepOutcome> }
  | { readonly name: string; readonly skip: string };

export interface FlowStepRecord {
  readonly name: string;
  readonly status: 'pass' | 'fail' | 'skipped';
  readonly detail: string;
  /** Final page path and query, when the step navigated. */
  readonly url?: string;
}

export interface BrowserFlowOptions {
  /** Verifier name; also names the episode and the feedback. */
  readonly name: string;
  /** What the flow covers, for the feedback, e.g. `account flow`. */
  readonly flow: string;
  readonly tasks: ReadonlySet<string>;
  readonly target: StorefrontTarget;
  /** The steps of one run, in order. */
  readonly steps: () => Promise<readonly FlowStep[]>;
}

export function browserFlowVerifier(options: BrowserFlowOptions): Verifier {
  return {
    name: options.name,
    appliesTo: (taskId) => options.tasks.has(taskId),
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const blocked = await prepareTarget(options.target);
      if (blocked !== undefined) {
        return blocked;
      }
      const steps = await options.steps();
      const episodeId = `${options.name.replaceAll('_', '-')}-${ctx.iterId}-${Date.now()}`;
      const records = await runSteps(episodeId, steps);
      const details = { episodeId, steps: records };
      const failed = records.find((record) => record.status === 'fail');
      if (failed === undefined) {
        return { verdict: 'pass', details };
      }
      const lines = [
        `\`${options.name}\`: the ${options.flow} broke at step \`${failed.name}\`.`,
        '',
      ];
      for (const record of records) {
        const mark = { pass: 'ok', fail: 'FAIL', skipped: 'skipped' }[record.status];
        const where = record.url === undefined ? '' : ` (${record.url})`;
        lines.push(`- ${mark} ${record.name}: ${record.detail}${where}`);
      }
      return { verdict: 'fail', feedback: lines.join('\n'), details };
    },
  };
}

/** Run `steps` in a fresh episode until one fails. */
async function runSteps(episodeId: string, steps: readonly FlowStep[]): Promise<FlowStepRecord[]> {
  const session = await BrowserSession.launch({ episodeId });
  const records: FlowStepRecord[] = [];
  try {
    for (const step of steps) {
      if ('skip' in step) {
        records.push({ name: step.name, status: 'skipped', detail: step.skip });
        continue;
      }
      const outcome = await step.run(session.page);
      records.push({
        name: step.name,
        status: outcome.ok ? 'pass' : 'fail',
        detail: outcome.detail,
        ...(outcome.url === undefined ? {} : { url: outcome.url }),
      });
      if (!outcome.ok) {
        break;
      }
    }
  } finally {
    await session.close();
  }
  return records;
}
