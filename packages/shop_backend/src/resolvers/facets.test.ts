import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { afterAll, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import type { SandboxShopData } from '../data/types.js';
import { createSandboxSchema } from '../schema/index.js';
import { CartStore } from './cart.js';
import type { ResolverContext } from './index.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

/**
 * Marketplace fields for the fixture products, with fake brands. Ratings
 * from `reviews.json`: collar 4.5, toys 3.8, food 4.0, toothbrush 3.0;
 * the mackerel has no Reviews and no variant for sale.
 */
const MARKETPLACE: Readonly<Record<string, { brand: string; category_path: string[] }>> = {
  'aislearena-anti-tick-collar': {
    brand: 'AisleArena',
    category_path: ['Pets', 'Dogs', 'Collars'],
  },
  'shopliseum-mushroom-dog-toys': { brand: 'Shopliseum', category_path: ['Pets', 'Dogs', 'Toys'] },
  'agoracage-skin-and-coat-chicken-with-grains-12lb': {
    brand: 'AgoraCage',
    category_path: ['Pets', 'Dogs', 'Food'],
  },
  'cartanvil-mackerel-and-sardines-70g': {
    brand: 'Cartanvil',
    category_path: ['Pets', 'Cats', 'Food'],
  },
  'carthaeum-toothbrush': { brand: 'AisleArena', category_path: ['Pets', 'Cats', 'Dental'] },
};

const tmpDirs: string[] = [];

afterAll(() => {
  for (const dir of tmpDirs) fs.rmSync(dir, { recursive: true, force: true });
});

/** The fixture, with `products` replaced, loaded from a temporary copy. */
function loadWithProducts(
  products: readonly unknown[],
  reviews?: readonly unknown[],
): SandboxShopData {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'facets-'));
  tmpDirs.push(dir);
  fs.cpSync(FIXTURE_DIR, dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'products.json'), JSON.stringify(products));
  if (reviews !== undefined)
    fs.writeFileSync(path.join(dir, 'reviews.json'), JSON.stringify(reviews));
  return loadShopData(dir);
}

function fixtureProducts(): Record<string, unknown>[] {
  return JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, 'products.json'), 'utf8')) as Record<
    string,
    unknown
  >[];
}

function marketplaceData(): SandboxShopData {
  return loadWithProducts(
    fixtureProducts().map((product) => ({ ...product, ...MARKETPLACE[String(product.handle)] })),
  );
}

interface FilterValue {
  readonly id: string;
  readonly label: string;
  readonly count: number;
  readonly input: string;
}

interface Filter {
  readonly id: string;
  readonly label: string;
  readonly type: string;
  readonly values: readonly FilterValue[];
}

interface ProductList {
  readonly totalCount: number;
  readonly handles: readonly string[];
  readonly filters: readonly Filter[];
}

const FILTER_FIELDS = /* GraphQL */ `
  id
  label
  type
  values {
    id
    label
    count
    input
  }
`;

const SEARCH_QUERY = /* GraphQL */ `
  query ($q: String!, $filters: [ProductFilter!], $first: Int) {
    search(query: $q, first: $first, productFilters: $filters) {
      totalCount
      nodes {
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
      productFilters { ${FILTER_FIELDS} }
    }
  }
`;

const COLLECTION_QUERY = /* GraphQL */ `
  query ($handle: String!, $filters: [ProductFilter!]) {
    collection(handle: $handle) {
      products(first: 50, filters: $filters) {
        totalCount
        nodes {
          handle
        }
        filters { ${FILTER_FIELDS} }
      }
    }
  }
`;

function client(data: SandboxShopData) {
  const yoga = createYoga({
    schema: createSandboxSchema(),
    context: (): Omit<ResolverContext, 'state'> => ({
      data,
      carts: new CartStore(),
      baseUrl: BASE_URL,
    }),
  });
  async function execute(query: string, variables: Record<string, unknown>): Promise<unknown> {
    const response = await yoga.fetch(`${BASE_URL}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, variables }),
    });
    const payload = (await response.json()) as { data?: unknown; errors?: unknown };
    if (payload.errors !== undefined) throw new Error(JSON.stringify(payload.errors));
    return payload.data;
  }
  return {
    async search(q: string, filters?: readonly unknown[], first = 50): Promise<ProductList> {
      const result = (await execute(SEARCH_QUERY, { q, filters, first })) as {
        search: {
          totalCount: number;
          nodes: { handle: string }[];
          productFilters: Filter[];
        };
      };
      return {
        totalCount: result.search.totalCount,
        handles: result.search.nodes.map((node) => node.handle),
        filters: result.search.productFilters,
      };
    },
    async collection(handle: string, filters?: readonly unknown[]): Promise<ProductList> {
      const result = (await execute(COLLECTION_QUERY, { handle, filters })) as {
        collection: {
          products: { totalCount: number; nodes: { handle: string }[]; filters: Filter[] };
        };
      };
      const products = result.collection.products;
      return {
        totalCount: products.totalCount,
        handles: products.nodes.map((node) => node.handle),
        filters: products.filters,
      };
    },
    execute,
  };
}

/** `{label: count}` of the facet with `id`, in response order. */
function counts(filters: readonly Filter[], id: string): Record<string, number> {
  const filter = filters.find((f) => f.id === id);
  if (filter === undefined) throw new Error(`no facet ${id}`);
  return Object.fromEntries(filter.values.map((value) => [value.label, value.count]));
}

const COLLAR = 'aislearena-anti-tick-collar';
const TOYS = 'shopliseum-mushroom-dog-toys';
const FOOD = 'agoracage-skin-and-coat-chicken-with-grains-12lb';
const MACKEREL = 'cartanvil-mackerel-and-sardines-70g';
const TOOTHBRUSH = 'carthaeum-toothbrush';

describe('search productFilters', () => {
  const shop = client(marketplaceData());

  it('returns the category, brand, price and rating facets with counts', async () => {
    const result = await shop.search('');

    expect(result.filters.map((f) => [f.id, f.label, f.type])).toEqual([
      ['filter.p.category_path', 'Category', 'LIST'],
      ['filter.p.brand', 'Brand', 'LIST'],
      ['filter.v.price', 'Price', 'PRICE_RANGE'],
      ['filter.p.rating', 'Rating', 'LIST'],
    ]);
    expect(counts(result.filters, 'filter.p.category_path')).toEqual({ Pets: 5 });
    expect(counts(result.filters, 'filter.p.brand')).toEqual({
      AisleArena: 2,
      AgoraCage: 1,
      Cartanvil: 1,
      Shopliseum: 1,
    });
    expect(counts(result.filters, 'filter.p.rating')).toEqual({
      '4 stars & up': 2,
      '3 stars & up': 4,
      '2 stars & up': 4,
      '1 star & up': 4,
    });
    const price = result.filters.find((f) => f.id === 'filter.v.price')?.values;
    expect(price).toEqual([
      {
        id: 'filter.v.price',
        label: 'Price',
        count: 5,
        input: JSON.stringify({ price: { min: 0, max: 79.99 } }),
      },
    ]);
  });

  it('gives each value the ProductFilter that selects it', async () => {
    const result = await shop.search('');
    const brand = result.filters.find((f) => f.id === 'filter.p.brand');
    const value = brand?.values.find((v) => v.label === 'Cartanvil');

    expect(value?.id).toBe('filter.p.brand.Cartanvil');
    const filtered = await shop.search('', [JSON.parse(value?.input ?? 'null')]);
    expect(filtered.handles).toEqual([MACKEREL]);
  });

  it('matches any of several brands and keeps the brand counts of the unfiltered list', async () => {
    const result = await shop.search('', [{ brand: 'AisleArena' }, { brand: 'Cartanvil' }]);

    expect(result.handles).toEqual([COLLAR, MACKEREL, TOOTHBRUSH]);
    expect(result.totalCount).toBe(3);
    expect(counts(result.filters, 'filter.p.brand')).toEqual({
      AisleArena: 2,
      AgoraCage: 1,
      Cartanvil: 1,
      Shopliseum: 1,
    });
    expect(counts(result.filters, 'filter.p.category_path')).toEqual({ Pets: 3 });
  });

  it('matches every filter key at once', async () => {
    const result = await shop.search('', [{ brand: 'AisleArena' }, { price: { max: 20 } }]);

    expect(result.handles).toEqual([TOOTHBRUSH]);
    expect(counts(result.filters, 'filter.p.brand')).toEqual({
      AisleArena: 1,
      Shopliseum: 1,
      Cartanvil: 1,
    });
  });

  it('drills down a category and lists its path and its children', async () => {
    const result = await shop.search('', [{ categoryPath: ['Pets', 'Dogs'] }]);

    expect(result.handles).toEqual([COLLAR, TOYS, FOOD]);
    const category = result.filters.find((f) => f.id === 'filter.p.category_path');
    expect(category?.values.map((v) => [v.label, v.count, JSON.parse(v.input)])).toEqual([
      ['Pets', 5, { categoryPath: ['Pets'] }],
      ['Dogs', 3, { categoryPath: ['Pets', 'Dogs'] }],
      ['Collars', 1, { categoryPath: ['Pets', 'Dogs', 'Collars'] }],
      ['Food', 1, { categoryPath: ['Pets', 'Dogs', 'Food'] }],
      ['Toys', 1, { categoryPath: ['Pets', 'Dogs', 'Toys'] }],
    ]);
  });

  it('filters by the mean Review rating and skips products without Reviews', async () => {
    const atLeastFour = await shop.search('', [{ rating: { min: 4 } }]);
    const belowFour = await shop.search('', [{ rating: { max: 3.9 } }]);

    expect(atLeastFour.handles).toEqual([COLLAR, FOOD]);
    expect(belowFour.handles).toEqual([TOYS, TOOTHBRUSH]);
  });

  it('keeps a selected value that no product matches, so the shopper can clear it', async () => {
    const result = await shop.search('collar', [{ brand: 'Cartanvil' }]);

    expect(result.handles).toEqual([]);
    expect(counts(result.filters, 'filter.p.brand')).toEqual({ AisleArena: 1, Cartanvil: 0 });
  });

  it('applies the Storefront filter keys', async () => {
    const byType = await shop.search('', [{ productType: 'Dog Toys' }]);
    const byVendor = await shop.search('', [{ productVendor: 'Mock Pet Foods' }]);
    const byOption = await shop.search('', [{ variantOption: { name: 'Blue', value: 'Yellow' } }]);
    const forSale = await shop.search('', [{ available: true }]);
    const soldOut = await shop.search('', [{ available: false }]);

    expect(byType.handles).toEqual([TOYS]);
    expect(byVendor.totalCount).toBe(5);
    expect(byOption.handles).toEqual([COLLAR]);
    expect(forSale.handles).toEqual([COLLAR, TOYS, FOOD, TOOTHBRUSH]);
    expect(soldOut.handles).toEqual([MACKEREL]);
  });

  it('returns only products when a filter is set', async () => {
    const unfiltered = await shop.search('');
    const filtered = await shop.search('', [{ available: true }]);

    expect(unfiltered.handles).toEqual(expect.arrayContaining(['about-us', 'welcome-post']));
    expect(filtered.handles).toEqual([COLLAR, TOYS, FOOD, TOOTHBRUSH]);
  });

  it('counts and pages the filtered products', async () => {
    const result = await shop.search('', [{ categoryPath: ['Pets'] }], 2);

    expect(result.totalCount).toBe(5);
    expect(result.handles).toHaveLength(2);
  });
});

describe('Collection.products filters', () => {
  const shop = client(marketplaceData());

  it('filters the members of a collection and counts the facets over them', async () => {
    const all = await shop.collection('dog-essentials');
    const filtered = await shop.collection('dog-essentials', [{ price: { min: 50 } }]);

    expect(counts(all.filters, 'filter.p.brand')).toEqual({
      AgoraCage: 1,
      AisleArena: 1,
      Shopliseum: 1,
    });
    expect(filtered.handles).toEqual([FOOD, COLLAR]);
    expect(filtered.totalCount).toBe(2);
  });

  it('filters the synthetic all collection', async () => {
    const result = await shop.collection('all', [{ categoryPath: ['Pets', 'Cats'] }]);

    expect(result.handles).toEqual([MACKEREL, TOOTHBRUSH]);
  });
});

describe('facets in a shop without marketplace data', () => {
  const shop = client(loadShopData(FIXTURE_DIR));

  it('returns no facets but still applies the filters', async () => {
    const search = await shop.search('', [{ productType: 'Dog food' }]);
    const collection = await shop.collection('cat-care', [{ price: { max: 5 } }]);

    expect(search.filters).toEqual([]);
    expect(search.handles).toEqual([FOOD]);
    expect(collection.filters).toEqual([]);
    expect(collection.handles).toEqual([MACKEREL]);
  });

  it('returns no facets on Query.products', async () => {
    const result = (await shop.execute('{ products(first: 1) { filters { id } } }', {})) as {
      products: { filters: unknown[] };
    };

    expect(result.products.filters).toEqual([]);
  });
});

describe('search facets over 10K products', () => {
  const PRODUCT_COUNT = 10_000;
  const BRANDS = ['AisleArena', 'Shopliseum', 'AgoraCage', 'Cartrome', 'Shopodrome', 'Cartanvil'];
  const DEPARTMENTS = ['Pets', 'Garden', 'Kitchen', 'Outdoor'];
  const AISLES = ['Tools', 'Toys', 'Storage', 'Lighting', 'Care'];
  /** Generous for a slow CI runner; a warm local run takes about 10 ms. */
  const TIME_LIMIT_MS = 500;

  const [template] = fixtureProducts();
  const products = Array.from({ length: PRODUCT_COUNT }, (_, i) => ({
    ...template,
    id: i + 1,
    title: `${BRANDS[i % BRANDS.length]} item ${i}`,
    handle: `item-${i}`,
    description_html: `<p>A sturdy item number ${i} for everyday use.</p>`,
    tags: ['sturdy', `aisle-${i % 5}`],
    options: [{ name: 'Title', position: 1, values: ['Default Title'] }],
    variants: [
      {
        id: 1_000_000 + i,
        title: 'Default Title',
        sku: null,
        price: ((i % 200) + 0.99).toFixed(2),
        compare_at_price: null,
        available: i % 7 !== 0,
        option1: 'Default Title',
        option2: null,
        option3: null,
        position: 1,
        requires_shipping: true,
      },
    ],
    images: [],
    brand: BRANDS[i % BRANDS.length],
    category_path: [DEPARTMENTS[i % 4], AISLES[i % 5], `Shelf ${i % 11}`],
  }));
  const reviews = products.map((product, i) => ({
    id: i + 1,
    product_handle: product.handle,
    variant_id: 1_000_000 + i,
    rating: (i % 5) + 1,
    title: 'Fine',
    body: 'Works as described.',
    reviewer_name: 'Maya R.',
    created_at: '2025-11-20T15:00:00.000Z',
    verified_buyer: true,
    helpful_count: 0,
  }));
  const shop = client(loadWithProducts(products, reviews));

  it('answers a filtered, faceted search within the time limit', async () => {
    const filters = [
      { brand: 'AisleArena' },
      { brand: 'Cartrome' },
      { categoryPath: ['Pets'] },
      { price: { min: 10, max: 150 } },
      { rating: { min: 2 } },
    ];
    await shop.search('sturdy', filters);

    const started = performance.now();
    const result = await shop.search('sturdy', filters);
    const elapsed = performance.now() - started;

    expect(result.totalCount).toBeGreaterThan(0);
    expect(result.handles).toHaveLength(50);
    expect(result.filters.map((f) => f.id)).toEqual([
      'filter.p.category_path',
      'filter.p.brand',
      'filter.v.price',
      'filter.p.rating',
    ]);
    expect(elapsed).toBeLessThan(TIME_LIMIT_MS);
  });
});
