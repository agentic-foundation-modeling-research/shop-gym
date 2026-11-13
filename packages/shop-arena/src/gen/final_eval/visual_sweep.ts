/**
 * The visual sweep: the canonical pages of a shop (`walkShopPages`, which
 * includes the open cart drawer when the storefront has one), captured in
 * one browser episode and judged with the build loop's rubric. A page whose
 * state the dataset or the storefront cannot give is recorded as skipped.
 */

import type { LlmClient, ModelRef } from '@shop-gym/agent';
import type { BrowserSession } from '@shop-gym/browser';

import {
  type PageCapture,
  type PageJudgement,
  capturePage,
  judgeContext,
  judgePage,
  loadJudgeRubric,
  mapConcurrent,
} from '../build/verifiers/page_judge.js';
import {
  type CanonicalPage,
  type SkippedPage,
  walkShopPages,
} from '../build/verifiers/shop_pages.js';
import type { DatasetHandles } from '../build/verifiers/task_routes.js';

const JUDGE_CONCURRENCY = 3;

export interface JudgedPage extends CanonicalPage {
  readonly status: 'pass' | 'fail';
  readonly judgement: PageJudgement;
}

export type VisualPageResult = SkippedPage | JudgedPage;

export interface VisualSweepOptions {
  readonly session: BrowserSession;
  readonly storefrontUrl: string;
  readonly dataDir: string;
  readonly manualDir?: string;
  readonly handles: DatasetHandles;
  readonly llm: LlmClient;
  readonly model: ModelRef;
  readonly screenshotsDir: string;
  readonly signal?: AbortSignal;
  readonly log: (line: string) => void;
}

/** Capture every canonical page, then judge them with bounded concurrency. */
export async function runVisualSweep(options: VisualSweepOptions): Promise<VisualPageResult[]> {
  const { session, storefrontUrl, handles } = options;
  const rubric = await loadJudgeRubric();
  const captures: { page: CanonicalPage; capture: PageCapture }[] = [];
  const capture = async (page: CanonicalPage): Promise<void> => {
    options.signal?.throwIfAborted();
    options.log(`final_eval: capturing ${page.name} ${page.route}`);
    captures.push({
      page,
      capture: await capturePage({
        session,
        baseUrl: storefrontUrl,
        route: page.route,
        outDir: options.screenshotsDir,
        slug: page.name,
      }),
    });
  };

  const skipped = await walkShopPages({
    session,
    baseUrl: storefrontUrl,
    dataDir: options.dataDir,
    handles,
    orderEmail: 'visual.sweep@example.com',
    visit: capture,
  });

  const judged = await mapConcurrent(
    captures,
    JUDGE_CONCURRENCY,
    async ({ page, capture: shot }) => {
      options.signal?.throwIfAborted();
      const context = await judgeContext(options.manualDir, [page.bucket]);
      const judgement = await judgePage({
        llm: options.llm,
        model: options.model,
        rubric,
        capture: shot,
        context,
        ...(options.signal !== undefined ? { signal: options.signal } : {}),
      });
      options.log(
        `final_eval: ${page.name} ${judgement.effective} (score ${judgement.verdict.score})`,
      );
      return { ...page, status: judgement.effective, judgement } satisfies JudgedPage;
    },
  );
  return [...judged, ...skipped];
}
