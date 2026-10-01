/**
 * Aria snapshots with stable element refs.
 *
 * Playwright's AI snapshot mode (`page.ariaSnapshot({mode: 'ai'})`) renders
 * the accessibility tree as YAML and tags each element with `[ref=eN]`.
 * The same page object resolves those refs through the built-in
 * `aria-ref=eN` selector engine, which is the mechanism Playwright MCP
 * uses. Refs (`e12`, or `f3e12` after navigations) stay valid until the
 * next snapshot re-tags changed elements.
 */

import type { Locator, Page } from 'playwright';

/** URL, title, and the ref-tagged aria tree of a page. */
export interface PageSnapshot {
  readonly url: string;
  readonly title: string;
  readonly aria: string;
}

/** `e12`, or `f3e12` once the page lives in a re-created frame. */
const REF_PATTERN = /^(?:f\d+)?e\d+$/;

/** Captures the page's URL, title, and ref-tagged aria snapshot. */
export async function snapshotPage(page: Page): Promise<PageSnapshot> {
  const [title, aria] = await Promise.all([page.title(), page.ariaSnapshot({ mode: 'ai' })]);
  return { url: page.url(), title, aria };
}

/** `URL:` and `Title:` lines for the page, the short summary tools return after acting. */
export async function pageSummary(page: Page): Promise<string> {
  return `URL: ${page.url()}\nTitle: ${await page.title()}`;
}

/** Renders a snapshot as the text shown to the model. */
export function formatSnapshot(snapshot: PageSnapshot): string {
  return `URL: ${snapshot.url}\nTitle: ${snapshot.title}\n\n\`\`\`yaml\n${snapshot.aria}\n\`\`\``;
}

/**
 * Resolves a ref from the latest snapshot to a locator.
 *
 * Raises: `Error` if `ref` is malformed or no element in the latest snapshot
 * carries it (for example after the page changed), so callers never wait
 * out an action timeout on a stale ref.
 */
export async function refLocator(page: Page, ref: string): Promise<Locator> {
  if (!REF_PATTERN.test(ref)) {
    throw new Error(`Invalid ref "${ref}": expected a ref like e12 from the latest snapshot.`);
  }
  const locator = page.locator(`aria-ref=${ref}`);
  if ((await locator.count()) === 0) {
    throw new Error(`Ref ${ref} is not in the latest snapshot. Call snapshot to get fresh refs.`);
  }
  return locator;
}
