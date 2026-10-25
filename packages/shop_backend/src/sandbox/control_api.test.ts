/**
 * Episode routing and the control API, exercised over real HTTP through
 * `createSandboxServer`: header-selected isolation, reset / state / delete,
 * and the error codes for malformed ids.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { type SandboxServer, createSandboxServer } from '../server.js';
import { EPISODE_HEADER } from './episode.js';
import { type StateSnapshot, stateSnapshotSchema } from './snapshot.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

interface GraphQLResponse<T> {
  readonly data?: T;
  readonly errors?: readonly unknown[];
}

interface CartCreateData {
  readonly cartCreate: { readonly cart: { readonly id: string } | null };
}
interface CartQueryData {
  readonly cart: { readonly id: string } | null;
}

const CREATE_CART = /* GraphQL */ 'mutation { cartCreate(input: {}) { cart { id } } }';
const lookupCart = (id: string) => /* GraphQL */ `{ cart(id: "${id}") { id } }`;

let server: SandboxServer;
let baseUrl: string;

beforeAll(async () => {
  server = createSandboxServer({ data: loadShopData(FIXTURE_DIR), dataDir: FIXTURE_DIR, port: 0 });
  await server.listen();
  baseUrl = server.url.replace(/\/graphql$/, '');
});

afterAll(async () => {
  await server.close();
});

async function gql<T>(query: string, episode?: string): Promise<GraphQLResponse<T>> {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (episode !== undefined) headers[EPISODE_HEADER] = episode;
  const response = await fetch(server.url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query }),
  });
  return (await response.json()) as GraphQLResponse<T>;
}

async function createCart(episode?: string): Promise<string> {
  const result = await gql<CartCreateData>(CREATE_CART, episode);
  const id = result.data?.cartCreate.cart?.id;
  if (id === undefined) throw new Error('expected a cart id');
  return id;
}

async function cartVisible(id: string, episode?: string): Promise<boolean> {
  const result = await gql<CartQueryData>(lookupCart(id), episode);
  return result.data?.cart !== null;
}

async function control(method: string, suffix: string): Promise<Response> {
  return fetch(`${baseUrl}/__shopgym/episodes/${suffix}`, { method });
}

async function snapshotOf(id: string): Promise<StateSnapshot> {
  const response = await control('GET', `${id}/state`);
  expect(response.status).toBe(200);
  return stateSnapshotSchema.parse(await response.json());
}

describe('episode header routing', () => {
  it('isolates carts between episodes and the default episode', async () => {
    // Ids are deterministic per episode (every episode's first cart is
    // `cart-1`), so compare against episodes that have minted fewer carts.
    await createCart('iso-a');
    const inA = await createCart('iso-a');
    expect(await cartVisible(inA, 'iso-a')).toBe(true);
    expect(await cartVisible(inA, 'iso-b')).toBe(false);
    expect(await cartVisible(inA)).toBe(false);

    const inDefault = await createCart();
    expect(await cartVisible(inDefault)).toBe(true);
    expect(await cartVisible(inDefault, 'default')).toBe(true);
    expect(await cartVisible(inDefault, 'iso-b')).toBe(false);
  });

  it('rejects a malformed episode header with 400 before GraphQL runs', async () => {
    const response = await fetch(server.url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', [EPISODE_HEADER]: 'bad id/with slash' },
      body: JSON.stringify({ query: CREATE_CART }),
    });
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: `invalid ${EPISODE_HEADER} header` });
  });

  it('advertises the episode header in CORS preflight', async () => {
    const response = await fetch(server.url, {
      method: 'OPTIONS',
      headers: {
        origin: 'http://storefront.test',
        'access-control-request-method': 'POST',
        'access-control-request-headers': EPISODE_HEADER,
      },
    });
    expect(response.headers.get('access-control-allow-headers')?.toLowerCase()).toContain(
      EPISODE_HEADER,
    );
  });
});

describe('control API', () => {
  it('GET /state returns a validated snapshot for a fresh episode', async () => {
    const snapshot = await snapshotOf('ctl-fresh');
    expect(snapshot.episodeId).toBe('ctl-fresh');
    expect(snapshot.carts).toEqual([]);
    expect(snapshot.customers).toHaveLength(1);
  });

  it('POST /reset re-seeds the episode and returns the fresh snapshot', async () => {
    const cartId = await createCart('ctl-reset');
    expect((await snapshotOf('ctl-reset')).carts.map((c) => c.id)).toEqual([cartId]);

    const response = await control('POST', 'ctl-reset/reset');
    expect(response.status).toBe(200);
    const snapshot = stateSnapshotSchema.parse(await response.json());
    expect(snapshot.carts).toEqual([]);
    expect(await cartVisible(cartId, 'ctl-reset')).toBe(false);
  });

  it('DELETE forgets the episode: 204 once, then 404', async () => {
    await createCart('ctl-del');
    expect((await control('DELETE', 'ctl-del')).status).toBe(204);
    expect((await control('DELETE', 'ctl-del')).status).toBe(404);
    // The next request re-seeds it.
    expect((await snapshotOf('ctl-del')).carts).toEqual([]);
  });

  it('answers 400 / 404 / 405 for bad ids, unknown paths, and wrong methods', async () => {
    expect((await control('GET', '.hidden/state')).status).toBe(400);
    expect((await fetch(`${baseUrl}/__shopgym/nope`)).status).toBe(404);
    expect((await control('GET', 'ctl-x/reset')).status).toBe(405);
    expect((await control('POST', 'ctl-x/state')).status).toBe(405);
    expect((await control('GET', 'ctl-x')).status).toBe(405);
  });

  it('keeps /health working alongside the control API', async () => {
    const response = await fetch(`${baseUrl}/health`);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok', store: 'Mock Pet Foods' });
  });
});
