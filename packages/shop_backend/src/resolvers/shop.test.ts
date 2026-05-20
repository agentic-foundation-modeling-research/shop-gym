import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { createSandboxSchema } from '../schema.js';
import { CartStore } from './cart.js';
import type { ResolverContext } from './index.js';
import { shopResolvers } from './shop.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);
const carts = new CartStore();

// Drive queries through yoga so the schema, executor, and `graphql` instance
// all come from a single realm — vitest otherwise hits the dual-package
// (CJS/ESM) hazard when calling `graphql()` directly on a yoga-built schema.
const yoga = createYoga({
  schema: createSandboxSchema(shopResolvers),
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

describe('shopResolvers — Query.shop', () => {
  it('resolves the canonical shop query with policy + payment + domain fields', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          name
          primaryDomain {
            host
          }
          paymentSettings {
            currencyCode
          }
          privacyPolicy {
            handle
            title
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: {
        name: 'Mock Pet Foods',
        primaryDomain: { host: 'mock-pet-foods.example' },
        paymentSettings: { currencyCode: 'CAD' },
        privacyPolicy: { handle: 'privacy-policy', title: 'Privacy Policy' },
      },
    });
  });

  it('exposes brand colors plumbed from store.brand.colors', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          brand {
            colors {
              primary {
                background
                foreground
              }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: {
        brand: {
          colors: {
            primary: [{ background: '#1f6f43', foreground: '#f3e9d2' }],
          },
        },
      },
    });
  });

  it('returns null for policies missing from the dataset', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          privacyPolicy {
            handle
          }
          shippingPolicy {
            handle
          }
          termsOfService {
            handle
          }
          refundPolicy {
            handle
          }
          subscriptionPolicy {
            handle
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: {
        privacyPolicy: { handle: 'privacy-policy' },
        shippingPolicy: null,
        termsOfService: null,
        refundPolicy: null,
        subscriptionPolicy: null,
      },
    });
  });

  it('exposes the accepted card brands list verbatim', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          paymentSettings {
            acceptedCardBrands
            countryCode
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      shop: {
        paymentSettings: {
          acceptedCardBrands: ['VISA', 'MASTER', 'AMERICAN_EXPRESS'],
          countryCode: 'CA',
        },
      },
    });
  });
});

describe('shopResolvers — Query.menu', () => {
  it('returns a menu for a known navigation handle', async () => {
    const result = await run(/* GraphQL */ `
      {
        menu(handle: "main-menu") {
          handle
          title
          items {
            title
            type
            url
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      menu: {
        handle: 'main-menu',
        title: 'Main Menu',
        items: [
          { title: 'Shop Dogs', type: 'COLLECTION', url: '/collections/dog-essentials' },
          { title: 'Shop Cats', type: 'COLLECTION', url: '/collections/cat-care' },
          { title: 'About', type: 'PAGE', url: '/pages/about-us' },
        ],
      },
    });
  });

  it('returns null for an unknown menu handle', async () => {
    const result = await run(/* GraphQL */ `
      {
        menu(handle: "does-not-exist") {
          handle
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ menu: null });
  });
});

describe('shopResolvers — Query.localization', () => {
  it('derives a single country/language pair from store country + currency', async () => {
    const result = await run(/* GraphQL */ `
      {
        localization {
          country {
            isoCode
            name
            currency {
              isoCode
              name
              symbol
            }
          }
          language {
            isoCode
            name
          }
          availableCountries {
            isoCode
            currency {
              isoCode
            }
          }
          availableLanguages {
            isoCode
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      localization: {
        country: {
          isoCode: 'CA',
          name: 'Canada',
          currency: { isoCode: 'CAD', name: 'Canadian Dollar', symbol: '$' },
        },
        language: { isoCode: 'EN', name: 'English' },
        availableCountries: [{ isoCode: 'CA', currency: { isoCode: 'CAD' } }],
        availableLanguages: [{ isoCode: 'EN' }],
      },
    });
  });
});
