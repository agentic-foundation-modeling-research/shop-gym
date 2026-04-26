/**
 * Tests for `buildHttpHandler` (T6.1).
 *
 * Each spec'd behavior gets its own request fixture: `/health`, an image
 * fetch (hit and miss), the `/api/<version>/graphql.json` rewrite, and
 * the yoga fall-through for arbitrary paths. The wrapped GraphQL
 * handler is stubbed so the test surface stays focused on the HTTP
 * routing layer.
 */

import { type Server, createServer as createHttpServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import { type GraphQLRequestHandler, buildHttpHandler } from './http.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../tests/fixtures/sandbox_shop_v0',
);

interface ProbeArgs {
  readonly yoga: GraphQLRequestHandler;
  readonly dataDir?: string;
  readonly storeName?: string;
}

interface Probe {
  readonly url: string;
  close(): Promise<void>;
}

/** Boot a node:http server bound to the wrapper on an ephemeral port. */
async function startProbe(args: ProbeArgs): Promise<Probe> {
  const handler = buildHttpHandler({
    yoga: args.yoga,
    dataDir: args.dataDir ?? FIXTURE_DIR,
    storeName: args.storeName ?? 'Mock Pet Foods',
  });
  const server: Server = createHttpServer(handler);
  await new Promise<void>((resolve, reject) => {
    const onError = (err: Error): void => reject(err);
    server.once('error', onError);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', onError);
      resolve();
    });
  });
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}`,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((err) => (err ? reject(err) : resolve()));
      }),
  };
}

describe('buildHttpHandler', () => {
  describe('GET /health', () => {
    let probe: Probe;
    const yoga = vi.fn<GraphQLRequestHandler>();

    beforeAll(async () => {
      probe = await startProbe({ yoga, storeName: 'Mock Pet Foods' });
    });
    afterAll(async () => {
      await probe.close();
    });

    it('returns 200 with the store name from options', async () => {
      const response = await fetch(`${probe.url}/health`);
      expect(response.status).toBe(200);
      expect(response.headers.get('content-type')).toMatch(/application\/json/);
      const body = (await response.json()) as { status: string; store: string };
      expect(body).toEqual({ status: 'ok', store: 'Mock Pet Foods' });
      expect(yoga).not.toHaveBeenCalled();
    });

    it('ignores a trailing query string', async () => {
      const response = await fetch(`${probe.url}/health?probe=1`);
      expect(response.status).toBe(200);
      const body = (await response.json()) as { status: string };
      expect(body.status).toBe('ok');
    });
  });

  describe('GET /images/<path>', () => {
    let probe: Probe;
    const yoga = vi.fn<GraphQLRequestHandler>();

    beforeAll(async () => {
      probe = await startProbe({ yoga });
    });
    afterAll(async () => {
      await probe.close();
    });

    it('serves a PNG with spec MIME + cache headers', async () => {
      const response = await fetch(`${probe.url}/images/pixel.png`);
      expect(response.status).toBe(200);
      expect(response.headers.get('content-type')).toBe('image/png');
      expect(response.headers.get('cache-control')).toBe('public, max-age=31536000');
      expect(response.headers.get('access-control-allow-origin')).toBe('*');
      const body = await response.arrayBuffer();
      // Smallest valid PNG fixture is 67 bytes; verify the magic header.
      expect(body.byteLength).toBeGreaterThan(0);
      const magic = new Uint8Array(body.slice(0, 8));
      expect(Array.from(magic)).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
      expect(yoga).not.toHaveBeenCalled();
    });

    it('strips the query string before resolving the file', async () => {
      const response = await fetch(`${probe.url}/images/pixel.png?width=100&crop=center`);
      expect(response.status).toBe(200);
      expect(response.headers.get('content-type')).toBe('image/png');
    });

    it('returns 404 for a missing file', async () => {
      const response = await fetch(`${probe.url}/images/does-not-exist.png`);
      expect(response.status).toBe(404);
    });

    it('returns 404 for an unsupported extension', async () => {
      const response = await fetch(`${probe.url}/images/pixel.gif`);
      expect(response.status).toBe(404);
    });

    it('refuses path traversal attempts', async () => {
      const response = await fetch(`${probe.url}/images/..%2F..%2Fstore.json`);
      expect(response.status).toBe(404);
    });
  });

  describe('GET /images/<path> when <dataDir>/images is missing', () => {
    let probe: Probe;
    let tmpDir: string;
    const yoga = vi.fn<GraphQLRequestHandler>();

    beforeAll(async () => {
      // A directory that exists but has no `images/` subdir.
      tmpDir = path.dirname(FIXTURE_DIR);
      probe = await startProbe({ yoga, dataDir: tmpDir });
    });
    afterAll(async () => {
      await probe.close();
    });

    it('returns 404 instead of falling through to yoga', async () => {
      const response = await fetch(`${probe.url}/images/anything.png`);
      expect(response.status).toBe(404);
      expect(yoga).not.toHaveBeenCalled();
    });
  });

  describe('versioned GraphQL rewrite', () => {
    let probe: Probe;
    let observedUrl: string | undefined;
    const yoga: GraphQLRequestHandler = (req, res) => {
      observedUrl = req.url;
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    };

    beforeAll(async () => {
      probe = await startProbe({ yoga });
    });
    afterAll(async () => {
      await probe.close();
    });

    it('rewrites /api/<version>/graphql.json to /graphql before forwarding', async () => {
      const response = await fetch(`${probe.url}/api/2024-01/graphql.json`, { method: 'POST' });
      expect(response.status).toBe(200);
      expect(observedUrl).toBe('/graphql');
    });

    it('preserves the query string when rewriting', async () => {
      const response = await fetch(`${probe.url}/api/2024-01/graphql.json?op=foo`, {
        method: 'POST',
      });
      expect(response.status).toBe(200);
      expect(observedUrl).toBe('/graphql?op=foo');
    });
  });

  describe('fall-through to yoga', () => {
    let probe: Probe;
    let observedUrl: string | undefined;
    const yoga: GraphQLRequestHandler = (req, res) => {
      observedUrl = req.url;
      res.writeHead(204);
      res.end();
    };

    beforeAll(async () => {
      probe = await startProbe({ yoga });
    });
    afterAll(async () => {
      await probe.close();
    });

    it('forwards arbitrary URLs unchanged', async () => {
      const response = await fetch(`${probe.url}/graphql`, { method: 'POST' });
      expect(response.status).toBe(204);
      expect(observedUrl).toBe('/graphql');
    });

    it('does not rewrite a non-versioned path that mentions graphql.json', async () => {
      const response = await fetch(`${probe.url}/something/graphql.json`, { method: 'POST' });
      expect(response.status).toBe(204);
      expect(observedUrl).toBe('/something/graphql.json');
    });
  });
});
