/**
 * Contract: search and predictive search against the committed fixture.
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { type ContractServer, startContractServer } from './helpers.js';

let ctx: ContractServer;

beforeAll(async () => {
  ctx = await startContractServer();
});

afterAll(async () => {
  await ctx.server.close();
});

interface SearchData {
  readonly search: {
    readonly totalCount: number;
    readonly nodes: readonly { readonly __typename: string; readonly handle: string }[];
  };
  readonly predictiveSearch: {
    readonly queries: readonly { readonly text: string }[];
    readonly products: readonly { readonly handle: string }[];
  } | null;
}

describe('contract: search', () => {
  it('search(query) returns matching products with totalCount', async () => {
    const result = await ctx.query<SearchData>(/* GraphQL */ `
      {
        search(query: "mushroom", first: 5) {
          totalCount
          nodes { __typename ... on Product { handle } }
        }
        predictiveSearch(query: "mushroom", limit: 3) {
          queries { text }
          products { handle }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      search: {
        totalCount: 1,
        nodes: [{ __typename: 'Product', handle: 'shopliseum-mushroom-dog-toys' }],
      },
      predictiveSearch: {
        queries: [{ text: 'mushroom' }],
        products: [{ handle: 'shopliseum-mushroom-dog-toys' }],
      },
    });
  });

  it('search(query) with no match returns an empty connection', async () => {
    const result = await ctx.query<SearchData>(/* GraphQL */ `
      { search(query: "zzzz-no-such-product", first: 5) { totalCount nodes { __typename } } }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data?.search).toEqual({ totalCount: 0, nodes: [] });
  });
});
