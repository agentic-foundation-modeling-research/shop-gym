/**
 * Final evaluation of a built shop: a visual sweep over its canonical pages
 * and a scripted functional sweep, both against an already-running
 * storefront and backend. Writes `report.json`, `summary.md`,
 * `pages/<name>.json` and `screenshots/` under `outDir`.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { LlmClient, ModelRef } from '@shop-gym/agent';
import { BrowserSession } from '@shop-gym/browser';

import { readApplicableDiscountCode } from '../build/verifiers/storefront_target.js';
import {
  SWEEP_CAPS,
  readDatasetHandles,
  sampleProductHandles,
} from '../build/verifiers/task_routes.js';
import { type FunctionalStep, runFunctionalSweep } from './functional_sweep.js';
import { type VisualPageResult, runVisualSweep } from './visual_sweep.js';

export const FINAL_EVAL_REPORT = 'report.json';
export const FINAL_EVAL_SUMMARY = 'summary.md';

export interface FinalEvalOptions {
  /** Sandbox shop data directory (`collections.json`, `products.json`, ...). */
  readonly dataDir: string;
  /** Shop manual directory (`capabilities.json`, `parts/*.md`); optional context for the judge. */
  readonly manualDir?: string;
  readonly backendUrl: string;
  readonly storefrontUrl: string;
  readonly llm: LlmClient;
  readonly model: ModelRef;
  /** Report directory, normally `<runDir>/final_eval`. */
  readonly outDir: string;
  readonly log?: (line: string) => void;
  readonly signal?: AbortSignal;
  /** Test seam: launch the browser headed. */
  readonly headless?: boolean;
}

export interface VisualPageReport {
  readonly name: string;
  readonly route: string;
  readonly bucket: string;
  readonly status: 'pass' | 'fail' | 'skipped';
  readonly httpStatus: number | null;
  readonly score: number | null;
  readonly screenshots: readonly { readonly viewport: string; readonly path: string }[];
  readonly issues: readonly unknown[];
  readonly feedback: string;
  readonly reason?: string;
}

export interface SweepCounts {
  readonly passed: number;
  readonly failed: number;
  readonly skipped: number;
}

export interface FinalEvalReport extends SweepCounts {
  readonly generatedAt: string;
  readonly storefrontUrl: string;
  readonly backendUrl: string;
  readonly model: ModelRef;
  readonly visual: SweepCounts & { readonly pages: readonly VisualPageReport[] };
  readonly functional: SweepCounts & { readonly steps: readonly FunctionalStep[] };
}

export interface FinalEvalResult extends SweepCounts {
  readonly reportPath: string;
  readonly report: FinalEvalReport;
}

export async function runFinalEval(options: FinalEvalOptions): Promise<FinalEvalResult> {
  const log = options.log ?? (() => {});
  const screenshotsDir = path.join(options.outDir, 'screenshots');
  const pagesDir = path.join(options.outDir, 'pages');
  await fs.mkdir(screenshotsDir, { recursive: true });
  await fs.mkdir(pagesDir, { recursive: true });
  const handles = await readDatasetHandles(options.dataDir);
  const productHandle = sampleProductHandles(handles, SWEEP_CAPS)[0];
  const discountCode = await readApplicableDiscountCode(options.dataDir);

  const visual = await withSession(options, 'final-eval-visual', (session) =>
    runVisualSweep({
      session,
      storefrontUrl: options.storefrontUrl,
      dataDir: options.dataDir,
      ...(options.manualDir !== undefined ? { manualDir: options.manualDir } : {}),
      handles,
      llm: options.llm,
      model: options.model,
      screenshotsDir,
      ...(options.signal !== undefined ? { signal: options.signal } : {}),
      log,
    }),
  );
  log('final_eval: running the functional sweep');
  const steps = await withSession(options, 'final-eval-functional', (session) =>
    runFunctionalSweep({
      session,
      storefrontUrl: options.storefrontUrl,
      productHandle,
      discountCode,
    }),
  );

  const pages = visual.map((page) => pageReport(page, options.outDir));
  const visualCounts = count(pages.map((page) => page.status));
  const functionalCounts = count(steps.map((step) => step.status));
  const report: FinalEvalReport = {
    generatedAt: new Date().toISOString(),
    storefrontUrl: options.storefrontUrl,
    backendUrl: options.backendUrl,
    model: options.model,
    visual: { ...visualCounts, pages },
    functional: { ...functionalCounts, steps },
    passed: visualCounts.passed + functionalCounts.passed,
    failed: visualCounts.failed + functionalCounts.failed,
    skipped: visualCounts.skipped + functionalCounts.skipped,
  };
  for (const page of visual) {
    await fs.writeFile(
      path.join(pagesDir, `${page.name}.json`),
      `${JSON.stringify(page, null, 2)}\n`,
    );
  }
  const reportPath = path.join(options.outDir, FINAL_EVAL_REPORT);
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  await fs.writeFile(path.join(options.outDir, FINAL_EVAL_SUMMARY), renderSummary(report));
  log(
    `final_eval: ${report.passed} passed, ${report.failed} failed, ${report.skipped} skipped -> ${reportPath}`,
  );
  return {
    ...count([...pages.map((p) => p.status), ...steps.map((s) => s.status)]),
    reportPath,
    report,
  };
}

async function withSession<T>(
  options: FinalEvalOptions,
  episodeId: string,
  run: (session: BrowserSession) => Promise<T>,
): Promise<T> {
  const session = await BrowserSession.launch({
    episodeId: `${episodeId}-${Date.now()}`,
    ...(options.headless !== undefined ? { headless: options.headless } : {}),
  });
  try {
    return await run(session);
  } finally {
    await session.close();
  }
}

function pageReport(page: VisualPageResult, outDir: string): VisualPageReport {
  if (page.status === 'skipped') {
    return {
      name: page.name,
      route: page.route,
      bucket: page.bucket,
      status: 'skipped',
      httpStatus: null,
      score: null,
      screenshots: [],
      issues: [],
      feedback: '',
      reason: page.reason,
    };
  }
  const { judgement } = page;
  return {
    name: page.name,
    route: page.route,
    bucket: page.bucket,
    status: page.status,
    httpStatus: judgement.status,
    score: judgement.verdict.score,
    screenshots: judgement.screenshots.map((shot) => ({
      viewport: shot.viewport,
      path: path.relative(outDir, shot.path),
    })),
    issues: judgement.verdict.issues,
    feedback: judgement.verdict.feedback,
  };
}

function count(statuses: readonly ('pass' | 'fail' | 'skipped')[]): SweepCounts {
  return {
    passed: statuses.filter((status) => status === 'pass').length,
    failed: statuses.filter((status) => status === 'fail').length,
    skipped: statuses.filter((status) => status === 'skipped').length,
  };
}

export function renderSummary(report: FinalEvalReport): string {
  const lines = [
    '# Final eval',
    '',
    `Storefront: ${report.storefrontUrl}`,
    `Generated: ${report.generatedAt}`,
    '',
    `**${report.passed} passed, ${report.failed} failed, ${report.skipped} skipped**`,
    '',
    '## Visual',
    '',
    '| Page | Route | Status | Score |',
    '| --- | --- | --- | --- |',
    ...report.visual.pages.map(
      (page) =>
        `| ${page.name} | ${page.route} | ${page.status}${page.reason ? ` (${page.reason})` : ''} | ${page.score ?? '-'} |`,
    ),
    '',
    '## Functional',
    '',
    '| Step | Status | Detail |',
    '| --- | --- | --- |',
    ...report.functional.steps.map((step) => `| ${step.name} | ${step.status} | ${step.detail} |`),
    '',
  ];
  return lines.join('\n');
}
