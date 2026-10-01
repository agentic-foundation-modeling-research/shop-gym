/**
 * Control API for episode lifecycle, served next to GraphQL:
 *
 *   POST   /__shopgym/episodes/<id>/reset   re-seed the episode  -> 200 StateSnapshot
 *   GET    /__shopgym/episodes/<id>/state   current StateSnapshot -> 200 StateSnapshot
 *   DELETE /__shopgym/episodes/<id>         forget the episode   -> 204 / 404
 *
 * `<id>` must satisfy `isValidEpisodeId`; otherwise 400. Any other method on
 * a matching path is 405. Paths outside `/__shopgym/` are not handled.
 */

import type { ServerResponse } from 'node:http';
import type { HttpRoute } from '../http.js';
import type { EpisodeStore } from '../state/episodes.js';
import { isValidEpisodeId } from './episode.js';
import { exportSnapshot } from './snapshot.js';

const CONTROL_PREFIX = '/__shopgym/';
const EPISODE_ROUTE = /^\/__shopgym\/episodes\/([^/]+)(?:\/(reset|state))?$/;

/** Build the control-API route over `episodes`. */
export function createControlApi(episodes: EpisodeStore): HttpRoute {
  return (req, res) => {
    const url = req.url ?? '/';
    const queryStart = url.indexOf('?');
    const pathname = queryStart >= 0 ? url.slice(0, queryStart) : url;
    if (!pathname.startsWith(CONTROL_PREFIX)) return false;

    const match = EPISODE_ROUTE.exec(pathname);
    if (match === null) {
      sendJson(res, 404, { error: 'not found' });
      return true;
    }
    const id = decodeURIComponent(match[1] ?? '');
    const action = match[2];
    if (!isValidEpisodeId(id)) {
      sendJson(res, 400, { error: `invalid episode id '${id}'` });
      return true;
    }
    const method = req.method ?? 'GET';

    if (action === 'reset' && method === 'POST') {
      sendJson(res, 200, exportSnapshot(episodes.reset(id)));
    } else if (action === 'state' && method === 'GET') {
      sendJson(res, 200, exportSnapshot(episodes.get(id)));
    } else if (action === undefined && method === 'DELETE') {
      if (episodes.delete(id)) {
        res.writeHead(204);
        res.end();
      } else {
        sendJson(res, 404, { error: `unknown episode '${id}'` });
      }
    } else {
      sendJson(res, 405, { error: `${method} not allowed on ${pathname}` });
    }
    return true;
  };
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(text),
    'access-control-allow-origin': '*',
  });
  res.end(text);
}
