/**
 * SandboxShop server entry point (T6.2).
 *
 * `createSandboxServer({ data, dataDir, port?, host?, baseUrl? })` wires the
 * SDL + resolvers built by `createSandboxSchema()` against a freshly
 * constructed `CartStore` (spec §5.5) and serves the surface defined in
 * spec §5.4 over `node:http`:
 *
 *   - `POST /graphql` — yoga-mounted GraphQL endpoint.
 *   - `POST /api/<version>/graphql.json` — rewritten to `/graphql` for
 *     Storefront-API-versioned clients.
 *   - `GET /images/<path>` — static images under `<dataDir>/images/`.
 *   - `GET /health` — `{ status: "ok", store }` JSON.
 *
 * CORS follows spec §5.4: `Access-Control-Allow-Origin: *`, methods
 * `POST, OPTIONS`, headers `Content-Type, X-Shopify-Storefront-Access-Token`.
 *
 * Each call allocates its own `CartStore`, so concurrent server instances —
 * including parallel test suites — never share cart ids. `close()` shuts
 * the listener down and clears the store, matching the spec's "cleared on
 * `server.close()`" contract.
 */

import { type Server, createServer as createHttpServer } from 'node:http';
import { type CORSOptions, createYoga } from 'graphql-yoga';
import type { SandboxShopData } from './data/types.js';
import { buildHttpHandler } from './http.js';
import { CartStore } from './resolvers/cart.js';
import type { ResolverContext } from './resolvers/index.js';
import { createSandboxSchema } from './schema.js';

/** CORS configuration mandated by spec §5.4. */
const CORS: CORSOptions = {
  origin: '*',
  methods: ['POST', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'X-Shopify-Storefront-Access-Token'],
};

export interface ServerOptions {
  /** Loaded SandboxShop dataset; resolvers read against this snapshot. */
  readonly data: SandboxShopData;
  /**
   * SandboxShop dataset directory. Static images are served from
   * `<dataDir>/images/`. Required so the HTTP wrapper can locate the asset
   * root; the loader in M1 does not retain it on `SandboxShopData`.
   */
  readonly dataDir: string;
  /** TCP port to bind. `0` requests an ephemeral port (used by tests). Defaults to 4000. */
  readonly port?: number;
  /** Host interface to bind. Defaults to `127.0.0.1`. */
  readonly host?: string;
  /**
   * Public origin used to rewrite relative image paths (spec §5.3). When
   * omitted, derived from `host:port` after the listener is bound. Tests can
   * pin this to a stable value.
   */
  readonly baseUrl?: string;
}

/** Handle returned by `createSandboxServer`. */
export interface SandboxServer {
  /** Start the listener. Resolves once the socket is bound. */
  listen(): Promise<void>;
  /** Stop the listener and clear the cart store. Idempotent for a closed server. */
  close(): Promise<void>;
  /** GraphQL endpoint URL, available after `listen()` resolves. */
  readonly url: string;
}

/**
 * Build a SandboxShop server bound to a single dataset snapshot.
 *
 * Each invocation owns a fresh `CartStore`; cart ids minted by one server are
 * unknown to any other. `close()` clears that store so subsequent reads
 * return `null` (spec §5.3).
 */
export function createSandboxServer(options: ServerOptions): SandboxServer {
  const { data, dataDir, port = 4000, host = '127.0.0.1' } = options;
  const carts = new CartStore();
  const schema = createSandboxSchema();

  let resolvedUrl = formatBaseUrl(host, port);
  const baseUrlOverride = options.baseUrl;

  const yoga = createYoga({
    schema,
    graphqlEndpoint: '/graphql',
    cors: CORS,
    context: (): ResolverContext => ({
      data,
      carts,
      baseUrl: baseUrlOverride ?? resolvedUrl,
    }),
  });

  const handler = buildHttpHandler({
    yoga,
    dataDir,
    storeName: data.store.name,
  });

  const http: Server = createHttpServer(handler);

  return {
    listen: () =>
      new Promise<void>((resolve, reject) => {
        const onError = (err: Error): void => reject(err);
        http.once('error', onError);
        http.listen(port, host, () => {
          http.removeListener('error', onError);
          const address = http.address();
          if (address !== null && typeof address === 'object') {
            resolvedUrl = formatBaseUrl(host, address.port);
          }
          resolve();
        });
      }),
    close: () =>
      new Promise<void>((resolve, reject) => {
        carts.clear();
        if (!http.listening) {
          resolve();
          return;
        }
        http.close((err) => (err ? reject(err) : resolve()));
      }),
    get url(): string {
      const base = baseUrlOverride ?? resolvedUrl;
      return `${base}/graphql`;
    },
  };
}

function formatBaseUrl(host: string, port: number): string {
  return `http://${host}:${port}`;
}
