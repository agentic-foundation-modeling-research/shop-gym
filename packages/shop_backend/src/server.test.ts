/**
 * Tests for `createSandboxServer` cart-store isolation (spec T4.5).
 *
 * Boots two server instances against the same fixture dataset on ephemeral
 * ports, then asserts that cart ids minted by server A are unknown to
 * server B — i.e. the per-server `CartStore` replaces the module-level
 * `Map`/counter that mock-api shared across instances.
 *
 * A second test exercises the `close() → listen()` round trip on a single
 * server: the store is cleared on close, so a cart id minted before close
 * does not resolve after the listener is rebound.
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

const CREATE_CART = /* GraphQL */ `mutation { cartCreate(input: {}) { cart { id } } }`;
const lookupCart = (id: string) => /* GraphQL */ `{ cart(id: "${id}") { id } }`;

describe('createSandboxServer — cart-store isolation', () => {
  it('does not share cart ids across two server instances', async () => {
    const data = loadShopData(FIXTURE_DIR);
    // `port: 0` requests an ephemeral port so two instances can listen
    // simultaneously without coordination.
    const serverA = createSandboxServer({ data, port: 0 });
    const serverB = createSandboxServer({ data, port: 0 });
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
    const server = createSandboxServer({ data, port: 0 });
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
