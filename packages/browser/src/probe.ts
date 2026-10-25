/**
 * Read-only DOM probe for graders and task validation.
 */

import type { BrowserSession } from './session.js';

/** What a Playwright selector matched on the session's page. */
export interface ProbeResult {
  readonly count: number;
  /** `innerText` of each match, in document order. */
  readonly texts: readonly string[];
  /** Whether the first match is visible. `false` when nothing matched. */
  readonly visible: boolean;
}

/**
 * Evaluates a Playwright selector (CSS, `text=`, `role=`, ...) on the current page.
 *
 * Does not wait: it reports the page as it is when called.
 */
export async function probe(session: BrowserSession, locator: string): Promise<ProbeResult> {
  const matches = session.page.locator(locator);
  const count = await matches.count();
  const texts = await matches.allInnerTexts();
  const visible = count > 0 && (await matches.first().isVisible());
  return { count, texts, visible };
}
