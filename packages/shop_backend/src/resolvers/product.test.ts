import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { type SandboxSchemaResolvers, createSandboxSchema } from '../schema.js';
import { CartStore } from './cart.js';
import type { ResolverContext } from './index.js';
import { productResolvers } from './product.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);
const carts = new CartStore();

const resolvers: SandboxSchemaResolvers = {
  Query: productResolvers.Query,
  Product: productResolvers.Product,
  Collection: productResolvers.Collection,
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

describe('productResolvers — Query.product', () => {
  it('returns the product node for a known handle', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "tickless-anti-tick-collar") {
          id
          handle
          title
          vendor
          productType
          tags
          priceRange {
            minVariantPrice {
              amount
              currencyCode
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        id: 'gid://shopify/Product/9048676991150',
        handle: 'tickless-anti-tick-collar',
        title: 'Tickless Anti Tick Collar',
        vendor: 'Mock Pet Foods',
        productType: '',
        tags: ['Anti tick', 'Collar', 'Dog supplies'],
        priceRange: {
          minVariantPrice: { amount: '79.99', currencyCode: 'CAD' },
        },
      },
    });
  });

  it('returns null when the handle is not in the dataset', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "does-not-exist") {
          handle
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ product: null });
  });
});

describe('productResolvers — Query.products', () => {
  it('returns every product with totalCount when no args are supplied', async () => {
    const result = await run(/* GraphQL */ `
      {
        products {
          totalCount
          nodes {
            handle
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      products: {
        totalCount: 5,
        nodes: [
          { handle: 'tickless-anti-tick-collar' },
          { handle: 'fuzzyard-mushroom-dog-toys' },
          { handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
          { handle: 'applaws-mackerel-and-sardines-70g' },
          { handle: 'bluestem-toothbrush' },
        ],
      },
    });
  });

  it('paginates with `first` and exposes hasNextPage + an end cursor', async () => {
    const result = (await run(/* GraphQL */ `
      {
        products(first: 2) {
          nodes {
            handle
          }
          pageInfo {
            hasNextPage
            hasPreviousPage
            endCursor
          }
        }
      }
    `)) as { data: { products: { pageInfo: { endCursor: string } } } };
    expect((result as ExecutionResult).errors).toBeUndefined();
    const endCursor = result.data.products.pageInfo.endCursor;
    expect(result.data).toEqual({
      products: {
        nodes: [{ handle: 'tickless-anti-tick-collar' }, { handle: 'fuzzyard-mushroom-dog-toys' }],
        pageInfo: {
          hasNextPage: true,
          hasPreviousPage: false,
          endCursor,
        },
      },
    });

    const next = await run(/* GraphQL */ `
      {
        products(first: 2, after: "${endCursor}") {
          nodes {
            handle
          }
          pageInfo {
            hasPreviousPage
          }
        }
      }
    `);
    expect(next.errors).toBeUndefined();
    expect(next.data).toEqual({
      products: {
        nodes: [
          { handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
          { handle: 'applaws-mackerel-and-sardines-70g' },
        ],
        pageInfo: { hasPreviousPage: true },
      },
    });
  });

  it('sorts by PRICE ascending (min variant price)', async () => {
    const result = await run(/* GraphQL */ `
      {
        products(sortKey: PRICE) {
          nodes {
            handle
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      products: {
        nodes: [
          { handle: 'applaws-mackerel-and-sardines-70g' },
          { handle: 'bluestem-toothbrush' },
          { handle: 'fuzzyard-mushroom-dog-toys' },
          { handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
          { handle: 'tickless-anti-tick-collar' },
        ],
      },
    });
  });

  it('sorts by TITLE descending when reverse is true', async () => {
    const result = await run(/* GraphQL */ `
      {
        products(sortKey: TITLE, reverse: true) {
          nodes {
            title
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    const expected = [
      'Tickless Anti Tick Collar',
      'Go! Skin and coat chicken with grains 12lb dog',
      'Fuzzyard Mushroom Dog Toys',
      'Bluestem Toothbrush',
      'Applaws Mackerel and Sardines 70g',
    ];
    expect(result.data).toEqual({
      products: { nodes: expected.map((title) => ({ title })) },
    });
  });

  it('filters by query across title / description / tags / vendor / productType', async () => {
    const result = await run(/* GraphQL */ `
      {
        products(query: "tick") {
          totalCount
          nodes {
            handle
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      products: {
        totalCount: 1,
        nodes: [{ handle: 'tickless-anti-tick-collar' }],
      },
    });
  });
});

describe('productResolvers — Query.collection', () => {
  it('returns the collection node for a known handle', async () => {
    const result = await run(/* GraphQL */ `
      {
        collection(handle: "dog-essentials") {
          id
          handle
          title
          description
          updatedAt
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      collection: {
        id: 'gid://shopify/Collection/295460700334',
        handle: 'dog-essentials',
        title: 'Dog Essentials',
        description: 'Everything your dog needs - food, toys, and care products.',
        updatedAt: '2026-04-14T07:16:31-04:00',
      },
    });
  });

  it('returns null for an unknown collection handle', async () => {
    const result = await run(/* GraphQL */ `
      {
        collection(handle: "does-not-exist") {
          handle
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ collection: null });
  });

  it('exposes member products via Collection.products in dataset order', async () => {
    const result = await run(/* GraphQL */ `
      {
        collection(handle: "dog-essentials") {
          products {
            totalCount
            nodes {
              handle
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      collection: {
        products: {
          totalCount: 3,
          nodes: [
            { handle: 'fuzzyard-mushroom-dog-toys' },
            { handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
            { handle: 'tickless-anti-tick-collar' },
          ],
        },
      },
    });
  });

  it('synthesizes the "all" collection containing every product', async () => {
    const result = await run(/* GraphQL */ `
      {
        collection(handle: "all") {
          handle
          title
          products(first: 10) {
            totalCount
            nodes {
              handle
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      collection: {
        handle: 'all',
        title: 'All Products',
        products: {
          totalCount: 5,
          nodes: [
            { handle: 'tickless-anti-tick-collar' },
            { handle: 'fuzzyard-mushroom-dog-toys' },
            { handle: 'go-skin-and-coat-chicken-with-grains-12lb' },
            { handle: 'applaws-mackerel-and-sardines-70g' },
            { handle: 'bluestem-toothbrush' },
          ],
        },
      },
    });
  });
});

describe('productResolvers — Query.collections', () => {
  it('returns every collection in dataset order', async () => {
    const result = await run(/* GraphQL */ `
      {
        collections {
          nodes {
            handle
            title
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      collections: {
        nodes: [
          { handle: 'dog-essentials', title: 'Dog Essentials' },
          { handle: 'cat-care', title: 'Cat Care' },
        ],
      },
    });
  });

  it('sorts collections by TITLE', async () => {
    const result = await run(/* GraphQL */ `
      {
        collections(sortKey: TITLE) {
          nodes {
            handle
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      collections: {
        nodes: [{ handle: 'cat-care' }, { handle: 'dog-essentials' }],
      },
    });
  });
});

describe('productResolvers — Product.selectedOrFirstAvailableVariant', () => {
  it('returns the variant matching the supplied selectedOptions', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "tickless-anti-tick-collar") {
          selectedOrFirstAvailableVariant(
            selectedOptions: [{ name: "Blue", value: "Yellow" }]
          ) {
            id
            title
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        selectedOrFirstAvailableVariant: {
          id: 'gid://shopify/ProductVariant/47642514456750',
          title: 'Yellow',
        },
      },
    });
  });

  it('falls back to the first available variant when selectedOptions is omitted', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "applaws-mackerel-and-sardines-70g") {
          selectedOrFirstAvailableVariant {
            title
            availableForSale
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    // The fixture's only variant is unavailable, so we fall through to the
    // first variant rather than null.
    expect(result.data).toEqual({
      product: {
        selectedOrFirstAvailableVariant: {
          title: 'Default Title',
          availableForSale: false,
        },
      },
    });
  });
});

describe('productResolvers — ProductVariant.quantityAvailable + availableForSale', () => {
  it('exposes the tracked count via selectedOrFirstAvailableVariant', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "fuzzyard-mushroom-dog-toys") {
          selectedOrFirstAvailableVariant(
            selectedOptions: [{ name: "Giggles Mushroom", value: "Giggles Mushroom" }]
          ) {
            title
            quantityAvailable
            availableForSale
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        selectedOrFirstAvailableVariant: {
          title: 'Giggles Mushroom',
          quantityAvailable: 2,
          availableForSale: true,
        },
      },
    });
  });

  it('overrides availableForSale to false when the inventory count is zero', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "fuzzyard-mushroom-dog-toys") {
          selectedOrFirstAvailableVariant(
            selectedOptions: [{ name: "Giggles Mushroom", value: "Cosmo Mushroom" }]
          ) {
            title
            quantityAvailable
            availableForSale
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        selectedOrFirstAvailableVariant: {
          title: 'Cosmo Mushroom',
          quantityAvailable: 0,
          availableForSale: false,
        },
      },
    });
  });
});
