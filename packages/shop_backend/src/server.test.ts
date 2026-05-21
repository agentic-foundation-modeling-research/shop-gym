/**
 * Tests for `createSandboxServer` (T6.2 + T4.5).
 *
 * Two areas under test:
 *   1. Wrapper wiring (T6.2). The server boots against an ephemeral port and
 *      resolves the canonical `{ shop { name } }` query against both
 *      `/graphql` and `/api/2024-01/graphql.json`. Satisfies SC2 + SC4.
 *   2. Cart-store isolation (T4.5). Cart ids minted by server A are unknown
 *      to server B; the store is cleared on `close()` and a cart id minted
 *      before close does not resolve after the listener is rebound.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { loadShopData } from './data/loader.js';
import { createSandboxServer } from './server.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../tests/fixtures/sandbox_shop_v0',
);

interface GraphQLResponse<T> {
  readonly data?: T;
  readonly errors?: readonly unknown[];
}

async function gql<T>(url: string, query: string): Promise<GraphQLResponse<T>> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  return (await response.json()) as GraphQLResponse<T>;
}

interface CartCreateData {
  readonly cartCreate: { readonly cart: { readonly id: string } | null };
}

interface CartQueryData {
  readonly cart: { readonly id: string } | null;
}

interface ShopQueryData {
  readonly shop: { readonly name: string };
}

const CREATE_CART = /* GraphQL */ 'mutation { cartCreate(input: {}) { cart { id } } }';
const SHOP_QUERY = /* GraphQL */ '{ shop { name } }';
const lookupCart = (id: string) => /* GraphQL */ `{ cart(id: "${id}") { id } }`;

describe('createSandboxServer — HTTP wiring', () => {
  it('serves { shop { name } } at /graphql and the versioned /api/<v>/graphql.json', async () => {
    const data = loadShopData(FIXTURE_DIR);
    const server = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
    await server.listen();
    try {
      const baseUrl = server.url.replace(/\/graphql$/, '');
      const direct = await gql<ShopQueryData>(server.url, SHOP_QUERY);
      expect(direct.errors).toBeUndefined();
      expect(direct.data?.shop.name).toBe(data.store.name);

      const versioned = await gql<ShopQueryData>(`${baseUrl}/api/2024-01/graphql.json`, SHOP_QUERY);
      expect(versioned.errors).toBeUndefined();
      expect(versioned.data?.shop.name).toBe(data.store.name);
    } finally {
      await server.close();
    }
  });

  it('responds to GET /health with the dataset store name', async () => {
    const data = loadShopData(FIXTURE_DIR);
    const server = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
    await server.listen();
    try {
      const baseUrl = server.url.replace(/\/graphql$/, '');
      const response = await fetch(`${baseUrl}/health`);
      expect(response.status).toBe(200);
      const body = (await response.json()) as { status: string; store: string };
      expect(body).toEqual({ status: 'ok', store: data.store.name });
    } finally {
      await server.close();
    }
  });
});

describe('createSandboxServer — @inContext enforcement (T7.3)', () => {
  it('rejects @inContext with a country the dataset does not serve', async () => {
    const data = loadShopData(FIXTURE_DIR);
    const server = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
    await server.listen();
    try {
      const result = await gql<ShopQueryData>(
        server.url,
        /* GraphQL */ 'query Q @inContext(country: GB) { shop { name } }',
      );
      expect(result.data).toBeUndefined();
      expect(result.errors).toBeDefined();
      const errors = result.errors as ReadonlyArray<{
        extensions?: { code?: string };
      }>;
      expect(errors[0]?.extensions?.code).toBe('UNSUPPORTED_LOCALE');
    } finally {
      await server.close();
    }
  });
});

describe('createSandboxServer — cart-store isolation', () => {
  it('does not share cart ids across two server instances', async () => {
    const data = loadShopData(FIXTURE_DIR);
    // `port: 0` requests an ephemeral port so two instances can listen
    // simultaneously without coordination.
    const serverA = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
    const serverB = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
    try {
      await Promise.all([serverA.listen(), serverB.listen()]);

      const created = await gql<CartCreateData>(serverA.url, CREATE_CART);
      const cartId = created.data?.cartCreate.cart?.id;
      expect(cartId).toBeDefined();

      const seenOnA = await gql<CartQueryData>(serverA.url, lookupCart(cartId as string));
      expect(seenOnA.data?.cart?.id).toBe(cartId);

      const seenOnB = await gql<CartQueryData>(serverB.url, lookupCart(cartId as string));
      expect(seenOnB.data?.cart).toBeNull();
    } finally {
      await Promise.all([serverA.close(), serverB.close()]);
    }
  });

  it('clears its cart store on close()', async () => {
    const data = loadShopData(FIXTURE_DIR);
    const server = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
    await server.listen();

    const created = await gql<CartCreateData>(server.url, CREATE_CART);
    const cartId = created.data?.cartCreate.cart?.id;
    expect(cartId).toBeDefined();

    await server.close();
    await server.listen();
    try {
      const lookup = await gql<CartQueryData>(server.url, lookupCart(cartId as string));
      expect(lookup.data?.cart).toBeNull();
    } finally {
      await server.close();
    }
  });
});
