/**
 * `nav_coverage` verifier: every menu target in `navigation.json` resolves
 * to 200 and appears as a link inside the rendered `<header>` or `<footer>`
 * of the homepage. Applies to the tasks that own the site shell.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { StorefrontClient, bodyExcerpt } from './http.js';
import { type StorefrontTarget, prepareTarget } from './storefront_target.js';

export const NAV_COVERAGE_NAME = 'nav_coverage';
const NAV_TASKS = new Set(['gen_navigation', 'gen_theme', 'visual_fix']);

export interface MenuTarget {
  readonly menu: string;
  readonly title: string;
  readonly url: string;
}

export interface MenuTargetCheck extends MenuTarget {
  readonly status: number;
  readonly linked: boolean;
}

export interface NavCoverageOptions {
  readonly target: StorefrontTarget;
  readonly dataDir: string;
}

export function navCoverageVerifier(options: NavCoverageOptions): Verifier {
  return {
    name: NAV_COVERAGE_NAME,
    appliesTo: (taskId) => NAV_TASKS.has(taskId),
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const blocked = await prepareTarget(options.target);
      if (blocked !== undefined) {
        return blocked;
      }
      const targets = await readMenuTargets(options.dataDir);
      const client = new StorefrontClient({
        baseUrl: options.target.url,
        episodeId: `nav-coverage-${ctx.iterId}`,
      });
      const home = await client.get('/');
      if (home.status !== 200) {
        return {
          verdict: 'fail',
          feedback: `\`nav_coverage\`: \`/\` returned ${home.status}; cannot inspect the header and footer.\n  body: ${bodyExcerpt(home.body)}`,
          details: { homeStatus: home.status },
        };
      }
      const shell = shellHtml(home.body);
      if (shell === '') {
        return {
          verdict: 'fail',
          feedback:
            '`nav_coverage`: the homepage renders no `<header>` or `<footer>` element, so no menu can be found.',
          details: { homeStatus: 200, targets },
        };
      }
      const checks: MenuTargetCheck[] = [];
      for (const target of targets) {
        const response = await client.get(target.url);
        checks.push({
          ...target,
          status: response.status,
          linked: shell.includes(`href="${target.url}"`),
        });
      }
      const failures = checks.filter((c) => c.status !== 200 || !c.linked);
      const details = { checks };
      if (failures.length === 0) {
        return { verdict: 'pass', details };
      }
      return { verdict: 'fail', feedback: renderFailures(failures), details };
    },
  };
}

/** Flattened same-origin menu items of every menu in `navigation.json`. */
export async function readMenuTargets(dataDir: string): Promise<MenuTarget[]> {
  const parsed: unknown = JSON.parse(
    await fs.readFile(path.join(dataDir, 'navigation.json'), 'utf-8'),
  );
  const out: MenuTarget[] = [];
  if (typeof parsed !== 'object' || parsed === null) {
    return out;
  }
  for (const [menu, items] of Object.entries(parsed as Record<string, unknown>)) {
    collect(menu, items, out);
  }
  return out;
}

function collect(menu: string, items: unknown, out: MenuTarget[]): void {
  if (!Array.isArray(items)) {
    return;
  }
  for (const item of items) {
    if (typeof item !== 'object' || item === null) {
      continue;
    }
    const { title, url, children } = item as { title?: unknown; url?: unknown; children?: unknown };
    if (typeof url === 'string' && url.startsWith('/')) {
      out.push({ menu, title: typeof title === 'string' ? title : '', url });
    }
    collect(menu, children, out);
  }
}

/** The first `<header>` and `<footer>` elements of a page, concatenated. */
export function shellHtml(html: string): string {
  const header = /<header[\s>][\s\S]*?<\/header>/i.exec(html)?.[0] ?? '';
  const footer = /<footer[\s>][\s\S]*?<\/footer>/i.exec(html)?.[0] ?? '';
  return header + footer;
}

function renderFailures(failures: readonly MenuTargetCheck[]): string {
  const lines = [`\`nav_coverage\`: ${failures.length} menu target(s) are broken or missing.`, ''];
  for (const failure of failures) {
    const problems: string[] = [];
    if (failure.status !== 200) {
      problems.push(`returns ${failure.status}`);
    }
    if (!failure.linked) {
      problems.push('is not linked from the rendered header or footer');
    }
    lines.push(
      `- \`${failure.url}\` (${failure.menu}: ${failure.title}) ${problems.join(' and ')}`,
    );
  }
  return lines.join('\n');
}
