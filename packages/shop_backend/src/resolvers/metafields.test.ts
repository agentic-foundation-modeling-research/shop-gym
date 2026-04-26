/**
 * Integration tests for the Product / Collection / Shop metafield resolvers
 * (T5.1 + T5.2).
 *
 * Runs the full schema with the combined resolver map so that the SDL,
 * graphql-yoga, and the per-area maps stay in sync — the resolver under
 * test merges into `Product` / `Collection` / `Shop` alongside the existing
 * nested resolvers, so the integration path is the only one worth covering.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { createSandboxSchema } from '../schema.js';
import { CartStore } from './cart.js';
import type { ResolverContext } from './index.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);
const carts = new CartStore();

const yoga = createYoga({
  schema: createSandboxSchema(),
  context: (): ResolverContext => ({ data, carts, baseUrl: BASE_URL }),
});

interface ExecutionResult {
  readonly data?: unknown;
  readonly errors?: readonly unknown[];
}

async function run(source: string): Promise<ExecutionResult> {
  const response = await yoga.fetch(`${BASE_URL}/graphql`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: source }),
  });
  return (await response.json()) as ExecutionResult;
}

describe('metafieldResolvers — Product.metafield', () => {
  it('returns the metafield matching namespace + key', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "go-skin-and-coat-chicken-with-grains-12lb") {
          metafield(namespace: "specs", key: "protein_source") {
            id
            namespace
            key
            value
            type
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        metafield: {
          id: 'gid://shopify/Metafield/80b98489',
          namespace: 'specs',
          key: 'protein_source',
          value: 'chicken',
          type: 'single_line_text_field',
        },
      },
    });
  });

  it('returns null when the metafield is missing', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "go-skin-and-coat-chicken-with-grains-12lb") {
          metafield(namespace: "specs", key: "missing_key") {
            value
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ product: { metafield: null } });
  });

  it('returns null on a product with no metafields', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "tickless-anti-tick-collar") {
          metafield(namespace: "specs", key: "protein_source") {
            value
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ product: { metafield: null } });
  });
});

describe('metafieldResolvers — Product.metafields', () => {
  it('preserves request order and returns null for misses', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "go-skin-and-coat-chicken-with-grains-12lb") {
          metafields(
            identifiers: [
              { namespace: "specs", key: "missing" }
              { namespace: "specs", key: "protein_source" }
              { namespace: "other", key: "protein_source" }
            ]
          ) {
            namespace
            key
            value
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        metafields: [null, { namespace: 'specs', key: 'protein_source', value: 'chicken' }, null],
      },
    });
  });
});

describe('metafieldResolvers — Collection.metafield(s)', () => {
  it('returns the matching collection metafield', async () => {
    const result = await run(/* GraphQL */ `
      {
        collection(handle: "dog-essentials") {
          metafield(namespace: "merch", key: "hero_color") {
            namespace
            key
            value
            type
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      collection: {
        metafield: {
          namespace: 'merch',
          key: 'hero_color',
          value: '#1f513f',
          type: 'color',
        },
      },
    });
  });

  it('returns null on a collection with no metafields', async () => {
    const result = await run(/* GraphQL */ `
      {
        collection(handle: "cat-care") {
          metafield(namespace: "merch", key: "hero_color") {
            value
          }
          metafields(identifiers: [{ namespace: "merch", key: "hero_color" }]) {
            value
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      collection: {
        metafield: null,
        metafields: [null],
      },
    });
  });
});

describe('metafieldResolvers — Shop.metafield(s)', () => {
  it('returns the shop metafield matching namespace + key', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          metafield(namespace: "shop", key: "tagline") {
            namespace
            key
            value
            type
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: {
        metafield: {
          namespace: 'shop',
          key: 'tagline',
          value: 'Quality food for happy pets',
          type: 'single_line_text_field',
        },
      },
    });
  });

  it('returns null when the shop metafield is missing', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          metafield(namespace: "shop", key: "missing") {
            value
          }
          metafields(
            identifiers: [
              { namespace: "shop", key: "missing" }
              { namespace: "shop", key: "tagline" }
            ]
          ) {
            namespace
            key
            value
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: {
        metafield: null,
        metafields: [
          null,
          { namespace: 'shop', key: 'tagline', value: 'Quality food for happy pets' },
        ],
      },
    });
  });
});
