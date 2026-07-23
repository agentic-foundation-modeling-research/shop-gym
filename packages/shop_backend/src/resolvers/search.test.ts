import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { afterAll, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import type { Product, SandboxShopData, Store } from '../data/types.js';
import { type SandboxSchemaResolvers, createSandboxSchema } from '../schema.js';
import { CartStore } from './cart.js';
import type { ResolverContext } from './index.js';
import { searchResolvers } from './search.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);
const carts = new CartStore();

const resolvers: SandboxSchemaResolvers = {
  Query: searchResolvers.Query,
  SearchResultItem: searchResolvers.SearchResultItem,
};

const yoga = createYoga({
  schema: createSandboxSchema(resolvers),
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
    const { totalCount, nodes } = await search({ q: 'aislearena' });
    expect(totalCount).toBe(1);
    expect(nodes).toEqual([{ __typename: 'Product', handle: 'aislearena-anti-tick-collar' }]);
  });

  it('matches products by description text', async () => {
    // "ultrasonic" appears only in the aislearena collar's description_html.
    const { totalCount, nodes } = await search({ q: 'ultrasonic' });
    expect(totalCount).toBe(1);
    expect(nodes).toEqual([{ __typename: 'Product', handle: 'aislearena-anti-tick-collar' }]);
  });

  it('matches products by tag', async () => {
    // "stuffed" appears only in the shopliseum "Stuffed animal" tag —
    // not in the title or description — exercising the tags portion of
    // the product haystack.
    const { totalCount, nodes } = await search({ q: 'stuffed' });
    expect(totalCount).toBe(1);
    expect(nodes).toEqual([{ __typename: 'Product', handle: 'shopliseum-mushroom-dog-toys' }]);
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
      { __typename: 'Product', handle: 'aislearena-anti-tick-collar' },
      { __typename: 'Product', handle: 'shopliseum-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'cartanvil-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'carthaeum-toothbrush' },
      { __typename: 'Article', handle: 'welcome-post' },
    ]);
  });

  it('returns every item when the query is empty', async () => {
    const { totalCount, nodes } = await search({ q: '' });
    expect(totalCount).toBe(7);
    expect(nodes).toEqual([
      { __typename: 'Product', handle: 'aislearena-anti-tick-collar' },
      { __typename: 'Product', handle: 'shopliseum-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'cartanvil-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'carthaeum-toothbrush' },
      { __typename: 'Page', handle: 'about-us' },
      { __typename: 'Article', handle: 'welcome-post' },
    ]);
  });

  it('honors the types filter — types: [PRODUCT] returns only products', async () => {
    const { totalCount, nodes } = await search({ q: 'mock', types: ['PRODUCT'] });
    expect(totalCount).toBe(5);
    expect(nodes.every((n) => n.__typename === 'Product')).toBe(true);
    expect(nodes).toEqual([
      { __typename: 'Product', handle: 'aislearena-anti-tick-collar' },
      { __typename: 'Product', handle: 'shopliseum-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'cartanvil-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'carthaeum-toothbrush' },
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
      { __typename: 'Product', handle: 'cartanvil-mackerel-and-sardines-70g' },
      { __typename: 'Product', handle: 'carthaeum-toothbrush' },
      { __typename: 'Product', handle: 'shopliseum-mushroom-dog-toys' },
      { __typename: 'Product', handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
      { __typename: 'Product', handle: 'aislearena-anti-tick-collar' },
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

  it('PRICE sort keeps a stable order when multiple entries share an infinite price', async () => {
    // Pages, articles, and products with no finite variant price all carry
    // price = +Infinity. PRICE ordering must place the finitely-priced product
    // first, then every infinite-priced entry in collection order (products,
    // pages, articles). This produces deterministic, stable ordering regardless
    // of how many entries tie at +Infinity.
    const priceData: SandboxShopData = {
      store: TEST_STORE,
      products: [makePricedProduct(1, 'a-priced', '5.00'), makePricedProduct(2, 'b-priceless', '')],
      collections: [],
      navigation: {},
      pages: [
        { handle: 'page-1', title: 'Page One', body_html: '' },
        { handle: 'page-2', title: 'Page Two', body_html: '' },
      ],
      policies: [],
      blogs: [
        {
          handle: 'news',
          title: 'News',
          articles: [
            {
              handle: 'art-1',
              title: 'Article One',
              content_html: '',
              author: null,
              published_at: null,
            },
            {
              handle: 'art-2',
              title: 'Article Two',
              content_html: '',
              author: null,
              published_at: null,
            },
          ],
        },
      ],
      metafields: { shop: [], products: {}, collections: {} },
      productsByHandle: new Map(),
      variantsByGid: new Map(),
    };
    const priceYoga = createYoga({
      schema: createSandboxSchema(resolvers),
      context: (): ResolverContext => ({ data: priceData, carts, baseUrl: BASE_URL }),
    });
    const response = await priceYoga.fetch(`${BASE_URL}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: NODES_QUERY, variables: { q: '', sortKey: 'PRICE' } }),
    });
    const payload = (await response.json()) as {
      readonly data: {
        readonly search: { readonly nodes: ReadonlyArray<{ readonly handle: string }> };
      };
    };
    expect(payload.data.search.nodes.map((n) => n.handle)).toEqual([
      'a-priced',
      'b-priceless',
      'page-1',
      'page-2',
      'art-1',
      'art-2',
    ]);
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
      { handle: 'aislearena-anti-tick-collar' },
      { handle: 'shopliseum-mushroom-dog-toys' },
      { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
      { handle: 'cartanvil-mackerel-and-sardines-70g' },
      { handle: 'carthaeum-toothbrush' },
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
      { handle: 'aislearena-anti-tick-collar' },
      { handle: 'shopliseum-mushroom-dog-toys' },
    ]);
    expect(result.articles).toEqual([{ handle: 'welcome-post' }]);
    expect(result.queries).toHaveLength(1);
  });

  it('honors limit across all types when limitScope is ALL', async () => {
    // "mock" hits 5 products + 1 article. limit=3 across ALL keeps the first
    // 3 products and drops everything else; the suggestion is unaffected.
    const result = await predictiveSearch({ q: 'mock', limit: 3, limitScope: 'ALL' });
    expect(result.products).toEqual([
      { handle: 'aislearena-anti-tick-collar' },
      { handle: 'shopliseum-mushroom-dog-toys' },
      { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
    ]);
    expect(result.articles).toEqual([]);
    expect(result.queries).toHaveLength(1);
  });

  it('echoes the trimmed term in the SearchQuerySuggestion', async () => {
    const result = await predictiveSearch({ q: '  AisleArena  ', types: ['QUERY'] });
    expect(result.queries).toEqual([
      { text: 'AisleArena', styledText: 'AisleArena', trackingParameters: null },
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

// ── Query.productRecommendations ──────────────────────────────────────────

const TEST_STORE: Store = {
  shop_id: 1,
  name: 'Test Shop',
  domain: 'test.example',
  description: '',
  currency_code: 'USD',
  country_code: 'US',
  payment_settings: { accepted_card_brands: [] },
  brand: {
    logo_url: null,
    colors: { primary: '#000000', secondary: '#ffffff' },
  },
};

function makeProduct(
  id: number,
  handle: string,
  productType: string,
  tags: readonly string[],
): Product {
  return {
    id,
    title: handle,
    handle,
    description_html: '',
    vendor: 'TestVendor',
    product_type: productType,
    tags,
    published_at: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    options: [],
    variants: [
      {
        id: id * 10,
        title: 'Default',
        sku: null,
        price: '10.00',
        compare_at_price: null,
        available: true,
        option1: null,
        option2: null,
        option3: null,
        position: 1,
        requires_shipping: true,
      },
    ],
    images: [],
  };
}

function makePricedProduct(id: number, handle: string, price: string): Product {
  const product = makeProduct(id, handle, '', []);
  return {
    ...product,
    variants: product.variants.map((variant) => ({ ...variant, price })),
  };
}

function makeData(products: readonly Product[]): SandboxShopData {
  return {
    store: TEST_STORE,
    products,
    collections: [],
    navigation: {},
    pages: [],
    policies: [],
    blogs: [],
    metafields: { shop: [], products: {}, collections: {} },
    productsByHandle: new Map(products.map((p) => [p.handle, p])),
    variantsByGid: new Map(),
  };
}

const RECOMMENDATIONS_QUERY = /* GraphQL */ `
  query ($id: ID!) {
    productRecommendations(productId: $id) {
      handle
    }
  }
`;

interface RecommendationsResponse {
  readonly data?: {
    readonly productRecommendations: readonly { readonly handle: string }[] | null;
  };
  readonly errors?: readonly unknown[];
}

async function recommend(
  yogaInstance: ReturnType<typeof createYoga>,
  productId: string,
): Promise<readonly { readonly handle: string }[] | null> {
  const response = await yogaInstance.fetch(`${BASE_URL}/graphql`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: RECOMMENDATIONS_QUERY, variables: { id: productId } }),
  });
  const payload = (await response.json()) as RecommendationsResponse;
  if (payload.errors !== undefined) {
    throw new Error(`productRecommendations failed: ${JSON.stringify(payload.errors)}`);
  }
  if (payload.data === undefined) throw new Error('productRecommendations returned no data');
  return payload.data.productRecommendations;
}

describe('searchResolvers — Query.productRecommendations', () => {
  // Synthetic catalog designed to exercise the type/tag/dataset-order cascade:
  //   alpha:   type 'cat',  tags red+blue  (the requesting product)
  //   beta:    type 'cat',  tags green     — same-type bonus only
  //   gamma:   type 'dog',  tags red       — 1 tag overlap
  //   delta:   type 'dog',  tags []        — no signal, dataset-order tail
  //   epsilon: type 'bird', tags blue+red  — 2 tag overlaps
  // Expected ranking from alpha: beta (same type) > epsilon (2 tags) >
  // gamma (1 tag) > delta (0).
  const synthetic = [
    makeProduct(1, 'alpha', 'cat', ['red', 'blue']),
    makeProduct(2, 'beta', 'cat', ['green']),
    makeProduct(3, 'gamma', 'dog', ['red']),
    makeProduct(4, 'delta', 'dog', []),
    makeProduct(5, 'epsilon', 'bird', ['blue', 'red']),
  ];
  const syntheticData = makeData(synthetic);
  const syntheticYoga = createYoga({
    schema: createSandboxSchema(resolvers),
    context: (): ResolverContext => ({ data: syntheticData, carts, baseUrl: BASE_URL }),
  });

  it('prefers same-type products, then tag overlap, then dataset order', async () => {
    const result = await recommend(syntheticYoga, 'gid://shopify/Product/1');
    expect(result).toEqual([
      { handle: 'beta' },
      { handle: 'epsilon' },
      { handle: 'gamma' },
      { handle: 'delta' },
    ]);
  });

  it('excludes the requesting product even when it would otherwise rank', async () => {
    const result = await recommend(syntheticYoga, 'gid://shopify/Product/1');
    const handles = (result ?? []).map((p) => p.handle);
    expect(handles).not.toContain('alpha');
  });

  it('caps the result at four products and drops the lowest-ranked tail', async () => {
    // Adding a 6th product with both same-type AND a tag overlap pushes it
    // above pure same-type beta. The cap then drops delta (the zero-score
    // dataset-order tail) so the result holds exactly four entries.
    const sixProductData = makeData([...synthetic, makeProduct(6, 'zeta', 'cat', ['red'])]);
    const sixYoga = createYoga({
      schema: createSandboxSchema(resolvers),
      context: (): ResolverContext => ({ data: sixProductData, carts, baseUrl: BASE_URL }),
    });
    const result = await recommend(sixYoga, 'gid://shopify/Product/1');
    expect(result).toEqual([
      { handle: 'zeta' },
      { handle: 'beta' },
      { handle: 'epsilon' },
      { handle: 'gamma' },
    ]);
  });

  it('returns the available subset when fewer than four other products exist', async () => {
    const tinyData = makeData([
      makeProduct(1, 'alpha', 'cat', []),
      makeProduct(2, 'beta', 'cat', []),
      makeProduct(3, 'gamma', 'dog', []),
    ]);
    const tinyYoga = createYoga({
      schema: createSandboxSchema(resolvers),
      context: (): ResolverContext => ({ data: tinyData, carts, baseUrl: BASE_URL }),
    });
    const result = await recommend(tinyYoga, 'gid://shopify/Product/1');
    expect(result).toEqual([{ handle: 'beta' }, { handle: 'gamma' }]);
  });

  it('does not award the same-type bonus to two empty product_type values', async () => {
    // alpha + beta share an empty product_type; the bonus is suppressed so the
    // tag overlap (red) wins and beta sorts ahead despite alpha-vs-gamma also
    // having an empty-vs-empty type.
    const data = makeData([
      makeProduct(1, 'alpha', '', ['red']),
      makeProduct(2, 'beta', 'snake', ['red']),
      makeProduct(3, 'gamma', '', []),
    ]);
    const targetYoga = createYoga({
      schema: createSandboxSchema(resolvers),
      context: (): ResolverContext => ({ data, carts, baseUrl: BASE_URL }),
    });
    const result = await recommend(targetYoga, 'gid://shopify/Product/1');
    expect(result).toEqual([{ handle: 'beta' }, { handle: 'gamma' }]);
  });

  it('returns null for an unknown product GID', async () => {
    const result = await recommend(syntheticYoga, 'gid://shopify/Product/999');
    expect(result).toBeNull();
  });

  it('returns null for a malformed product GID', async () => {
    const result = await recommend(syntheticYoga, 'not-a-gid');
    expect(result).toBeNull();
  });

  it('integrates with the loader fixture — excludes the requesting product', async () => {
    // The fixture has 5 products with no shared types or tags, so every
    // candidate ties at score 0. Dataset insertion order must be preserved
    // and the requesting product (aislearena, id 9048676991150) excluded.
    const result = await recommend(yoga, 'gid://shopify/Product/9048676991150');
    expect(result).toEqual([
      { handle: 'shopliseum-mushroom-dog-toys' },
      { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
      { handle: 'cartanvil-mackerel-and-sardines-70g' },
      { handle: 'carthaeum-toothbrush' },
    ]);
  });
});

describe('searchResolvers — Query.predictiveSearch with no blogs.json', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sandbox-shop-no-blogs-'));
  fs.cpSync(FIXTURE_DIR, tmpDir, { recursive: true });
  fs.rmSync(path.join(tmpDir, 'blogs.json'));

  const noBlogsData = loadShopData(tmpDir);
  const noBlogsYoga = createYoga({
    schema: createSandboxSchema(resolvers),
    context: (): ResolverContext => ({ data: noBlogsData, carts, baseUrl: BASE_URL }),
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
