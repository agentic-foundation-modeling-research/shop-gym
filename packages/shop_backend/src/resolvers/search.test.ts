import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { afterAll, describe, expect, it } from 'vitest';

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

// ── Query.predictiveSearch ────────────────────────────────────────────────

const PREDICTIVE_QUERY = /* GraphQL */ `
  query (
    $q: String!
    $limit: Int
    $limitScope: PredictiveSearchLimitScope
    $types: [PredictiveSearchType]
  ) {
    predictiveSearch(query: $q, limit: $limit, limitScope: $limitScope, types: $types) {
      products {
        handle
      }
      collections {
        handle
      }
      pages {
        handle
      }
      articles {
        handle
      }
      queries {
        text
        styledText
        trackingParameters
      }
    }
  }
`;

interface PredictiveSearchPayload {
  readonly products: ReadonlyArray<{ readonly handle: string }>;
  readonly collections: ReadonlyArray<{ readonly handle: string }>;
  readonly pages: ReadonlyArray<{ readonly handle: string }>;
  readonly articles: ReadonlyArray<{ readonly handle: string }>;
  readonly queries: ReadonlyArray<{
    readonly text: string;
    readonly styledText: string;
    readonly trackingParameters: string | null;
  }>;
}

async function predictiveSearchOn(
  yogaInstance: ReturnType<typeof createYoga>,
  variables: {
    readonly q: string;
    readonly limit?: number;
    readonly limitScope?: 'EACH' | 'ALL';
    readonly types?: readonly string[];
  },
): Promise<PredictiveSearchPayload> {
  const response = await yogaInstance.fetch(`${BASE_URL}/graphql`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: PREDICTIVE_QUERY, variables }),
  });
  const payload = (await response.json()) as {
    readonly data?: { readonly predictiveSearch?: PredictiveSearchPayload };
    readonly errors?: readonly unknown[];
  };
  if (payload.errors !== undefined) {
    throw new Error(`predictiveSearch query failed: ${JSON.stringify(payload.errors)}`);
  }
  if (payload.data?.predictiveSearch === undefined) {
    throw new Error('predictiveSearch query returned no data');
  }
  return payload.data.predictiveSearch;
}

const predictiveSearch = (variables: {
  readonly q: string;
  readonly limit?: number;
  readonly limitScope?: 'EACH' | 'ALL';
  readonly types?: readonly string[];
}): Promise<PredictiveSearchPayload> => predictiveSearchOn(yoga, variables);

describe('searchResolvers — Query.predictiveSearch', () => {
  it('returns matches across every entity type plus a query suggestion', async () => {
    // "mock" hits every product (vendor "Mock Pet Foods"), the welcome-post
    // article (title), and no pages or collections. Exercises the cross-type
    // fan-out and the suggestion echo.
    const result = await predictiveSearch({ q: 'mock' });
    expect(result.products).toEqual([
      { handle: 'tickless-anti-tick-collar' },
      { handle: 'fuzzyard-mushroom-dog-toys' },
      { handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
      { handle: 'applaws-mackerel-and-sardines-70g' },
      { handle: 'bluestem-toothbrush' },
    ]);
    expect(result.collections).toEqual([]);
    expect(result.pages).toEqual([]);
    expect(result.articles).toEqual([{ handle: 'welcome-post' }]);
    expect(result.queries).toEqual([
      { text: 'mock', styledText: 'mock', trackingParameters: null },
    ]);
  });

  it('matches collections by title — "dog" hits "Dog Essentials"', async () => {
    const result = await predictiveSearch({ q: 'dog', types: ['COLLECTION'] });
    expect(result.collections).toEqual([{ handle: 'dog-essentials' }]);
    expect(result.products).toEqual([]);
    expect(result.queries).toEqual([]);
  });

  it('honors limit per type when limitScope is EACH (default)', async () => {
    // 5 products match "mock"; cap to 2.
    const result = await predictiveSearch({ q: 'mock', limit: 2 });
    expect(result.products).toEqual([
      { handle: 'tickless-anti-tick-collar' },
      { handle: 'fuzzyard-mushroom-dog-toys' },
    ]);
    expect(result.articles).toEqual([{ handle: 'welcome-post' }]);
    expect(result.queries).toHaveLength(1);
  });

  it('honors limit across all types when limitScope is ALL', async () => {
    // "mock" hits 5 products + 1 article. limit=3 across ALL keeps the first
    // 3 products and drops everything else; the suggestion is unaffected.
    const result = await predictiveSearch({ q: 'mock', limit: 3, limitScope: 'ALL' });
    expect(result.products).toEqual([
      { handle: 'tickless-anti-tick-collar' },
      { handle: 'fuzzyard-mushroom-dog-toys' },
      { handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
    ]);
    expect(result.articles).toEqual([]);
    expect(result.queries).toHaveLength(1);
  });

  it('echoes the trimmed term in the SearchQuerySuggestion', async () => {
    const result = await predictiveSearch({ q: '  Tickless  ', types: ['QUERY'] });
    expect(result.queries).toEqual([
      { text: 'Tickless', styledText: 'Tickless', trackingParameters: null },
    ]);
    expect(result.products).toEqual([]);
  });

  it('suppresses the query suggestion when QUERY is omitted from types', async () => {
    const result = await predictiveSearch({ q: 'mock', types: ['PRODUCT'] });
    expect(result.products.length).toBeGreaterThan(0);
    expect(result.queries).toEqual([]);
    expect(result.articles).toEqual([]);
  });

  it('returns empty results for an empty query (no types echoed either)', async () => {
    const result = await predictiveSearch({ q: '   ' });
    expect(result.products).toEqual([]);
    expect(result.collections).toEqual([]);
    expect(result.pages).toEqual([]);
    expect(result.articles).toEqual([]);
    expect(result.queries).toEqual([]);
  });
});

describe('searchResolvers — Query.predictiveSearch with no blogs.json', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sandbox-shop-no-blogs-'));
  fs.cpSync(FIXTURE_DIR, tmpDir, { recursive: true });
  fs.rmSync(path.join(tmpDir, 'blogs.json'));

  const noBlogsData = loadShopData(tmpDir);
  const noBlogsYoga = createYoga({
    schema: createSandboxSchema(resolvers),
    context: (): ResolverContext => ({ data: noBlogsData, baseUrl: BASE_URL }),
  });

  afterAll(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('returns no articles when blogs.json is absent', async () => {
    const result = await predictiveSearchOn(noBlogsYoga, { q: 'mock' });
    expect(result.products.length).toBeGreaterThan(0);
    expect(result.articles).toEqual([]);
    // The suggestion is still emitted — it does not depend on the blogs file.
    expect(result.queries).toEqual([
      { text: 'mock', styledText: 'mock', trackingParameters: null },
    ]);
  });
});
