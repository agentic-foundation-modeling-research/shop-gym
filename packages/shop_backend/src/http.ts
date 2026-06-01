/**
 * HTTP wrapper for the SandboxShop server (T6.1, spec §5.4).
 *
 * Layers four non-GraphQL behaviors on top of a wrapped graphql-yoga
 * handler:
 *
 *   1. `GET /health` → 200 JSON `{ status: 'ok', store }`.
 *   2. `GET /images/<path>` → static file under `<dataDir>/images/` with
 *      the spec MIME map and immutable cache headers. The query string
 *      is stripped before filesystem lookup (Hydrogen appends
 *      `?width=&height=&crop=`). 404 if the file or `<dataDir>/images/`
 *      directory is missing.
 *   3. `POST /api/<version>/graphql.json` → `req.url` rewritten to
 *      `/graphql` (preserving any query string) before the request is
 *      forwarded to yoga. Compatibility shim for versioned Storefront
 *      API clients.
 *   4. Everything else → forwarded unchanged to the wrapped yoga
 *      handler.
 *
 * `createSandboxServer` (T6.2) composes this wrapper on top of the
 * `createYoga` instance, so the GraphQL behavior tested elsewhere stays
 * untouched.
 */

import { type Stats, createReadStream } from 'node:fs';
import { stat as statPath } from 'node:fs/promises';
import type { IncomingMessage, ServerResponse } from 'node:http';
import * as path from 'node:path';

/** Spec §5.4 MIME map. Extensions are matched case-insensitively. */
const MIME_TYPES: Readonly<Record<string, string>> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
};

const IMAGE_PREFIX = '/images/';
const HEALTH_PATH = '/health';
const VERSIONED_GRAPHQL_RE = /^\/api\/[^/]+\/graphql\.json(?:\?.*)?$/;
const IMMUTABLE_CACHE = 'public, max-age=31536000';

/**
 * Request-handler shape the wrapper expects for the GraphQL fallthrough.
 * `createYoga(...)` returns a `ServerAdapter`, which is callable as
 * `(req, res) => Promise<void>` under Node's HTTP server. We accept the
 * narrower shape here so the wrapper has no implicit dependency on the
 * full yoga generic surface.
 */
export type GraphQLRequestHandler = (
  req: IncomingMessage,
  res: ServerResponse,
) => undefined | Promise<unknown>;

/** Options accepted by `buildHttpHandler`. */
export interface HttpHandlerOptions {
  /** Wrapped GraphQL handler — typically the result of `createYoga(...)`. */
  readonly yoga: GraphQLRequestHandler;
  /**
   * SandboxShop dataset directory. Static images are served from
   * `<dataDir>/images/`. If that directory is absent every image request
   * returns 404.
   */
  readonly dataDir: string;
  /** Echoed in `/health` responses as `{ store: <name> }`. */
  readonly storeName: string;
}

/**
 * Build the SandboxShop HTTP request handler.
 *
 * The returned function is suitable as the listener for
 * `node:http.createServer`. See module docstring for routed behaviors.
 */
export function buildHttpHandler(
  options: HttpHandlerOptions,
): (req: IncomingMessage, res: ServerResponse) => void {
  const { yoga, dataDir, storeName } = options;
  const imagesRoot = path.resolve(dataDir, 'images');

  return (req, res) => {
    const url = req.url ?? '/';
    const method = req.method ?? 'GET';
    const queryStart = url.indexOf('?');
    const pathname = queryStart >= 0 ? url.slice(0, queryStart) : url;

    if (method === 'GET' && pathname === HEALTH_PATH) {
      respondHealth(res, storeName);
      return;
    }

    if (method === 'GET' && pathname.startsWith(IMAGE_PREFIX)) {
      const relPath = pathname.slice(IMAGE_PREFIX.length);
      void serveImage(res, imagesRoot, relPath);
      return;
    }

    if (VERSIONED_GRAPHQL_RE.test(url)) {
      const query = queryStart >= 0 ? url.slice(queryStart) : '';
      req.url = `/graphql${query}`;
    }

    void yoga(req, res);
  };
}

function respondHealth(res: ServerResponse, storeName: string): void {
  const body = JSON.stringify({ status: 'ok', store: storeName });
  res.writeHead(200, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

async function serveImage(res: ServerResponse, imagesRoot: string, relPath: string): Promise<void> {
  let decoded: string;
  try {
    decoded = decodeURIComponent(relPath);
  } catch {
    notFound(res);
    return;
  }

  const ext = path.extname(decoded).toLowerCase();
  const mime = MIME_TYPES[ext];
  if (mime === undefined) {
    notFound(res);
    return;
  }

  const resolved = path.resolve(imagesRoot, decoded);
  // Guard against `..` traversal: the resolved path must descend from
  // `imagesRoot`. We allow equality so a request that resolves exactly
  // to the root still falls through to the `stat`/`isFile` check, which
  // will return 404 because directories are not served.
  const rootWithSep = imagesRoot.endsWith(path.sep) ? imagesRoot : imagesRoot + path.sep;
  if (resolved !== imagesRoot && !resolved.startsWith(rootWithSep)) {
    notFound(res);
    return;
  }

  let stats: Stats;
  try {
    stats = await statPath(resolved);
  } catch {
    notFound(res);
    return;
  }
  if (!stats.isFile()) {
    notFound(res);
    return;
  }

  res.writeHead(200, {
    'content-type': mime,
    'content-length': stats.size,
    'cache-control': IMMUTABLE_CACHE,
    'access-control-allow-origin': '*',
  });
  createReadStream(resolved).pipe(res);
}

function notFound(res: ServerResponse): void {
  res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
  res.end('not found');
}
