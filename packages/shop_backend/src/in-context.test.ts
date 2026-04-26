/**
 * Tests for the `@inContext` directive enforcement plugin (T7.3).
 *
 * Drives queries through a yoga instance wired with the validation plugin so
 * the rule is exercised end-to-end (parse → validate → execute) against the
 * default fixture (CA / EN). Asserts:
 *
 *   - Matching country/language passes through to the resolvers.
 *   - Mismatched country surfaces an `UNSUPPORTED_LOCALE` error and no
 *     `data` field per the v0.2 contract (validation errors abort execution
 *     before the resolvers run).
 *   - Mismatched language surfaces the same error.
 *   - Queries with no `@inContext` directive are unaffected.
 *   - `visitorConsent` is accepted without locale validation.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { describe, expect, it } from 'vitest';

import { loadShopData } from './data/loader.js';
import { createInContextValidationPlugin } from './in-context.js';
import { CartStore } from './resolvers/cart.js';
import type { ResolverContext } from './resolvers/index.js';
import { createSandboxSchema } from './schema.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../tests/fixtures/sandbox_shop_v0',
);
const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);
const carts = new CartStore();

const yoga = createYoga({
  schema: createSandboxSchema(),
  plugins: [createInContextValidationPlugin(data)],
  context: (): ResolverContext => ({ data, carts, baseUrl: BASE_URL }),
});

interface ExecutionResult {
  readonly data?: { readonly shop?: { readonly name?: string } | null } | null;
  readonly errors?: ReadonlyArray<{
    readonly message: string;
    readonly extensions?: { readonly code?: string };
  }>;
}

async function run(source: string): Promise<ExecutionResult> {
  const response = await yoga.fetch(`${BASE_URL}/graphql`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: source }),
  });
  return (await response.json()) as ExecutionResult;
}

describe('createInContextValidationPlugin', () => {
  it('passes queries with no @inContext directive', async () => {
    const result = await run(/* GraphQL */ `
      {
        shop {
          name
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data?.shop?.name).toBe(data.store.name);
  });

  it('passes @inContext with the dataset country + language', async () => {
    const result = await run(/* GraphQL */ `
      query LocaleMatch @inContext(country: CA, language: EN) {
        shop {
          name
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data?.shop?.name).toBe(data.store.name);
  });

  it('rejects @inContext with a country the dataset does not serve', async () => {
    const result = await run(/* GraphQL */ `
      query LocaleMismatch @inContext(country: GB) {
        shop {
          name
        }
      }
    `);
    expect(result.data).toBeUndefined();
    expect(result.errors).toBeDefined();
    expect(result.errors).toHaveLength(1);
    const error = result.errors?.[0];
    expect(error?.extensions?.code).toBe('UNSUPPORTED_LOCALE');
    expect(error?.message).toContain('country "GB"');
    expect(error?.message).toContain('"CA"');
  });

  it('rejects @inContext with a language the dataset does not serve', async () => {
    const result = await run(/* GraphQL */ `
      query LangMismatch @inContext(language: FR) {
        shop {
          name
        }
      }
    `);
    expect(result.data).toBeUndefined();
    expect(result.errors).toBeDefined();
    expect(result.errors).toHaveLength(1);
    const error = result.errors?.[0];
    expect(error?.extensions?.code).toBe('UNSUPPORTED_LOCALE');
    expect(error?.message).toContain('language "FR"');
    expect(error?.message).toContain('"EN"');
  });

  it('reports both errors when country and language mismatch in the same query', async () => {
    const result = await run(/* GraphQL */ `
      query DoubleMismatch @inContext(country: GB, language: FR) {
        shop {
          name
        }
      }
    `);
    expect(result.data).toBeUndefined();
    expect(result.errors).toBeDefined();
    expect(result.errors).toHaveLength(2);
    const codes = result.errors?.map((e) => e.extensions?.code);
    expect(codes).toEqual(['UNSUPPORTED_LOCALE', 'UNSUPPORTED_LOCALE']);
  });

  it('accepts visitorConsent without imposing locale validation on it', async () => {
    const result = await run(/* GraphQL */ `
      query ConsentOnly @inContext(visitorConsent: { marketing: true }) {
        shop {
          name
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data?.shop?.name).toBe(data.store.name);
  });

  it('enforces the directive on mutations as well', async () => {
    const result = await run(/* GraphQL */ `
      mutation MutateInUnsupportedLocale @inContext(country: GB) {
        cartCreate(input: {}) {
          cart {
            id
          }
        }
      }
    `);
    expect(result.data).toBeUndefined();
    expect(result.errors).toBeDefined();
    expect(result.errors?.[0]?.extensions?.code).toBe('UNSUPPORTED_LOCALE');
  });
});
