import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { type SandboxSchemaResolvers, createSandboxSchema } from '../schema.js';
import type { ResolverContext } from './index.js';
import { searchResolvers } from './search.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);

const resolvers: SandboxSchemaResolvers = {
  Query: searchResolvers.Query,
  SearchResultItem: searchResolvers.SearchResultItem,
};

const yoga = createYoga({
  schema: createSandboxSchema(resolvers),
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

const NODES_QUERY = /* GraphQL */ `
  query ($q: String!, $types: [SearchType!], $sortKey: SearchSortKeys, $first: Int) {
    search(query: $q, types: $types, sortKey: $sortKey, first: $first) {
      totalCount
      nodes {
        __typename
        ... on Product {
          handle
        }
        ... on Page {
          handle
        }
        ... on Article {
          handle
        }
      }
    }
  }
`;

async function search(variables: {
  readonly q: string;
  readonly types?: readonly string[];
  readonly sortKey?: 'PRICE' | 'RELEVANCE';
  readonly first?: number;
}): Promise<{
  readonly totalCount: number;
  readonly nodes: ReadonlyArray<{ readonly __typename: string; readonly handle: string }>;
}> {
  const response = await yoga.fetch(`${BASE_URL}/graphql`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: NODES_QUERY, variables }),
  });
  const payload = (await response.json()) as {
    readonly data?: {
      readonly search?: {
        readonly totalCount: number;
        readonly nodes: ReadonlyArray<{ readonly __typename: string; readonly handle: string }>;
      };
    };
    readonly errors?: readonly unknown[];
  };
  if (payload.errors !== undefined) {
    throw new Error(`Search query failed: ${JSON.stringify(payload.errors)}`);
  }
  if (payload.data?.search === undefined) {
    throw new Error('Search query returned no data');
  }
  return payload.data.search;
}

describe('searchResolvers — Query.search filtering', () => {
  it('matches products by title', async () => {
    const { totalCount, nodes } = await search({ q: 'tickless' });
    expect(totalCount).toBe(1);
    expect(nodes).toEqual([{ __typename: 'Product', handle: 'tickless-anti-tick-collar' }]);
  });

  it('matches products by description text', async () => {
    // "ultrasonic" appears only in the tickless collar's description_html.
    const { totalCount, nodes } = await search({ q: 'ultrasonic' });
    expect(totalCount).toBe(1);
    expect(nodes).toEqual([{ __typename: 'Product', handle: 'tickless-anti-tick-collar' }]);
  });

  it('matches products by tag', async () => {
    // "stuffed" appears only in the fuzzyard "Stuffed animal" tag —
    // not in the title or description — exercising the tags portion of
    // the product haystack.
    const { totalCount, nodes } = await search({ q: 'stuffed' });
    expect(totalCount).toBe(1);
    expect(nodes).toEqual([{ __typename: 'Product', handle: 'fuzzyard-mushroom-dog-toys' }]);
  });

  it('returns mixed Product + Article results, preserving dataset + insertion order on ties', async () => {
    // "mock" matches every product via vendor "Mock Pet Foods" and the
    // welcome-post article via title "Welcome to Mock Pet Foods". The
    // page title "Our Story" does not match. All scores tie at 1, so the
    // stable RELEVANCE sort preserves products-first / article-last
    // insertion order.
    const result = await search({ q: 'mock' });
    expect(result.totalCount).toBe(6);
    expect(result.nodes).toEqual([
      { __typename: 'Product', handle: 'tickless-anti-tick-collar' },
      { __typename: 'Product', handle: 'fuzzyard-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'applaws-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'bluestem-toothbrush' },
      { __typename: 'Article', handle: 'welcome-post' },
    ]);
  });

  it('returns every item when the query is empty', async () => {
    const { totalCount, nodes } = await search({ q: '' });
    expect(totalCount).toBe(7);
    expect(nodes).toEqual([
      { __typename: 'Product', handle: 'tickless-anti-tick-collar' },
      { __typename: 'Product', handle: 'fuzzyard-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'applaws-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'bluestem-toothbrush' },
      { __typename: 'Page', handle: 'about-us' },
      { __typename: 'Article', handle: 'welcome-post' },
    ]);
  });

  it('honors the types filter — types: [PRODUCT] returns only products', async () => {
    const { totalCount, nodes } = await search({ q: 'mock', types: ['PRODUCT'] });
    expect(totalCount).toBe(5);
    expect(nodes.every((n) => n.__typename === 'Product')).toBe(true);
    expect(nodes).toEqual([
      { __typename: 'Product', handle: 'tickless-anti-tick-collar' },
      { __typename: 'Product', handle: 'fuzzyard-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'applaws-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'bluestem-toothbrush' },
    ]);
  });
});

describe('searchResolvers — Query.search sort + pagination', () => {
  it('sorts by PRICE ascending (min variant price); non-products sink to the end', async () => {
    // Empty query so every dataset item is in scope. Products sort by
    // ascending price (2.49 → 12.99 → 19.99 → 54.99 → 79.99); pages and
    // articles have no price, so they trail the products.
    const { nodes } = await search({ q: '', sortKey: 'PRICE' });
    expect(nodes).toEqual([
      { __typename: 'Product', handle: 'applaws-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'bluestem-toothbrush' },
      { __typename: 'Product', handle: 'fuzzyard-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'tickless-anti-tick-collar' },
      { __typename: 'Page', handle: 'about-us' },
      { __typename: 'Article', handle: 'welcome-post' },
    ]);
  });

  it('paginates with `first` and reports pageInfo.hasNextPage', async () => {
    const result = await run(/* GraphQL */ `
      {
        search(query: "", first: 3) {
          totalCount
          pageInfo {
            hasNextPage
            hasPreviousPage
          }
          nodes {
            __typename
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      search: {
        totalCount: 7,
        pageInfo: { hasNextPage: true, hasPreviousPage: false },
        nodes: [{ __typename: 'Product' }, { __typename: 'Product' }, { __typename: 'Product' }],
      },
    });
  });
});
