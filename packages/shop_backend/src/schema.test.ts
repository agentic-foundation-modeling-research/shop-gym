import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { GraphQLObjectType } from 'graphql';
import { createYoga } from 'graphql-yoga';
import { describe, expect, it } from 'vitest';

import { loadShopData } from './data/loader.js';
import type { ResolverContext } from './resolvers/index.js';
import { createSandboxSchema } from './schema.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

describe('createSandboxSchema', () => {
  it('builds a non-null GraphQLSchema with the storefront Query surface', () => {
    const schema = createSandboxSchema();
    expect(schema).not.toBeNull();

    const queryType = schema.getQueryType();
    expect(queryType).toBeDefined();

    // Query.shop is the canonical sentinel for the storefront subset.
    const fields = (queryType as GraphQLObjectType).getFields();
    expect(fields.shop).toBeDefined();
    expect(String(fields.shop?.type)).toBe('Shop!');

    // A handful of other top-level queries should also be wired.
    for (const name of [
      'product',
      'products',
      'collection',
      'collections',
      'menu',
      'page',
      'blog',
      'blogs',
      'search',
      'predictiveSearch',
      'productRecommendations',
      'localization',
      'cart',
    ]) {
      expect(fields[name], `Query.${name} missing`).toBeDefined();
    }
  });

  it('exposes the cart mutations from the v0.1 surface', () => {
    const schema = createSandboxSchema();
    const mutationType = schema.getMutationType();
    expect(mutationType).toBeDefined();

    const fields = (mutationType as GraphQLObjectType).getFields();
    for (const name of [
      'cartCreate',
      'cartLinesAdd',
      'cartLinesUpdate',
      'cartLinesRemove',
      'cartDiscountCodesUpdate',
      'cartBuyerIdentityUpdate',
      'cartNoteUpdate',
      'cartAttributesUpdate',
      'cartGiftCardCodesUpdate',
    ]) {
      expect(fields[name], `Mutation.${name} missing`).toBeDefined();
    }
  });
});

describe('createSandboxSchema — combined resolvers', () => {
  // Drive queries through yoga so the schema, executor, and `graphql` instance
  // all come from a single realm — vitest otherwise hits the dual-package
  // (CJS/ESM) hazard when calling `graphql()` directly on a yoga-built schema.
  const data = loadShopData(FIXTURE_DIR);
  const yoga = createYoga({
    schema: createSandboxSchema(),
    context: (): ResolverContext => ({ data, baseUrl: BASE_URL }),
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

  it('answers a multi-area query (shop + products + collection.products)', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          name
        }
        products(first: 2) {
          nodes {
            handle
          }
        }
        collection(handle: "dog-essentials") {
          handle
          products(first: 1) {
            nodes {
              handle
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: { name: 'Mock Pet Foods' },
      products: {
        nodes: [{ handle: 'tickless-anti-tick-collar' }, { handle: 'fuzzyard-mushroom-dog-toys' }],
      },
      collection: {
        handle: 'dog-essentials',
        products: {
          nodes: [{ handle: 'fuzzyard-mushroom-dog-toys' }],
        },
      },
    });
  });
});
