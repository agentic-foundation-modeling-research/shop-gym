import * as http from 'node:http';
import type { AddressInfo } from 'node:net';

import type { ToolContent, ToolContext } from '@shop-gym/agent';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { IterationBrowser } from './browser.js';

const HOME = '<!doctype html><html><head><title>Home</title></head><body>Home</body></html>';
/** How many links the long page has; its accessibility tree is over 100,000 characters. */
const LONG_ITEMS = 1200;
const LONG = `<!doctype html><html><head><title>Long</title></head><body>${Array.from(
  { length: LONG_ITEMS },
  (_, i) => `<p><a href="#item-${i}">Item ${i}</a></p>`,
).join('')}</body></html>`;

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
      case '/long':
        return res.writeHead(200, { 'content-type': 'text/html' }).end(LONG);
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
      baseUrl,
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
      baseUrl,
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
      baseUrl,
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
      baseUrl,
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
      baseUrl,
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

/** Runs one of the browser's tools and returns its text. */
async function call(
  browser: IterationBrowser,
  name: string,
  params: Record<string, unknown> = {},
): Promise<string> {
  const tool = browser.tools.find((candidate) => candidate.name === name);
  if (tool === undefined) throw new Error(`no tool ${name}`);
  const ctx: ToolContext = { cwd: '.', callId: 'call-1', signal: new AbortController().signal };
  const { content } = await tool.execute(params, ctx);
  return content
    .filter((c): c is Extract<ToolContent, { type: 'text' }> => c.type === 'text')
    .map((c) => c.text)
    .join('\n');
}

/** The accessibility tree inside the YAML block of a snapshot result. */
function tree(snapshot: string): string {
  return /```yaml\n([\s\S]*)\n```/.exec(snapshot)?.[1] ?? '';
}

/** Takes snapshots from offset 0 until the note of a part gives no next offset. */
async function snapshotParts(browser: IterationBrowser): Promise<string[]> {
  const parts: string[] = [];
  let offset: number | undefined = 0;
  while (offset !== undefined) {
    const snapshot = await call(browser, 'snapshot', offset === 0 ? {} : { offset });
    parts.push(snapshot);
    const next = /call snapshot with offset (\d+)/.exec(snapshot)?.[1];
    offset = next === undefined ? undefined : Number(next);
  }
  return parts;
}

describe('IterationBrowser snapshot', { timeout: 30_000 }, () => {
  const launch = () =>
    IterationBrowser.launch({ episodeId: 'iteration-browser', baseUrl, startUrl: `${baseUrl}/` });

  it('shows a short page whole, with no note', async () => {
    const browser = await launch();
    try {
      await browser.start();
      const snapshot = await call(browser, 'snapshot');
      expect(snapshot.startsWith(`URL: ${baseUrl}/\nTitle: Home\n\n\`\`\`yaml\n`)).toBe(true);
      expect(snapshot.endsWith('\n```')).toBe(true);
    } finally {
      await browser.close();
    }
  });

  it('shows a long page in parts of at most 50,000 characters that offset pages through', async () => {
    const browser = await launch();
    let parts: string[];
    try {
      await browser.start();
      await call(browser, 'navigate', { url: '/long' });
      parts = await snapshotParts(browser);
    } finally {
      await browser.close();
    }

    expect(parts.length).toBeGreaterThan(2);
    for (const part of parts) {
      expect(part.startsWith(`URL: ${baseUrl}/long\nTitle: Long\n`)).toBe(true);
    }
    for (const part of parts.slice(0, -1)) {
      expect(part).toContain('[Snapshot cut:');
      expect(tree(part).length).toBeLessThanOrEqual(50_000);
    }
    expect(parts.at(-1)).toContain('[Last part of the snapshot:');
    // Every link shows once, in page order, and no line is split between parts.
    const links = parts.flatMap((part) =>
      [...tree(part).matchAll(/^ {2}- paragraph \[ref=\w+\]:\n {4}- link "Item (\d+)"/gm)].map(
        (match) => Number(match[1]),
      ),
    );
    expect(links).toEqual(Array.from({ length: LONG_ITEMS }, (_, i) => i));
  });

  it('keeps the refs of an earlier part valid after a later part', async () => {
    const browser = await launch();
    try {
      await browser.start();
      await call(browser, 'navigate', { url: '/long' });
      const [first] = await snapshotParts(browser);
      const ref = /link "Item 0" \[ref=(\w+)\]/.exec(first ?? '')?.[1] ?? 'missing';
      expect(await call(browser, 'click', { ref })).toContain(`URL: ${baseUrl}/long#item-0`);
    } finally {
      await browser.close();
    }
  });
});
