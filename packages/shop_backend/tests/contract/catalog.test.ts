/**
 * Contract: catalog reads against the committed fixture. These pin the
 * behaviour generated shops' storefronts already depend on; change them only
 * with a deliberate, documented API change.
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

describe('contract: shop', () => {
  it('shop exposes name, domain, currency, and payment settings', async () => {
    const result = await ctx.query(/* GraphQL */ `
      {
        shop {
          name
          primaryDomain { host url }
          paymentSettings { currencyCode countryCode acceptedCardBrands }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: {
        name: 'Mock Pet Foods',
        primaryDomain: { host: 'mock-pet-foods.example', url: 'https://mock-pet-foods.example' },
        paymentSettings: {
          currencyCode: 'CAD',
          countryCode: 'CA',
          acceptedCardBrands: ['VISA', 'MASTER', 'AMERICAN_EXPRESS'],
        },
      },
    });
  });
});

describe('contract: products', () => {
  it('products(first) pages in dataset order with totalCount and cursors', async () => {
    const result = await ctx.query(/* GraphQL */ `
      {
        products(first: 3) {
          totalCount
          pageInfo { hasNextPage hasPreviousPage }
          nodes { handle }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      products: {
        totalCount: 5,
        pageInfo: { hasNextPage: true, hasPreviousPage: false },
        nodes: [
          { handle: 'aislearena-anti-tick-collar' },
          { handle: 'shopliseum-mushroom-dog-toys' },
          { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
        ],
      },
    });
  });

  it('product(handle) returns price range, availability, variants, and quantityAvailable', async () => {
    const result = await ctx.query(/* GraphQL */ `
      {
        product(handle: "shopliseum-mushroom-dog-toys") {
          id
          title
          availableForSale
          priceRange { minVariantPrice { amount currencyCode } maxVariantPrice { amount } }
          variants(first: 4) { nodes { id title availableForSale quantityAvailable price { amount } } }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        id: 'gid://shopify/Product/8938306273454',
        title: 'Shopliseum Mushroom Dog Toys',
        availableForSale: true,
        priceRange: {
          minVariantPrice: { amount: '19.99', currencyCode: 'CAD' },
          maxVariantPrice: { amount: '19.99' },
        },
        variants: {
          nodes: [
            {
              id: 'gid://shopify/ProductVariant/47242666836142',
              title: 'Red Mushroom',
              availableForSale: true,
              quantityAvailable: 2,
              price: { amount: '19.99' },
            },
            {
              id: 'gid://shopify/ProductVariant/47242687709358',
              title: 'Blue Mushroom',
              availableForSale: false,
              quantityAvailable: 0,
              price: { amount: '19.99' },
            },
            {
              id: 'gid://shopify/ProductVariant/47242695737518',
              title: 'Green Mushroom',
              availableForSale: true,
              quantityAvailable: null,
              price: { amount: '19.99' },
            },
            {
              id: 'gid://shopify/ProductVariant/47242720215214',
              title: 'Yellow Mushroom',
              availableForSale: true,
              quantityAvailable: null,
              price: { amount: '19.99' },
            },
          ],
        },
      },
    });
  });

  it('product(handle) is null for an unknown handle', async () => {
    const result = await ctx.query(/* GraphQL */ `{ product(handle: "does-not-exist") { id } }`);
    expect(result.data).toEqual({ product: null });
  });
});

describe('contract: collections', () => {
  it('collections and collection(handle).products keep dataset order', async () => {
    const result = await ctx.query(/* GraphQL */ `
      {
        collections(first: 5) { nodes { handle title } }
        collection(handle: "dog-essentials") {
          title
          products(first: 5) { nodes { handle } }
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
      collection: {
        title: 'Dog Essentials',
        products: {
          nodes: [
            { handle: 'shopliseum-mushroom-dog-toys' },
            { handle: 'agoracage-skin-and-coat-chicken-with-grains-12lb' },
            { handle: 'aislearena-anti-tick-collar' },
          ],
        },
      },
    });
  });
});
