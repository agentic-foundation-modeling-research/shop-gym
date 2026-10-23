/**
 * Re-checks an explorer proposal on a fresh browser so a task only enters
 * the benchmark when its page-level checks hold independently of the
 * explorer's session.
 */

import * as fs from 'node:fs/promises';

import { BrowserSession, probe } from '@shop-gym/browser';
import type { Task } from '@shop-gym/core';

import { matchText } from '../grade/matchers.js';
import type { Proposal } from './propose.js';

export interface VerifyOptions {
  readonly baseUrl: string;
  readonly episodeId: string;
  /** Where to save a screenshot of `verifyUrl`. */
  readonly screenshotPath: string;
  readonly headless?: boolean;
}

export interface Verification {
  readonly ok: boolean;
  readonly reasons: string[];
  /** Evidence recorded on the accepted task. */
  readonly evidence: Record<string, unknown>;
}

async function pageOk(session: BrowserSession, url: string): Promise<boolean> {
  const response = await session.page.goto(url, { waitUntil: 'domcontentloaded' });
  return response?.ok() ?? false;
}

/**
 * Visit each `url_match` target (must answer 2xx) and each `locator_probe`
 * page (selector must match and satisfy `required`), recording what was seen.
 */
export async function verifyProposal(
  proposal: Proposal,
  options: VerifyOptions,
): Promise<Verification> {
  const session = await BrowserSession.launch({
    episodeId: options.episodeId,
    baseUrl: options.baseUrl,
    headless: options.headless ?? true,
  });
  const reasons: string[] = [];
  const probes: Record<string, unknown>[] = [];
  try {
    for (const check of proposal.task.eval) {
      if (check.type === 'url_match' && check.rule !== 'contains') {
        const url = new URL(check.url, options.baseUrl).toString();
        if (!(await pageOk(session, url))) reasons.push(`url_match: ${check.url} is not reachable`);
      }
      if (check.type === 'locator_probe') {
        const page = check.url === 'last' ? proposal.verifyUrl : check.url;
        const url = new URL(page, options.baseUrl).toString();
        if (!(await pageOk(session, url))) {
          reasons.push(`locator_probe: ${page} is not reachable`);
          continue;
        }
        const found = await probe(session, check.locator);
        const combined = matchText(found.texts.join('\n'), {
          mustInclude: check.required.mustInclude,
        });
        const exact =
          check.required.exactMatch === undefined ||
          found.texts.some((t) => t.trim() === check.required.exactMatch?.trim());
        probes.push({ url: page, locator: check.locator, count: found.count, texts: found.texts });
        if (found.count === 0)
          reasons.push(`locator_probe: "${check.locator}" matched nothing on ${page}`);
        else if (!combined.passed || !exact)
          reasons.push(`locator_probe: ${combined.detail} on ${page}`);
      }
    }
    const verifyUrl = new URL(proposal.verifyUrl, options.baseUrl).toString();
    await session.page.goto(verifyUrl, { waitUntil: 'domcontentloaded' });
    await fs.writeFile(options.screenshotPath, await session.page.screenshot());
  } finally {
    await session.close();
  }
  return {
    ok: reasons.length === 0,
    reasons,
    evidence: { url: proposal.verifyUrl, probes, screenshotPath: options.screenshotPath },
  };
}

/** The accepted task with verification evidence attached. */
export function withEvidence(task: Task, evidence: Record<string, unknown>): Task {
  return { ...task, evidence: { ...(task.evidence ?? {}), ...evidence } };
}
