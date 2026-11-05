/**
 * Local HTTP server for the review reports.
 *
 *   - `GET /` -> the index of every report, newest first.
 *   - `GET /<YYYY-MM-DD-slug>.html` -> that report inside the site shell.
 *   - `GET /assets/<name>` -> a shared asset (stylesheet, theme script).
 *
 * Files are read on each request, so an edited report shows on reload. Paths
 * are matched against strict patterns before any file access, so a request
 * cannot reach a file outside the two directories.
 */

import * as fs from 'node:fs/promises';
import {
  type IncomingMessage,
  type Server,
  type ServerResponse,
  createServer as createHttpServer,
} from 'node:http';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { listReports, readReport } from './catalog.js';
import { renderIndexPage, renderNotFoundPage, renderReportPage } from './shell.js';

/** The committed reports: `pages/` in this package. */
export const PAGES_DIR = fileURLToPath(new URL('../pages/', import.meta.url));
/** The shared stylesheet and scripts: `assets/` in this package. */
export const ASSETS_DIR = fileURLToPath(new URL('../assets/', import.meta.url));
export const DEFAULT_PORT = 4100;
export const DEFAULT_HOST = '127.0.0.1';

const ASSET_PATH_RE = /^\/assets\/([a-z0-9][a-z0-9._-]*)$/i;
const HTML_TYPE = 'text/html; charset=utf-8';
/** Extensions are matched case-insensitively. */
const ASSET_TYPES: Readonly<Record<string, string>> = {
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
};

/** Options accepted by `createReportServer`. */
export interface ReportServerOptions {
  /** Directory of report files. Defaults to `PAGES_DIR`. */
  readonly pagesDir?: string;
  /** Directory of shared assets. Defaults to `ASSETS_DIR`. */
  readonly assetsDir?: string;
  /** TCP port to bind; `0` picks a free port. Defaults to `DEFAULT_PORT`. */
  readonly port?: number;
  /** Interface to bind. Defaults to `DEFAULT_HOST`. */
  readonly host?: string;
}

/** Handle returned by `createReportServer`. */
export interface ReportServer {
  /** Start the listener. Resolves once the socket is bound. */
  listen(): Promise<void>;
  /** Stop the listener and drop open connections. Safe to call on a closed server. */
  close(): Promise<void>;
  /** Base URL, with the bound port once `listen()` resolves. */
  readonly url: string;
}

/** Build the reports server. Nothing is bound until `listen()`. */
export function createReportServer(options: ReportServerOptions = {}): ReportServer {
  const pagesDir = options.pagesDir ?? PAGES_DIR;
  const assetsDir = options.assetsDir ?? ASSETS_DIR;
  const host = options.host ?? DEFAULT_HOST;
  let port = options.port ?? DEFAULT_PORT;

  const http: Server = createHttpServer((req, res) => {
    handle(req, res, pagesDir, assetsDir).catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      send(res, 500, 'text/plain; charset=utf-8', `${message}\n`);
    });
  });

  return {
    listen: () =>
      new Promise<void>((resolve, reject) => {
        const onError = (error: Error): void => reject(error);
        http.once('error', onError);
        http.listen(port, host, () => {
          http.removeListener('error', onError);
          const address = http.address();
          if (address !== null && typeof address === 'object') {
            port = address.port;
          }
          resolve();
        });
      }),
    close: () =>
      new Promise<void>((resolve, reject) => {
        if (!http.listening) {
          resolve();
          return;
        }
        http.close((error) => (error ? reject(error) : resolve()));
        http.closeAllConnections();
      }),
    get url(): string {
      return `http://${host.includes(':') ? `[${host}]` : host}:${port}`;
    },
  };
}

async function handle(
  req: IncomingMessage,
  res: ServerResponse,
  pagesDir: string,
  assetsDir: string,
): Promise<void> {
  if (req.method !== 'GET') {
    res.setHeader('allow', 'GET');
    send(res, 405, 'text/plain; charset=utf-8', 'Method not allowed\n');
    return;
  }
  const { pathname } = new URL(req.url ?? '/', 'http://localhost');
  if (pathname === '/') {
    send(res, 200, HTML_TYPE, renderIndexPage(await listReports(pagesDir)));
    return;
  }
  // A report file name has no "/", so this cannot leave `pagesDir`.
  const report = await readReport(pagesDir, pathname.slice(1));
  if (report !== undefined) {
    send(res, 200, HTML_TYPE, renderReportPage(report));
    return;
  }
  const assetName = ASSET_PATH_RE.exec(pathname)?.[1];
  const assetType = ASSET_TYPES[path.extname(assetName ?? '').toLowerCase()];
  if (assetName !== undefined && assetType !== undefined) {
    const asset = await readIfExists(path.join(assetsDir, assetName));
    if (asset !== undefined) {
      send(res, 200, assetType, asset);
      return;
    }
  }
  send(res, 404, HTML_TYPE, renderNotFoundPage(pathname));
}

async function readIfExists(file: string): Promise<Buffer | undefined> {
  try {
    return await fs.readFile(file);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return undefined;
    }
    throw error;
  }
}

function send(res: ServerResponse, status: number, type: string, body: string | Buffer): void {
  res.writeHead(status, {
    'content-type': type,
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  });
  res.end(body);
}
