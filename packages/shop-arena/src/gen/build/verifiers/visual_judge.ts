/**
 * `visual_judge` verifier: render the task's routes in a real browser and
 * let the model judge each page against the shared rubric. Every page must
 * pass for the task to pass. A per-task retry budget, persisted under
 * `<runDir>/checks/visual_judge_budget.json`, downgrades the verdict to
 * advisory once the task has failed this verifier `retryBudget` times, so a
 * stubborn page cannot consume the whole run.
 *
 * Cart routes are judged with a line in the cart: the verifier adds the
 * first sampled product before capturing, so the model sees the populated
 * state the shopper sees rather than the empty-cart message. Account routes
 * other than the login page are captured after logging in as the first
 * seeded customer, so the profile shows the orders table. Screenshots of
 * the failing pages are returned as `images` so the harness can show them
 * to the next executor iteration.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { LlmClient, ModelRef } from '@shop-gym/agent';
import { BrowserSession } from '@shop-gym/browser';
import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { addToCart, logIn } from './browser_steps.js';
import {
  type PageJudgement,
  capturePage,
  judgeContext,
  judgePage,
  loadJudgeRubric,
  mapConcurrent,
} from './page_judge.js';
import { type StorefrontTarget, prepareTarget, readSeededCustomer } from './storefront_target.js';
import {
  type BucketCaps,
  DEFAULT_CAPS,
  type DatasetHandles,
  bucketsForTask,
  readDatasetHandles,
  routesForBuckets,
  sampleProductHandles,
} from './task_routes.js';

export const VISUAL_JUDGE_NAME = 'visual_judge';
export const VISUAL_RETRY_BUDGET = 3;
export const VISUAL_BUDGET_FILE = path.join('checks', 'visual_judge_budget.json');
const JUDGE_CONCURRENCY = 3;

export interface VisualJudgeOptions {
  readonly target: StorefrontTarget;
  readonly dataDir: string;
  /** Holds `capabilities.json` and `parts/*.md`; omitted means no context. */
  readonly manualDir?: string;
  readonly llm: LlmClient;
  readonly model: ModelRef;
  readonly caps?: BucketCaps;
  readonly retryBudget?: number;
}

export function visualJudgeVerifier(options: VisualJudgeOptions): Verifier {
  const caps = options.caps ?? DEFAULT_CAPS;
  const retryBudget = options.retryBudget ?? VISUAL_RETRY_BUDGET;
  return {
    name: VISUAL_JUDGE_NAME,
    appliesTo: (taskId) => bucketsForTask(taskId).length > 0,
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const blocked = await prepareTarget(options.target);
      if (blocked !== undefined) {
        return blocked;
      }
      const buckets = bucketsForTask(ctx.selectedTaskId);
      const handles = await readDatasetHandles(options.dataDir);
      const routes = routesForBuckets(buckets, handles, caps);
      const [rubric, context] = await Promise.all([
        loadJudgeRubric(),
        judgeContext(options.manualDir, buckets),
      ]);
      const outDir = path.join(ctx.runDir, 'iters', ctx.iterId, 'checks', VISUAL_JUDGE_NAME);
      const session = await BrowserSession.launch({ episodeId: `visual-judge-${ctx.iterId}` });
      const captures: Awaited<ReturnType<typeof capturePage>>[] = [];
      let cartSeed: string | undefined;
      let accountSeed: string | undefined;
      try {
        if (buckets.includes('cart_search')) {
          cartSeed = await seedCart(session, options.target.url, handles, caps);
        }
        for (const route of routes.filter((r) => !needsLogin(r))) {
          captures.push(await capturePage({ session, baseUrl: options.target.url, route, outDir }));
        }
        const memberRoutes = routes.filter(needsLogin);
        if (memberRoutes.length > 0) {
          accountSeed = await seedAccount(session, options.target.url, options.dataDir);
          for (const route of memberRoutes) {
            captures.push(
              await capturePage({ session, baseUrl: options.target.url, route, outDir }),
            );
          }
        }
      } finally {
        await session.close();
      }
      const pages = await mapConcurrent(captures, JUDGE_CONCURRENCY, (capture) =>
        judgePage({ llm: options.llm, model: options.model, rubric, capture, context }),
      );
      const failed = pages.filter((p) => p.effective === 'fail');
      const score =
        pages.length === 0 ? 0 : pages.reduce((sum, p) => sum + p.verdict.score, 0) / pages.length;
      const budget = await consumeBudget(
        ctx.runDir,
        ctx.selectedTaskId,
        retryBudget,
        failed.length > 0,
      );
      const details = {
        buckets,
        score,
        pages: pages.map(pageDetails),
        retryBudget: budget,
        ...(cartSeed === undefined ? {} : { cartSeed }),
        ...(accountSeed === undefined ? {} : { accountSeed }),
      };
      if (failed.length === 0) {
        return { verdict: 'pass', details };
      }
      const feedback = renderFeedback(ctx.selectedTaskId, pages, budget);
      const images = failed.flatMap((p) => p.screenshots.map((s) => s.path));
      return { verdict: budget.exhausted ? 'advisory' : 'fail', feedback, details, images };
    },
  };
}

/** Put the first sampled product in the session's cart; returns what happened. */
async function seedCart(
  session: BrowserSession,
  baseUrl: string,
  handles: DatasetHandles,
  caps: BucketCaps,
): Promise<string> {
  const productHandle = sampleProductHandles(handles, caps)[0];
  if (productHandle === undefined) {
    return 'the dataset has no product to add';
  }
  const outcome = await addToCart(session.page, baseUrl, productHandle);
  return outcome.detail;
}

/** Account routes other than the login page need the seeded customer's session. */
function needsLogin(route: string): boolean {
  return route.startsWith('/account') && route !== '/account/login';
}

/** Log in as the first seeded customer; returns what happened. */
async function seedAccount(
  session: BrowserSession,
  baseUrl: string,
  dataDir: string,
): Promise<string> {
  const customer = await readSeededCustomer(dataDir);
  if (customer === undefined) {
    return 'the dataset has no seeded customer';
  }
  const outcome = await logIn(session.page, baseUrl, customer);
  return outcome.detail;
}

export interface RetryBudgetState {
  readonly budget: number;
  /** Failures recorded for the task before this run. */
  readonly priorFailures: number;
  /** `true` when this failure was downgraded to advisory. */
  readonly exhausted: boolean;
}

/** Read the per-task failure counter; on a failure, record it unless the budget is spent. */
async function consumeBudget(
  runDir: string,
  taskId: string,
  budget: number,
  failed: boolean,
): Promise<RetryBudgetState> {
  const file = path.join(runDir, VISUAL_BUDGET_FILE);
  const raw = await fs.readFile(file, 'utf-8').catch(() => '{}');
  const counts = JSON.parse(raw) as Record<string, number>;
  const priorFailures = counts[taskId] ?? 0;
  if (!failed) {
    return { budget, priorFailures, exhausted: false };
  }
  if (priorFailures >= budget) {
    return { budget, priorFailures, exhausted: true };
  }
  counts[taskId] = priorFailures + 1;
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, `${JSON.stringify(counts, null, 2)}\n`);
  return { budget, priorFailures, exhausted: false };
}

function pageDetails(page: PageJudgement): Record<string, unknown> {
  return {
    route: page.route,
    status: page.status,
    screenshots: page.screenshots,
    effective: page.effective,
    ...page.verdict,
  };
}

function renderFeedback(
  taskId: string,
  pages: readonly PageJudgement[],
  budget: RetryBudgetState,
): string {
  const failed = pages.filter((p) => p.effective === 'fail');
  const lines = [
    `\`visual_judge\`: ${failed.length} of ${pages.length} page(s) for \`${taskId}\` failed.`,
    'Desktop and mobile screenshots of the failing pages are attached to this prompt in the order listed below (the harness caps how many).',
  ];
  if (budget.exhausted) {
    lines.push(
      '',
      `The visual retry budget for this task (${budget.budget}) is spent; this result is advisory. Fix what you can and move on.`,
    );
  }
  for (const page of pages) {
    lines.push(
      '',
      `### \`${page.route}\` - ${page.effective} (score ${page.verdict.score.toFixed(1)})`,
      '',
      page.verdict.feedback.trim(),
    );
    for (const issue of page.verdict.issues) {
      const capability = issue.capability === null ? '' : ` [${issue.capability}]`;
      lines.push(`- ${issue.severity} (${issue.viewport})${capability}: ${issue.summary}`);
    }
  }
  return lines.join('\n');
}
