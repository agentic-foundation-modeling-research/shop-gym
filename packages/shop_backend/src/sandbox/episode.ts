/**
 * Episode selection header shared by the GraphQL and control-API layers.
 *
 * Every request may carry `x-shopgym-episode: <id>`; absence selects the
 * `default` episode. Ids are restricted to a URL-safe alphabet so they can be
 * echoed verbatim in control-API paths.
 */

import type { IncomingHttpHeaders } from 'node:http';
import { DEFAULT_EPISODE_ID } from '../state/episodes.js';

export { DEFAULT_EPISODE_ID } from '../state/episodes.js';

/** Request header that selects the episode branch. */
export const EPISODE_HEADER = 'x-shopgym-episode';

const EPISODE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** Whether `id` is an acceptable episode id (1-64 chars of `[A-Za-z0-9._-]`, no leading punctuation). */
export function isValidEpisodeId(id: string): boolean {
  return EPISODE_ID_RE.test(id);
}

/**
 * Episode id named by `headers`, `DEFAULT_EPISODE_ID` when the header is
 * absent, or `null` when the header value is malformed.
 */
export function episodeIdFromHeaders(headers: Headers | IncomingHttpHeaders): string | null {
  // Duck-type: yoga hands out a ponyfilled `Headers`, not the global class.
  const raw = isHeaders(headers) ? headers.get(EPISODE_HEADER) : headers[EPISODE_HEADER];
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined || value === null) return DEFAULT_EPISODE_ID;
  return isValidEpisodeId(value) ? value : null;
}

function isHeaders(headers: Headers | IncomingHttpHeaders): headers is Headers {
  return typeof (headers as Headers).get === 'function';
}
