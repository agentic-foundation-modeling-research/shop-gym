import * as http from 'node:http';
import type { AddressInfo } from 'node:net';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { IterationBrowser } from './browser.js';

const HOME = '<!doctype html><html><head><title>Home</title></head><body>Home</body></html>';

let server: http.Server;
let baseUrl = '';
const requested: string[] = [];

beforeAll(async () => {
  server = http.createServer((req, res) => {
    requested.push(req.url ?? '');
    switch (req.url) {
      case '/':
        return res.writeHead(200, { 'content-type': 'text/html' }).end(HOME);
      case '/cart.js':
        return res
          .writeHead(200, { 'content-type': 'application/json' })
          .end(JSON.stringify({ items: [{ variant_id: 7, quantity: 2, title: 'Mug' }] }));
      case '/blocked-cart.js':
        return res.writeHead(503).end();
      case '/page-cart.js':
        return res.writeHead(200, { 'content-type': 'text/html' }).end(HOME);
      default:
        return res.writeHead(404).end();
    }
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

/** A URL on a port that nothing listens on. */
async function closedUrl(path: string): Promise<string> {
  const closed = http.createServer();
  await new Promise<void>((resolve) => closed.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${(closed.address() as AddressInfo).port}${path}`;
  await new Promise<void>((resolve) => closed.close(() => resolve()));
  return url;
}

describe('IterationBrowser.start', { timeout: 30_000 }, () => {
  it('records the start URL and the cart lines', async () => {
    const browser = await IterationBrowser.launch({
      episodeId: 'iteration-browser',
      startUrl: `${baseUrl}/`,
      cartUrl: `${baseUrl}/cart.js`,
    });
    try {
      expect(await browser.start()).toEqual({
        url: `${baseUrl}/`,
        cart: { items: [{ variant_id: 7, quantity: 2 }] },
        error: null,
      });
    } finally {
      await browser.close();
    }
  });

  it('records no cart and sends no cart request when the shop has no cart URL', async () => {
    requested.length = 0;
    const browser = await IterationBrowser.launch({
      episodeId: 'iteration-browser',
      startUrl: `${baseUrl}/`,
    });
    try {
      expect(await browser.start()).toEqual({ url: `${baseUrl}/`, cart: null, error: null });
    } finally {
      await browser.close();
    }
    expect(requested).not.toContain('/cart.js');
  });

  it.each([
    ['/blocked-cart.js', 'returned HTTP 503'],
    ['/page-cart.js', 'did not return a cart'],
  ])('records why the cart at %s could not be read', async (cartPath, reason) => {
    const browser = await IterationBrowser.launch({
      episodeId: 'iteration-browser',
      startUrl: `${baseUrl}/`,
      cartUrl: `${baseUrl}${cartPath}`,
    });
    try {
      expect(await browser.start()).toEqual({
        url: `${baseUrl}/`,
        cart: null,
        error: `${baseUrl}${cartPath} ${reason}`,
      });
    } finally {
      await browser.close();
    }
  });

  it('records why the cart request failed', async () => {
    const cartUrl = await closedUrl('/cart.js');
    const browser = await IterationBrowser.launch({
      episodeId: 'iteration-browser',
      startUrl: `${baseUrl}/`,
      cartUrl,
    });
    try {
      const start = await browser.start();
      expect(start.cart).toBeNull();
      expect(start.error?.startsWith(`${cartUrl} did not load: `)).toBe(true);
      expect(start.error).toContain('ECONNREFUSED');
    } finally {
      await browser.close();
    }
  });

  it('records why the start URL did not load', async () => {
    const browser = await IterationBrowser.launch({
      episodeId: 'iteration-browser',
      startUrl: await closedUrl('/'),
      cartUrl: `${baseUrl}/cart.js`,
    });
    try {
      const start = await browser.start();
      expect(start.cart).toBeNull();
      expect(start.error).toContain('ERR_CONNECTION_REFUSED');
    } finally {
      await browser.close();
    }
  });
});
