/**
 * Hosting smoke: boots the pristine backend template on the dataset and
 * runs a fixed set of Storefront API queries against it, ending with a
 * cart that is checked out as the first seeded customer.
 */

import { datasetSchema } from '@shop-gym/shop-backend';
import type { z } from 'zod';

import { type SidecarLaunch, freePort } from '../build/sidecar.js';
import { readJsonFile, readJsonIfExists } from '../io.js';

export interface HostingCheck {
  readonly name: string;
  readonly ok: boolean;
  readonly detail: string;
}

export interface HostingSmokeOptions {
  readonly dataDir: string;
  readonly backendDir: string;
  readonly logPath: string;
  readonly launch: SidecarLaunch;
  readonly healthTimeoutMs?: number;
}

export interface HostingSmokeResult {
  readonly port: number;
  readonly checks: readonly HostingCheck[];
}

type Customer = z.infer<typeof datasetSchema.customerSchema>;

class GraphqlClient {
  constructor(private readonly url: string) {}

  async query(
    query: string,
    variables: Record<string, unknown> = {},
  ): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.url}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, variables }),
    });
    const body = (await response.json()) as {
      data?: Record<string, unknown>;
      errors?: { message: string }[];
    };
    if (body.errors !== undefined && body.errors.length > 0) {
      throw new Error(body.errors.map((e) => e.message).join('; '));
    }
    if (body.data === undefined) throw new Error(`HTTP ${response.status} without data`);
    return body.data;
  }
}

function get(value: unknown, ...keys: (string | number)[]): unknown {
  let cur: unknown = value;
  for (const key of keys) {
    if (cur === null || typeof cur !== 'object') return undefined;
    cur = (cur as Record<string | number, unknown>)[key];
  }
  return cur;
}

async function check(name: string, fn: () => Promise<string>): Promise<HostingCheck> {
  try {
    return { name, ok: true, detail: await fn() };
  } catch (err) {
    return { name, ok: false, detail: err instanceof Error ? err.message : String(err) };
  }
}

async function cartLifecycle(
  gql: GraphqlClient,
  variantId: string,
  customer: Customer | undefined,
): Promise<string> {
  let token: string | undefined;
  if (customer !== undefined) {
    const login = await gql.query(
      'mutation($input: CustomerAccessTokenCreateInput!) { customerAccessTokenCreate(input: $input) { customerAccessToken { accessToken } customerUserErrors { message } } }',
      { input: { email: customer.email, password: customer.password } },
    );
    token = get(login, 'customerAccessTokenCreate', 'customerAccessToken', 'accessToken') as
      | string
      | undefined;
    if (token === undefined)
      throw new Error(`login failed for ${customer.email}: ${JSON.stringify(login)}`);
  }
  const created = await gql.query(
    'mutation { cartCreate(input: {}) { cart { id } userErrors { message } } }',
  );
  const cartId = get(created, 'cartCreate', 'cart', 'id');
  if (typeof cartId !== 'string')
    throw new Error(`cartCreate returned no cart: ${JSON.stringify(created)}`);
  const added = await gql.query(
    'mutation($cartId: ID!, $lines: [CartLineInput!]!) { cartLinesAdd(cartId: $cartId, lines: $lines) { cart { totalQuantity } userErrors { message } } }',
    { cartId, lines: [{ merchandiseId: variantId, quantity: 1 }] },
  );
  if (get(added, 'cartLinesAdd', 'cart', 'totalQuantity') !== 1) {
    throw new Error(`cartLinesAdd did not add the line: ${JSON.stringify(added)}`);
  }
  if (customer !== undefined && token !== undefined) {
    await gql.query(
      'mutation($cartId: ID!, $buyer: CartBuyerIdentityInput!) { cartBuyerIdentityUpdate(cartId: $cartId, buyerIdentity: $buyer) { cart { id } userErrors { message } } }',
      { cartId, buyer: { customerAccessToken: token, email: customer.email } },
    );
  }
  const address = customer?.addresses[0];
  const completed = await gql.query(
    'mutation($cartId: ID!, $input: CheckoutCompleteInput!) { checkoutComplete(cartId: $cartId, input: $input) { order { id name totalPrice { amount } } userErrors { message } } }',
    {
      cartId,
      input: {
        email: customer?.email ?? 'guest@example.com',
        shippingAddress: {
          firstName: address?.first_name ?? 'Test',
          lastName: address?.last_name ?? 'Shopper',
          address1: address?.address1 ?? '1 Example Street',
          city: address?.city ?? 'Exampleville',
          province: address?.province ?? '',
          country: address?.country ?? 'Exampleland',
          zip: address?.zip ?? '00000',
        },
      },
    },
  );
  const order = get(completed, 'checkoutComplete', 'order');
  if (order === null || order === undefined) {
    throw new Error(
      `checkoutComplete returned no order: ${JSON.stringify(get(completed, 'checkoutComplete', 'userErrors'))}`,
    );
  }
  return `order ${String(get(order, 'name'))} total ${String(get(order, 'totalPrice', 'amount'))}${customer === undefined ? ' (guest)' : ` as ${customer.email}`}`;
}

export async function runHostingSmoke(options: HostingSmokeOptions): Promise<HostingSmokeResult> {
  const store = await readJsonFile(`${options.dataDir}/store.json`, datasetSchema.storeSchema);
  const products = await readJsonFile(
    `${options.dataDir}/products.json`,
    datasetSchema.productsFileSchema,
  );
  const collections = await readJsonFile(
    `${options.dataDir}/collections.json`,
    datasetSchema.collectionsFileSchema,
  );
  const customers =
    (await readJsonIfExists(
      `${options.dataDir}/customers.json`,
      datasetSchema.customersFileSchema,
    )) ?? [];
  const port = await freePort();
  const url = `http://127.0.0.1:${port}`;
  const sidecar = await options.launch({
    backendDir: options.backendDir,
    dataDir: options.dataDir,
    port,
    url,
    logPath: options.logPath,
    healthTimeoutMs: options.healthTimeoutMs ?? 60_000,
  });
  const gql = new GraphqlClient(url);
  const checks: HostingCheck[] = [];
  try {
    checks.push(
      await check('shop', async () => {
        const data = await gql.query('{ shop { name } }');
        const name = get(data, 'shop', 'name');
        if (name !== store.name)
          throw new Error(`shop.name is ${String(name)}, expected ${store.name}`);
        return `shop.name = ${store.name}`;
      }),
    );
    let variantId: string | undefined;
    checks.push(
      await check('products', async () => {
        const data = await gql.query(
          '{ products(first: 5) { edges { node { handle variants(first: 10) { edges { node { id availableForSale } } } } } } }',
        );
        const edges = get(data, 'products', 'edges');
        if (!Array.isArray(edges) || edges.length === 0)
          throw new Error('products(first: 5) returned no edges');
        const variants = edges.flatMap(
          (e) => (get(e, 'node', 'variants', 'edges') as unknown[]) ?? [],
        );
        const pick =
          variants.find((v) => get(v, 'node', 'availableForSale') === true) ?? variants[0];
        variantId = get(pick, 'node', 'id') as string | undefined;
        return `${edges.length} products, first variant ${variantId ?? 'none'}`;
      }),
    );
    const firstCollection = collections[0];
    checks.push(
      await check('collection', async () => {
        if (firstCollection === undefined) throw new Error('collections.json is empty');
        const data = await gql.query(
          'query($handle: String!) { collection(handle: $handle) { handle products(first: 3) { edges { node { handle } } } } }',
          { handle: firstCollection.handle },
        );
        if (get(data, 'collection', 'handle') !== firstCollection.handle) {
          throw new Error(`collection(handle: ${firstCollection.handle}) not found`);
        }
        return `collection ${firstCollection.handle} resolves`;
      }),
    );
    const term =
      products[0]?.title.split(/\s+/).find((w) => w.length >= 3) ?? products[0]?.title ?? '';
    checks.push(
      await check('search', async () => {
        const data = await gql.query(
          'query($q: String!) { search(query: $q, first: 5) { edges { node { ... on Product { handle } } } } }',
          { q: term },
        );
        const edges = get(data, 'search', 'edges');
        if (!Array.isArray(edges) || edges.length === 0)
          throw new Error(`search(${JSON.stringify(term)}) returned nothing`);
        return `search(${JSON.stringify(term)}) -> ${edges.length} results`;
      }),
    );
    const image = products.flatMap((p) => p.images)[0];
    checks.push(
      await check('image', async () => {
        if (image === undefined) return 'no product images';
        const rel = image.src.replace(/^\/?images\//, '');
        const response = await fetch(`${url}/images/${rel}`);
        if (!response.ok) throw new Error(`GET /images/${rel} -> HTTP ${response.status}`);
        return `GET /images/${rel} -> ${response.status}`;
      }),
    );
    checks.push(
      await check('cart_lifecycle', () => {
        if (variantId === undefined) throw new Error('no variant id from the products check');
        return cartLifecycle(gql, variantId, customers[0]);
      }),
    );
  } finally {
    await sidecar.stop();
  }
  return { port, checks };
}
