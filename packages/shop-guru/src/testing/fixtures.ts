/**
 * Test scaffolding: the committed sandbox fixture, an in-process backend,
 * and a tiny storefront stand-in served by node:http.
 */

import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  type SandboxServer,
  type SandboxShopData,
  createSandboxServer,
  loadShopData,
} from '@shop-gym/shop-backend';

export const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../shop_backend/tests/fixtures/sandbox_shop_v0',
);

export function loadFixture(): SandboxShopData {
  return loadShopData(FIXTURE_DIR);
}

export interface Backend {
  readonly server: SandboxServer;
  readonly url: string;
  readonly data: SandboxShopData;
}

/** Boot `shop-backend` on the fixture at an ephemeral port. */
export async function startBackend(): Promise<Backend> {
  const data = loadFixture();
  const server = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
  await server.listen();
  return { server, url: server.url, data };
}

export interface SeenRequest {
  readonly method: string;
  readonly path: string;
  readonly episode: string | undefined;
  readonly cookie: string | undefined;
  readonly body: string;
}

export interface FakeStorefront {
  readonly url: string;
  readonly seen: SeenRequest[];
  close(): Promise<void>;
}

const LOGIN_COOKIE = '__shop_gym_session=fake-session; Path=/; HttpOnly';

/**
 * Serves `pages` by path, accepts `POST /cart` (listing added variant gids
 * on `/cart`) and `POST /account/login` (302 + cookie for `password123`),
 * and records every request.
 */
export async function startFakeStorefront(
  pages: Readonly<Record<string, string>>,
): Promise<FakeStorefront> {
  const seen: SeenRequest[] = [];
  const cartLines: string[] = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk: Buffer) => {
      body += chunk.toString();
    });
    req.on('end', () => {
      const url = new URL(req.url ?? '/', 'http://127.0.0.1');
      const episode = req.headers['x-shopgym-episode'];
      seen.push({
        method: req.method ?? 'GET',
        path: url.pathname,
        episode: Array.isArray(episode) ? episode[0] : episode,
        cookie: req.headers.cookie,
        body,
      });
      const form = new URLSearchParams(body);
      if (req.method === 'POST' && url.pathname === '/cart') {
        cartLines.push(`${form.get('merchandiseId')} x${form.get('quantity')}`);
        res.writeHead(302, { location: '/cart' });
        res.end();
        return;
      }
      if (req.method === 'POST' && url.pathname === '/account/login') {
        if (form.get('password') === 'password123') {
          res.writeHead(302, { location: '/account', 'set-cookie': LOGIN_COOKIE });
        } else {
          res.writeHead(200, { 'content-type': 'text/html' });
        }
        res.end('<p>Invalid credentials</p>');
        return;
      }
      const page = pages[url.pathname];
      if (page === undefined) {
        res.writeHead(404, { 'content-type': 'text/html' });
        res.end('<h1>Not found</h1>');
        return;
      }
      res.writeHead(200, { 'content-type': 'text/html' });
      res.end(
        page.replace('{{cart_lines}}', cartLines.map((l) => `<li class="line">${l}</li>`).join('')),
      );
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    seen,
    close: () =>
      new Promise<void>((resolve, reject) => server.close((e) => (e ? reject(e) : resolve()))),
  };
}

/** Pages for the fake storefront used across the browser-driven tests. */
export const SHOP_PAGES: Readonly<Record<string, string>> = {
  '/': `<!doctype html><html><head><title>Fixture Shop</title></head><body>
<h1>Fixture Shop</h1><nav><a href="/cart">Cart</a> <a href="/collections/dog-essentials">Dogs</a></nav>
</body></html>`,
  '/cart': `<!doctype html><html><head><title>Cart</title></head><body>
<h1>Your cart</h1><ul id="lines">{{cart_lines}}</ul><p class="total">Total: $29.98</p>
</body></html>`,
  '/collections/dog-essentials': `<!doctype html><html><head><title>Dog Essentials</title></head><body>
<h1>Dog Essentials</h1><div class="product"><span class="title">AisleArena Anti Tick Collar</span></div>
<div class="product"><span class="title">Shopliseum Mushroom Dog Toys</span></div>
</body></html>`,
  '/account':
    '<!doctype html><html><body><h1>Account</h1><p>jane.doe@example.com</p></body></html>',
};
