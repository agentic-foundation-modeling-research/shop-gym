/**
 * Customer domain tests: account creation, token login/logout, the
 * authenticated `customer` query, and cart <-> customer association.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { beforeEach, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { createSandboxSchema } from '../schema/index.js';
import { ShopState } from '../state/shop_state.js';
import type { ResolverContext } from './index.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);
const BASE_URL = 'http://sandbox.test';

const data = loadShopData(FIXTURE_DIR);
const schema = createSandboxSchema();

interface ExecutionResult {
  readonly data?: unknown;
  readonly errors?: readonly unknown[];
}

function runWith(state: ShopState) {
  const yoga = createYoga({
    schema,
    context: (): ResolverContext => ({
      data: state.data,
      state,
      carts: state.carts,
      baseUrl: BASE_URL,
    }),
  });
  return async (source: string): Promise<ExecutionResult> => {
    const response = await yoga.fetch(`${BASE_URL}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: source }),
    });
    return (await response.json()) as ExecutionResult;
  };
}

const LOGIN = /* GraphQL */ `
  mutation {
    customerAccessTokenCreate(input: { email: "jane.doe@example.com", password: "password123" }) {
      customerAccessToken { accessToken expiresAt }
      customerUserErrors { code field message }
    }
  }
`;

async function login(run: ReturnType<typeof runWith>): Promise<string> {
  const result = await run(LOGIN);
  const payload = (
    result.data as { customerAccessTokenCreate: { customerAccessToken: { accessToken: string } } }
  ).customerAccessTokenCreate;
  return payload.customerAccessToken.accessToken;
}

let state: ShopState;
let run: ReturnType<typeof runWith>;

beforeEach(() => {
  state = new ShopState(data, 'test');
  run = runWith(state);
});

describe('customerCreate', () => {
  it('creates an account and returns the customer', async () => {
    const result = await run(/* GraphQL */ `
      mutation {
        customerCreate(input: { email: "sam@example.com", password: "hunter22", firstName: "Sam", lastName: "Buyer" }) {
          customer { id email displayName acceptsMarketing createdAt numberOfOrders }
          customerUserErrors { code }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      customerCreate: {
        customer: {
          id: 'gid://shopify/Customer/5',
          email: 'sam@example.com',
          displayName: 'Sam Buyer',
          acceptsMarketing: false,
          createdAt: '2026-01-01T00:00:01.000Z',
          numberOfOrders: 0,
        },
        customerUserErrors: [],
      },
    });
    expect(state.findCustomerByEmail('sam@example.com')).toBeDefined();
  });

  it('reports TAKEN and TOO_SHORT without creating anything', async () => {
    const result = await run(/* GraphQL */ `
      mutation {
        customerCreate(input: { email: "jane.doe@example.com", password: "abc" }) {
          customer { id }
          customerUserErrors { code field }
        }
      }
    `);
    expect(result.data).toEqual({
      customerCreate: {
        customer: null,
        customerUserErrors: [
          { code: 'TAKEN', field: ['input', 'email'] },
          { code: 'TOO_SHORT', field: ['input', 'password'] },
        ],
      },
    });
    expect(state.listCustomers()).toHaveLength(4);
  });
});

describe('customerAccessTokenCreate / Delete', () => {
  it('mints a deterministic token for valid credentials', async () => {
    const result = await run(LOGIN);
    expect(result.data).toEqual({
      customerAccessTokenCreate: {
        customerAccessToken: {
          accessToken: 'sandbox-token-1',
          expiresAt: '2026-01-15T00:00:01.000Z',
        },
        customerUserErrors: [],
      },
    });
  });

  it('rejects a wrong password with UNIDENTIFIED_CUSTOMER', async () => {
    const result = await run(/* GraphQL */ `
      mutation {
        customerAccessTokenCreate(input: { email: "jane.doe@example.com", password: "nope" }) {
          customerAccessToken { accessToken }
          customerUserErrors { code }
        }
      }
    `);
    expect(result.data).toEqual({
      customerAccessTokenCreate: {
        customerAccessToken: null,
        customerUserErrors: [{ code: 'UNIDENTIFIED_CUSTOMER' }],
      },
    });
  });

  it('revokes the token so customer(token) resolves to null', async () => {
    const token = await login(run);
    const deleted = await run(/* GraphQL */ `
      mutation {
        customerAccessTokenDelete(customerAccessToken: "${token}") {
          deletedAccessToken
          userErrors { message }
        }
      }
    `);
    expect(deleted.data).toEqual({
      customerAccessTokenDelete: { deletedAccessToken: token, userErrors: [] },
    });
    const after = await run(/* GraphQL */ `{ customer(customerAccessToken: "${token}") { id } }`);
    expect(after.data).toEqual({ customer: null });
  });
});

describe('Query.customer', () => {
  it('returns the profile, addresses, and order history for a live token', async () => {
    const token = await login(run);
    const result = await run(/* GraphQL */ `
      {
        customer(customerAccessToken: "${token}") {
          id
          displayName
          phone
          numberOfOrders
          defaultAddress { id formatted provinceCode countryCodeV2 }
          addresses(first: 5) { nodes { address1 } }
          orders(first: 5) {
            totalCount
            nodes {
              id name orderNumber processedAt financialStatus fulfillmentStatus
              totalPrice { amount currencyCode }
              lineItems(first: 5) { nodes { title quantity variant { id } originalTotalPrice { amount } } }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      customer: {
        id: 'gid://shopify/Customer/1',
        displayName: 'Jane Doe',
        phone: '+16135550123',
        numberOfOrders: 1,
        defaultAddress: {
          id: 'gid://shopify/MailingAddress/1',
          formatted: ['Jane Doe', '123 Bank Street', 'Apt 4', 'Ottawa ON K2P 1X3', 'Canada'],
          provinceCode: 'ON',
          countryCodeV2: 'CA',
        },
        addresses: { nodes: [{ address1: '123 Bank Street' }] },
        orders: {
          totalCount: 1,
          nodes: [
            {
              id: 'gid://shopify/Order/1001',
              name: '#1001',
              orderNumber: 1001,
              processedAt: '2025-07-01T16:05:00.000Z',
              financialStatus: 'PAID',
              fulfillmentStatus: 'FULFILLED',
              totalPrice: { amount: '29.98', currencyCode: 'CAD' },
              lineItems: {
                nodes: [
                  {
                    title: 'Shopliseum Mushroom Dog Toys - Red Mushroom',
                    quantity: 1,
                    variant: { id: 'gid://shopify/ProductVariant/47242666836142' },
                    originalTotalPrice: { amount: '19.99' },
                  },
                ],
              },
            },
          ],
        },
      },
    });
  });

  it('returns null for an unknown token', async () => {
    const result = await run(/* GraphQL */ `{ customer(customerAccessToken: "bogus") { id } }`);
    expect(result.data).toEqual({ customer: null });
  });
});

describe('cartBuyerIdentityUpdate with customerAccessToken', () => {
  it('associates the cart with the logged-in customer', async () => {
    const token = await login(run);
    const cart = state.carts.create({});
    const result = await run(/* GraphQL */ `
      mutation {
        cartBuyerIdentityUpdate(cartId: "${cart.id}", buyerIdentity: { customerAccessToken: "${token}" }) {
          cart { buyerIdentity { email customer { id displayName } } }
          userErrors { code }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      cartBuyerIdentityUpdate: {
        cart: {
          buyerIdentity: {
            email: 'jane.doe@example.com',
            customer: { id: 'gid://shopify/Customer/1', displayName: 'Jane Doe' },
          },
        },
        userErrors: [],
      },
    });
    expect(cart.buyerIdentity.customerId).toBe(1);
  });

  it('rejects an invalid token and leaves the cart anonymous', async () => {
    const cart = state.carts.create({});
    const result = await run(/* GraphQL */ `
      mutation {
        cartBuyerIdentityUpdate(cartId: "${cart.id}", buyerIdentity: { customerAccessToken: "expired" }) {
          cart { buyerIdentity { customer { id } } }
          userErrors { code field }
        }
      }
    `);
    expect(result.data).toEqual({
      cartBuyerIdentityUpdate: {
        cart: { buyerIdentity: { customer: null } },
        userErrors: [{ code: 'INVALID', field: ['buyerIdentity', 'customerAccessToken'] }],
      },
    });
  });
});
