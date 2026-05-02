# ShopBackend

Local GraphQL server that backs **SandboxShop** sandboxes.

Used for benchmarking shopping LLM agents and as the planned host of an RL
environment. Spec:
[`docs/specs/shop_backend/storefront_api.md`](../../docs/specs/shop_backend/storefront_api.md).

## Status

v0.1 (M1–M6 landed). Boots against a SandboxShop dataset directory and
answers canonical Storefront-API queries across `shop`, `product`,
`collection`, `menu`, `page`, `blog`, `search`, `predictiveSearch`,
`localization`, plus a full cart lifecycle (`cartCreate` → `cartLinesAdd` →
`cartLinesUpdate` → `cartLinesRemove`). v0.2 follow-ups (resolver codegen,
inventory queries, `@inContext` enforcement) tracked in
[`docs/impl/storefront_api_implementation.md`](../../docs/impl/storefront_api_implementation.md).

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

CORS allows `*` origins.

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

By default the cart store lives in-memory only — restarting the server
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

A SandboxShop dataset is a directory containing the JSON files defined in
[spec §8.1](../../docs/specs/shop_backend/storefront_api.md#81-sandboxshop-dataset-schema-v01).
Required: `store.json`, `products.json`, `collections.json`,
`navigation.json`, `pages.json`, `policies.json`. Optional: `blogs.json`,
`metafields.json`. Image assets live under `<data-dir>/images/` and are
served at `/images/<path>`.

Datasets are produced by ShopArena's `shop_gen` module.

## Library API

```ts
import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';

const dataDir = './outputs/shops/example/data';
const data = loadShopData(dataDir);
const server = createSandboxServer({ data, dataDir });
await server.listen();
console.log(server.url); // http://127.0.0.1:4000/graphql
```

## Build & test

```bash
pnpm --filter @shop-gym/shop-backend build
pnpm --filter @shop-gym/shop-backend test
```
