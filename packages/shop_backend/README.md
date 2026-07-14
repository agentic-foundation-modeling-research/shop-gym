# ShopBackend

Local GraphQL server that backs **SandboxShop** sandboxes.

ShopBackend loads one synthesized storefront dataset and exposes a
Storefront-API-compatible GraphQL surface for generated Hydrogen storefronts,
shopping-agent benchmarks, and local environment validation.

## Status

Implemented as a TypeScript ESM package. The server boots against a
SandboxShop dataset directory, serves dataset images, and answers canonical
Storefront API queries across shop metadata, menus, products, variants,
collections, content, search, predictive search, localization, product
recommendations, metafields, and cart state.

The current GraphQL contract is the SDL in `src/schema.ts`. It includes:

| Area | Surface |
| --- | --- |
| Shop | `shop`, `Shop.paymentSettings`, `Shop.primaryDomain`, `Shop.brand`, policies, `Shop.metafield(s)` |
| Menu | `menu(handle)` |
| Product | `product(handle)`, `products(...)`, product options, variants, images, encoded variant fields, inventory-backed `availableForSale` / `quantityAvailable`, `Product.metafield(s)` |
| Collection | `collection(handle)`, `collections(...)`, `Collection.products(...)`, `Collection.metafield(s)` |
| Content | `page(handle)`, `blog(handle)`, `blogs(...)`, `Blog.articles(...)`, `Blog.articleByHandle(...)` |
| Search | `search(...)`, `predictiveSearch(...)`, `productRecommendations(productId)` |
| Localization | `localization`, plus validation for literal `@inContext(country:, language:)` values |
| Cart | `cart(id)` and cart mutations for create, line add/update/remove, discount codes, buyer identity, note, attributes, and gift-card codes |

The server is deterministic and read-mostly. Cart state is mutable per server
instance, in-memory by default, and optionally persisted with `--cart-store`.
There is no Admin API, checkout/payment, customer account auth, order surface,
webhook support, or Storefront access-token validation.

## Install (dev)

```bash
pnpm install
```

## Usage

Boot against the bundled fixture (run from the package directory; no build
step required):

```bash
pnpm --filter @shop-gym/shop-backend shop-backend \
  tests/fixtures/sandbox_shop_v0 4000
```

The CLI prints loaded counts on startup and binds:

| Path                                | Behavior                                                |
| ----------------------------------- | ------------------------------------------------------- |
| `POST /graphql`                     | GraphQL endpoint.                                       |
| `POST /api/<version>/graphql.json`  | Rewritten to `/graphql` for versioned clients.          |
| `GET /images/<path>`                | Static images under `<data-dir>/images/`.               |
| `GET /health`                       | `200 {"status":"ok","store":"<name>"}`.                 |

`/images/*` serves PNG, JPG, JPEG, WEBP, and SVG files with immutable cache
headers and strips query strings before filesystem lookup. GraphQL CORS allows
any origin for `POST` / `OPTIONS` requests with the `Content-Type` header.

### Example query

With the server above running on port 4000:

```bash
curl -s -X POST http://127.0.0.1:4000/graphql \
  -H 'content-type: application/json' \
  -d '{"query":"{ shop { name paymentSettings { currencyCode } } products(first: 2) { nodes { handle title priceRange { minVariantPrice { amount currencyCode } } } } collection(handle: \"dog-essentials\") { title products(first: 2) { nodes { handle } } } }"}'
```

Returns the `Mock Pet Foods` shop, the first two products, and the
`dog-essentials` collection's members. The same multi-area query is
exercised end-to-end in `src/storefront_api.e2e.test.ts`.

### Persisted carts

By default the cart store lives in-memory only. Restarting the server
resets every cart to "not found". Pass `--cart-store <path>` to back the
store with a JSON snapshot file:

```bash
pnpm --filter @shop-gym/shop-backend shop-backend \
  tests/fixtures/sandbox_shop_v0 4000 \
  --cart-store ./outputs/cart-store.json
```

The file is rewritten synchronously after every cart mutation. Pointing a
later run at the same path rehydrates carts (and the cart-id counter) so
ids minted in run A remain queryable from run B.

## Dataset layout

`loadShopData(dir)` reads one snapshot from a SandboxShop dataset directory.
Missing required files or malformed optional files fail startup.

Required files:

| File | Contents |
| --- | --- |
| `store.json` | Store identity, domain, description, currency, country, payment settings, and brand colors |
| `products.json` | Products, options, variants, images, prices, tags, timestamps, and availability fallback flags |
| `collections.json` | Collections and ordered product-handle membership |
| `navigation.json` | Menu handles mapped to nested navigation items |
| `pages.json` | Static pages |
| `policies.json` | Store policies |

Optional files:

| File | Default | Used for |
| --- | --- | --- |
| `blogs.json` | `[]` | Blogs, articles, article search results, and predictive search articles |
| `metafields.json` | `{ shop: [], products: {}, collections: {} }` | Shop, product, and collection metafield resolvers |
| `inventory.json` | `{}` | Per-variant `quantityAvailable` and inventory-backed availability |

Image assets may live under `<data-dir>/images/` and are served at
`/images/<path>`. Product image `src` values can be absolute URLs or relative
image paths; relative paths are rewritten to same-origin `/images/*` URLs at
resolve time. For older local storefront artifacts that cannot serve
same-origin `/images/*`, start the server with `--image-url-mode absolute` to
return backend-origin image URLs instead.

Datasets are produced by ShopArena's generation pipeline and consumed as a
frozen snapshot for the lifetime of the server instance.

## Library API

```ts
import {
  createSandboxSchema,
  createSandboxServer,
  loadShopData,
} from '@shop-gym/shop-backend';

const dataDir = './outputs/shops/example/data';
const data = loadShopData(dataDir);
const server = createSandboxServer({ data, dataDir });
await server.listen();
console.log(server.url); // http://127.0.0.1:4000/graphql
```

Public exports include `loadShopData`, `createSandboxSchema`,
`createSandboxServer`, `SandboxShopData`, `ServerOptions`, `SandboxServer`, and
the primary dataset entity types used by the loader.

## Build & test

```bash
pnpm --filter @shop-gym/shop-backend build
pnpm --filter @shop-gym/shop-backend test
```
