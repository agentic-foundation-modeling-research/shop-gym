/**
 * End-to-end M6 acceptance test (T6.4).
 *
 * Boots `createSandboxServer` against the v0.1 fixture and drives the full
 * Storefront-API subset enumerated in
 * `docs/specs/shop_backend/storefront_api.md` §5.2 over real HTTP — every area
 * is hit with a canonical query in one round-trip:
 *
 *   - **Shop / Menu / Localization**: `Query.shop` (incl. `paymentSettings`,
 *     `primaryDomain`, `brand.colors`, and `privacyPolicy`), `Query.menu`,
 *     `Query.localization`.
 *   - **Product / Collection**: `Query.product`, `Query.products`,
 *     `Query.productRecommendations`, `Query.collection`, `Query.collections`.
 *   - **Content**: `Query.page`, `Query.blog`, `Query.blogs`.
 *   - **Search**: `Query.search`, `Query.predictiveSearch`.
 *   - **Cart**: full mutation lifecycle (`cartCreate` → `cartLinesAdd` →
 *     `cartLinesUpdate(quantity:0)` → `cartLinesRemove`) followed by a
 *     terminal `Query.cart` round-trip.
 *   - **Metafields**: `Product.metafield` and `Collection.metafields` against
 *     the fixture's `metafields.json` entries.
 *
 * The static image asset surface (spec §5.4) is exercised separately:
 *
 *   - `GET /images/pixel.png` returns the file with the spec MIME type and
 *     immutable cache headers (satisfies SC5).
 *   - `Product.featuredImage.url` rewrites the dataset's relative `src` to
 *     the public `<baseUrl>/images/<src>` route (spec §5.3).
 *
 * Together these exercise SC1 (loader), SC2 (every §5.2 area answers a
 * canonical query), SC3 (cart lifecycle), SC5 (image asset), and SC6 (this
 * file is checked by `tsc --strict` + `biome check` along with the rest of
 * the package). SC4 — versioned `/api/<v>/graphql.json` routing — is covered
 * by `server.test.ts`; this suite does not duplicate it.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { loadShopData } from './data/loader.js';
import { type SandboxServer, createSandboxServer } from './server.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../tests/fixtures/sandbox_shop_v0',
);

const AISLEARENA_VARIANT = 'gid://shopgym/ProductVariant/47642512195758'; // $79.99
const SHOPLISEUM_VARIANT = 'gid://shopgym/ProductVariant/47242666836142'; // $19.99
const CARTHAEUM_VARIANT = 'gid://shopgym/ProductVariant/47694728298670'; // $12.99

interface GraphQLResponse<T> {
  readonly data?: T;
  readonly errors?: readonly unknown[];
}

async function gql<T>(url: string, query: string): Promise<GraphQLResponse<T>> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  return (await response.json()) as GraphQLResponse<T>;
}

describe('Storefront API — end-to-end (M6 acceptance, T6.4)', () => {
  const data = loadShopData(FIXTURE_DIR);
  let server: SandboxServer;
  let baseUrl: string;

  beforeAll(async () => {
    server = createSandboxServer({ data, dataDir: FIXTURE_DIR, port: 0 });
    await server.listen();
    baseUrl = server.url.replace(/\/graphql$/, '');
  });

  afterAll(async () => {
    await server.close();
  });

  it('answers one canonical query covering every §5.2 read area', async () => {
    interface Result {
      readonly shop: {
        readonly name: string;
        readonly description: string;
        readonly primaryDomain: { readonly host: string; readonly url: string };
        readonly paymentSettings: {
          readonly currencyCode: string;
          readonly countryCode: string;
          readonly acceptedCardBrands: readonly string[];
        };
        readonly brand: {
          readonly colors: {
            readonly primary: ReadonlyArray<{
              readonly background: string;
              readonly foreground: string;
            }>;
          };
        };
        readonly privacyPolicy: { readonly handle: string; readonly title: string } | null;
      };
      readonly menu: {
        readonly handle: string;
        readonly items: ReadonlyArray<{ readonly title: string; readonly type: string }>;
      } | null;
      readonly localization: {
        readonly country: { readonly isoCode: string; readonly currency: { readonly isoCode: string } };
        readonly language: { readonly isoCode: string };
      };
      readonly product: {
        readonly handle: string;
        readonly title: string;
        readonly availableForSale: boolean;
        readonly featuredImage: { readonly url: string } | null;
        readonly priceRange: { readonly minVariantPrice: { readonly amount: string } };
        readonly metafield: { readonly namespace: string; readonly value: string } | null;
      } | null;
      readonly products: {
        readonly totalCount: number;
        readonly nodes: ReadonlyArray<{ readonly handle: string }>;
      };
      readonly productRecommendations: ReadonlyArray<{ readonly handle: string }> | null;
      readonly collection: {
        readonly handle: string;
        readonly title: string;
        readonly products: { readonly nodes: ReadonlyArray<{ readonly handle: string }> };
        readonly metafields: ReadonlyArray<{
          readonly namespace: string;
          readonly key: string;
          readonly value: string;
        } | null>;
      } | null;
      readonly collections: { readonly nodes: ReadonlyArray<{ readonly handle: string }> };
      readonly page: { readonly handle: string; readonly title: string } | null;
      readonly blog: {
        readonly handle: string;
        readonly articles: { readonly nodes: ReadonlyArray<{ readonly handle: string }> };
      } | null;
      readonly blogs: { readonly nodes: ReadonlyArray<{ readonly handle: string }> };
      readonly search: {
        readonly totalCount: number;
        readonly nodes: ReadonlyArray<{ readonly __typename: string }>;
      };
      readonly predictiveSearch: {
        readonly products: ReadonlyArray<{ readonly handle: string }>;
        readonly queries: ReadonlyArray<{ readonly text: string }>;
      } | null;
    }

    const query = /* GraphQL */ `
      {
        shop {
          name
          description
          primaryDomain { host url }
          paymentSettings { currencyCode countryCode acceptedCardBrands }
          brand { colors { primary { background foreground } } }
          privacyPolicy { handle title }
        }
        menu(handle: "main-menu") {
          handle
          items { title type }
        }
        localization {
          country { isoCode currency { isoCode } }
          language { isoCode }
        }
        product(handle: "agoracage-skin-and-coat-chicken-with-grains-12lb") {
          handle
          title
          availableForSale
          featuredImage { url }
          priceRange { minVariantPrice { amount } }
          metafield(namespace: "specs", key: "protein_source") {
            namespace
            value
          }
        }
        products(first: 3) {
          totalCount
          nodes { handle }
        }
        productRecommendations(productId: "gid://shopgym/Product/9061637816494") {
          handle
        }
        collection(handle: "dog-essentials") {
          handle
          title
          products(first: 2) { nodes { handle } }
          metafields(identifiers: [
            { namespace: "merch", key: "hero_color" }
            { namespace: "merch", key: "missing" }
          ]) {
            namespace
            key
            value
          }
        }
        collections(first: 5) { nodes { handle } }
        page(handle: "about-us") { handle title }
        blog(handle: "news") {
          handle
          articles(first: 5) { nodes { handle } }
        }
        blogs(first: 5) { nodes { handle } }
        search(query: "dog", first: 5) {
          totalCount
          nodes { __typename }
        }
        predictiveSearch(query: "dog", limit: 3) {
          products { handle }
          queries { text }
        }
      }
    `;

    const result = await gql<Result>(server.url, query);
    expect(result.errors).toBeUndefined();
    const body = result.data;
    if (body === undefined) throw new Error('expected data');

    // Shop area.
    expect(body.shop.name).toBe('Mock Pet Foods');
    expect(body.shop.description).toContain('Mock Pet Foods');
    expect(body.shop.primaryDomain.host).toBe('mock-pet-foods.example');
    expect(body.shop.primaryDomain.url).toBe('https://mock-pet-foods.example');
    expect(body.shop.paymentSettings.currencyCode).toBe('CAD');
    expect(body.shop.paymentSettings.countryCode).toBe('CA');
    expect(body.shop.paymentSettings.acceptedCardBrands).toEqual([
      'VISA',
      'MASTER',
      'AMERICAN_EXPRESS',
    ]);
    expect(body.shop.brand.colors.primary[0]).toEqual({
      background: '#1f6f43',
      foreground: '#f3e9d2',
    });
    expect(body.shop.privacyPolicy).toEqual({
      handle: 'privacy-policy',
      title: 'Privacy Policy',
    });

    // Menu area.
    expect(body.menu?.handle).toBe('main-menu');
    expect(body.menu?.items.map((item) => item.title)).toEqual(['Shop Dogs', 'Shop Cats', 'About']);

    // Localization area.
    expect(body.localization.country.isoCode).toBe('CA');
    expect(body.localization.country.currency.isoCode).toBe('CAD');
    expect(body.localization.language.isoCode).toBe('EN');

    // Product area — including metafield + image URL rewrite.
    expect(body.product?.handle).toBe('agoracage-skin-and-coat-chicken-with-grains-12lb');
    expect(body.product?.availableForSale).toBe(true);
    expect(body.product?.priceRange.minVariantPrice.amount).toBe('54.99');
    expect(body.product?.featuredImage?.url).toBe(
      `${baseUrl}/images/products/agoracage-skin-and-coat-chicken-with-grains-12lb-1.jpg`,
    );
    expect(body.product?.metafield).toEqual({ namespace: 'specs', value: 'chicken' });

    expect(body.products.totalCount).toBe(5);
    expect(body.products.nodes.map((node) => node.handle)).toEqual([
      'aislearena-anti-tick-collar',
      'shopliseum-mushroom-dog-toys',
      'agoracage-skin-and-coat-chicken-with-grains-12lb',
    ]);

    // productRecommendations excludes the requesting product.
    const recHandles = body.productRecommendations?.map((r) => r.handle) ?? [];
    expect(recHandles).not.toContain('carthaeum-toothbrush');
    expect(recHandles.length).toBeGreaterThan(0);

    // Collection area — including order-preserving metafields with a miss.
    expect(body.collection?.handle).toBe('dog-essentials');
    expect(body.collection?.products.nodes.map((node) => node.handle)).toEqual([
      'shopliseum-mushroom-dog-toys',
      'agoracage-skin-and-coat-chicken-with-grains-12lb',
    ]);
    expect(body.collection?.metafields[0]).toEqual({
      namespace: 'merch',
      key: 'hero_color',
      value: '#1f513f',
    });
    expect(body.collection?.metafields[1]).toBeNull();

    expect(body.collections.nodes.map((node) => node.handle)).toEqual([
      'dog-essentials',
      'cat-care',
    ]);

    // Content area.
    expect(body.page).toEqual({ handle: 'about-us', title: 'Our Story' });
    expect(body.blog?.handle).toBe('news');
    expect(body.blog?.articles.nodes.map((article) => article.handle)).toEqual(['welcome-post']);
    expect(body.blogs.nodes.map((node) => node.handle)).toEqual(['news']);

    // Search area.
    expect(body.search.totalCount).toBeGreaterThan(0);
    expect(body.search.nodes.length).toBeGreaterThan(0);
    expect(body.search.nodes.every((node) => node.__typename === 'Product')).toBe(true);

    expect(body.predictiveSearch?.products.length).toBeGreaterThan(0);
    expect(body.predictiveSearch?.queries[0]?.text).toBe('dog');
  });

  it('round-trips the full cart lifecycle: create → add → update(0) → remove (SC3)', async () => {
    interface CartLineSummary {
      readonly id: string;
      readonly quantity: number;
      readonly merchandise: { readonly id: string };
    }
    interface CartSummary {
      readonly id: string;
      readonly totalQuantity: number;
      readonly cost: { readonly subtotalAmount: { readonly amount: string; readonly currencyCode: string } };
      readonly lines: { readonly nodes: readonly CartLineSummary[] };
    }

    interface CreatePayload {
      readonly cartCreate: { readonly cart: CartSummary | null };
    }
    interface AddPayload {
      readonly cartLinesAdd: { readonly cart: CartSummary | null };
    }
    interface UpdatePayload {
      readonly cartLinesUpdate: { readonly cart: CartSummary | null };
    }
    interface RemovePayload {
      readonly cartLinesRemove: { readonly cart: CartSummary | null };
    }
    interface CartLookupPayload {
      readonly cart: CartSummary | null;
    }

    const cartFragment = /* GraphQL */ `
      cart {
        id
        totalQuantity
        cost { subtotalAmount { amount currencyCode } }
        lines(first: 10) {
          nodes {
            ... on CartLine {
              id
              quantity
              merchandise { ... on ProductVariant { id } }
            }
          }
        }
      }
    `;

    // 1. cartCreate with two starting lines.
    const create = await gql<CreatePayload>(
      server.url,
      /* GraphQL */ `
        mutation {
          cartCreate(input: {
            lines: [
              { merchandiseId: "${AISLEARENA_VARIANT}", quantity: 1 }
              { merchandiseId: "${SHOPLISEUM_VARIANT}", quantity: 2 }
            ]
          }) { ${cartFragment} }
        }
      `,
    );
    expect(create.errors).toBeUndefined();
    const created = create.data?.cartCreate.cart;
    if (!created) throw new Error('expected cart');
    expect(created.totalQuantity).toBe(3);
    // 1 * 79.99 + 2 * 19.99 = 119.97.
    expect(created.cost.subtotalAmount).toEqual({ amount: '119.97', currencyCode: 'CAD' });
    expect(created.lines.nodes).toHaveLength(2);
    const aisleArenaLineId = created.lines.nodes[0]?.id;
    const shopliseumLineId = created.lines.nodes[1]?.id;
    if (aisleArenaLineId === undefined || shopliseumLineId === undefined) {
      throw new Error('unreachable: cart should have two lines');
    }

    // 2. cartLinesAdd: AISLEARENA merges, CARTHAEUM appends.
    const add = await gql<AddPayload>(
      server.url,
      /* GraphQL */ `
        mutation {
          cartLinesAdd(
            cartId: "${created.id}"
            lines: [
              { merchandiseId: "${AISLEARENA_VARIANT}", quantity: 2 }
              { merchandiseId: "${CARTHAEUM_VARIANT}", quantity: 1 }
            ]
          ) { ${cartFragment} }
        }
      `,
    );
    expect(add.errors).toBeUndefined();
    const added = add.data?.cartLinesAdd.cart;
    if (!added) throw new Error('expected cart');
    // AISLEARENA qty=3, SHOPLISEUM qty=2, CARTHAEUM qty=1.
    expect(added.totalQuantity).toBe(6);
    expect(added.cost.subtotalAmount.amount).toBe('292.94');
    expect(added.lines.nodes).toHaveLength(3);
    expect(added.lines.nodes[0]?.id).toBe(aisleArenaLineId); // merged keeps original id
    expect(added.lines.nodes[0]?.quantity).toBe(3);

    // 3. cartLinesUpdate(quantity: 0) drops SHOPLISEUM.
    const update = await gql<UpdatePayload>(
      server.url,
      /* GraphQL */ `
        mutation {
          cartLinesUpdate(
            cartId: "${created.id}"
            lines: [{ id: "${shopliseumLineId}", quantity: 0 }]
          ) { ${cartFragment} }
        }
      `,
    );
    expect(update.errors).toBeUndefined();
    const updated = update.data?.cartLinesUpdate.cart;
    if (!updated) throw new Error('expected cart');
    expect(updated.totalQuantity).toBe(4);
    expect(updated.lines.nodes).toHaveLength(2);
    expect(updated.lines.nodes.some((line) => line.id === shopliseumLineId)).toBe(false);

    // 4. cartLinesRemove drops AISLEARENA.
    const remove = await gql<RemovePayload>(
      server.url,
      /* GraphQL */ `
        mutation {
          cartLinesRemove(cartId: "${created.id}", lineIds: ["${aisleArenaLineId}"]) {
            ${cartFragment}
          }
        }
      `,
    );
    expect(remove.errors).toBeUndefined();
    const removed = remove.data?.cartLinesRemove.cart;
    if (!removed) throw new Error('expected cart');
    expect(removed.totalQuantity).toBe(1);
    expect(removed.lines.nodes).toHaveLength(1);
    expect(removed.lines.nodes[0]?.merchandise.id).toBe(CARTHAEUM_VARIANT);

    // 5. Query.cart resolves the same id back with the surviving state.
    const lookup = await gql<CartLookupPayload>(
      server.url,
      /* GraphQL */ `
        {
          cart(id: "${created.id}") {
            id
            totalQuantity
            cost { subtotalAmount { amount currencyCode } }
            lines(first: 10) {
              nodes {
                ... on CartLine {
                  id
                  quantity
                  merchandise { ... on ProductVariant { id } }
                }
              }
            }
          }
        }
      `,
    );
    expect(lookup.errors).toBeUndefined();
    const persisted = lookup.data?.cart;
    if (!persisted) throw new Error('expected cart');
    expect(persisted.id).toBe(created.id);
    expect(persisted.totalQuantity).toBe(1);
    expect(persisted.lines.nodes[0]?.merchandise.id).toBe(CARTHAEUM_VARIANT);
  });

  it('serves /images/<file> with the spec MIME and cache headers (SC5)', async () => {
    const response = await fetch(`${baseUrl}/images/pixel.png`);
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('image/png');
    expect(response.headers.get('cache-control')).toBe('public, max-age=31536000');
    expect(response.headers.get('access-control-allow-origin')).toBe('*');

    const body = new Uint8Array(await response.arrayBuffer());
    // The committed PNG fixture is the smallest valid PNG (67 bytes); verify
    // the magic header so we know the actual file bytes were served.
    expect(body.byteLength).toBeGreaterThan(0);
    expect(Array.from(body.slice(0, 8))).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  });
});
