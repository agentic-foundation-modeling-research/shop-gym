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
        product(handle: "aislearena-anti-tick-collar") {
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
        handle: 'aislearena-anti-tick-collar',
        title: 'AisleArena Anti Tick Collar',
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

  it('exposes Hydrogen encoded variant fields', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "aislearena-anti-tick-collar") {
          encodedVariantExistence
          encodedVariantAvailability
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        encodedVariantExistence: 'v1_0 1',
        encodedVariantAvailability: 'v1_0 1',
      },
    });
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
          { handle: 'aislearena-anti-tick-collar' },
          { handle: 'shopliseum-mushroom-dog-toys' },
          { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
          { handle: 'cartanvil-mackerel-and-sardines-70g' },
          { handle: 'carthaeum-toothbrush' },
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
        nodes: [
          { handle: 'aislearena-anti-tick-collar' },
          { handle: 'shopliseum-mushroom-dog-toys' },
        ],
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
          { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
          { handle: 'cartanvil-mackerel-and-sardines-70g' },
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
          { handle: 'cartanvil-mackerel-and-sardines-70g' },
          { handle: 'carthaeum-toothbrush' },
          { handle: 'shopliseum-mushroom-dog-toys' },
          { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
          { handle: 'aislearena-anti-tick-collar' },
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
      'Shopliseum Mushroom Dog Toys',
      'Carthaeum Toothbrush',
      'Cartanvil Mackerel and Sardines 70g',
      'AisleArena Anti Tick Collar',
      'AgoraCage Skin and coat chicken with grains 12lb dog',
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
        nodes: [{ handle: 'aislearena-anti-tick-collar' }],
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
            { handle: 'shopliseum-mushroom-dog-toys' },
            { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
            { handle: 'aislearena-anti-tick-collar' },
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
            { handle: 'aislearena-anti-tick-collar' },
            { handle: 'shopliseum-mushroom-dog-toys' },
            { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
            { handle: 'cartanvil-mackerel-and-sardines-70g' },
            { handle: 'carthaeum-toothbrush' },
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
  it('wraps product images as a paginated connection', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "aislearena-anti-tick-collar") {
          images(first: 1) {
            nodes {
              id
              url
              width
              height
            }
            edges {
              node {
                id
              }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        images: {
          nodes: [
            {
              id: 'gid://shopify/ProductImage/43482199916718',
              url: '/images/products/aislearena-anti-tick-collar-1.jpg',
              width: 3264,
              height: 2448,
            },
          ],
          edges: [{ node: { id: 'gid://shopify/ProductImage/43482199916718' } }],
        },
      },
    });
  });

  it('wraps product variants as a paginated connection', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "aislearena-anti-tick-collar") {
          variants(first: 1) {
            nodes {
              id
              title
            }
            edges {
              node {
                id
              }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        variants: {
          nodes: [
            {
              id: 'gid://shopify/ProductVariant/47642512195758',
              title: 'Blue',
            },
          ],
          edges: [{ node: { id: 'gid://shopify/ProductVariant/47642512195758' } }],
        },
      },
    });
  });

  it('returns the variant matching the supplied selectedOptions', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "aislearena-anti-tick-collar") {
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
        product(handle: "cartanvil-mackerel-and-sardines-70g") {
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
        product(handle: "shopliseum-mushroom-dog-toys") {
          selectedOrFirstAvailableVariant(
            selectedOptions: [{ name: "Red Mushroom", value: "Red Mushroom" }]
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
          title: 'Red Mushroom',
          quantityAvailable: 2,
          availableForSale: true,
        },
      },
    });
  });

  it('overrides availableForSale to false when the inventory count is zero', async () => {
    const result = await run(/* GraphQL */ `
      {
        product(handle: "shopliseum-mushroom-dog-toys") {
          selectedOrFirstAvailableVariant(
            selectedOptions: [{ name: "Red Mushroom", value: "Blue Mushroom" }]
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
          title: 'Blue Mushroom',
          quantityAvailable: 0,
          availableForSale: false,
        },
      },
    });
  });
});
