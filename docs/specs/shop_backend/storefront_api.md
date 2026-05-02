# ShopBackend Storefront API (`packages/shop_backend`)

Status: **Spec (proposed)** · Version: **0.1**
Owners: ShopBackend

> A local GraphQL API server that resolves against a **SandboxShop dataset**
> — a small bundle of synthesized JSON files describing one fake storefront.

---

## 1. Overview

`shop_backend` is the runtime that backs every SandboxShop instance.
Given a directory of synthesized JSON files (the SandboxShop dataset),
it exposes a graphql-yoga server hosting sandbox shop's data.

Two design choices define the module:

- **Synthesis-driven, not extraction-driven.** The server is the
  consumer of a SandboxShop dataset that ShopArena (`shop_arena.gen`)
  synthesizes. There is no ETL, no live BigQuery dependency, no Admin
  API scrape. The dataset shape is defined by this spec; ShopArena
  promises to produce it.
- **Read-mostly with a real cart.** Read paths (Shop, Product,
  Collection, Menu, Page, Search, PredictiveSearch, Localization) build
  GraphQL nodes on the fly from the loaded dataset. The cart is the
  only mutable surface: a per-server in-memory store with the standard
  `cartCreate` / `cartLines*` / `cartDiscountCodesUpdate` / etc.
  mutations.

`shop_backend` is the first server-side package in the repo that
benchmarks shopping LLM agents against a stable, deterministic
GraphQL surface, and it is the planned host of an RL environment.

---

## 2. Terminology

- **SandboxShop dataset** — a directory of JSON files describing one
  synthesized storefront. Authoritative shape is defined in §8.1.
  Produced by ShopArena `shop_arena.gen`; consumed by this server.
- **SandboxShop instance** — one running `shop_backend` server bound
  to a single dataset directory.
- **Storefront API** — Shopify's public GraphQL surface for buyer-side
  operations (shop, products, collections, cart, search). The subset
  this spec covers is enumerated in §5.2.
- **GID** — Shopify's global ID format, e.g.
  `gid://shopify/Product/9061637816494`. Generated deterministically
  from numeric ids in the dataset; hash-based for string keys.
- **Cart store** — the per-server in-memory `Map<cartId, Cart>` that
  holds mutable cart state for the lifetime of a server instance. Not
  persisted; cleared on `server.close()`.

---

## 3. Current Status

- `packages/shop_backend/` is scaffolded with graphql-yoga + vitest +
  biome, exposing a placeholder `Query.ping` schema (`src/schema.ts`,
  `src/server.ts`, `src/cli.ts`). No SandboxShop schema, no resolvers,
  no dataset loader.
- ShopArena `shop_arena.gen` does not yet emit a SandboxShop dataset; that
  spec lives separately. This spec defines the consumer contract that
  `shop_arena.gen` will target.

---

## 4. Desired Status

A self-contained TypeScript package under `packages/shop_backend/` that,
given a SandboxShop dataset directory, runs a graphql-yoga server
mirroring the Storefront API subset in §5.2 and serves dataset-derived
images at `/images/*`.

### 4.1 I/O contract

**Library entry points** (re-exported from `src/index.ts`):

| Symbol                   | Purpose                                                                                |
| ------------------------ | -------------------------------------------------------------------------------------- |
| `loadShopData(dir)`      | Read the dataset directory, return a typed `SandboxShopData` (eager, single pass).     |
| `createSandboxSchema()`  | Build the graphql-yoga `GraphQLSchema` from the SDL + resolvers.                       |
| `createSandboxServer({ data, port?, host? })` | Wire schema + HTTP wrapper (`/graphql`, `/images/*`, `/health`, versioned routing). Returns `{ listen, close, url }`. |
| `SandboxShopData`        | Public TS type for the loaded dataset.                                                 |

**CLI** (`shop-backend <data-dir> [port]`):

```
shop-backend ./outputs/shops/example/data 4000
```

Prints loaded counts (products, collections, pages, blogs, policies)
on startup and the GraphQL endpoint URL.

**Endpoints:**

| Path                          | Behavior                                                                  |
| ----------------------------- | ------------------------------------------------------------------------- |
| `POST /graphql`               | The GraphQL endpoint.                                                     |
| `POST /api/<version>/graphql.json` | Rewritten to `/graphql` for Storefront-API-versioned clients.        |
| `GET /images/<path>`          | Serves files under `<data-dir>/images/`. PNG/JPG/WEBP. Cache-immutable.   |
| `GET /health`                 | `200 {"status":"ok","store":"<name>"}`.                                   |

**Out of scope (v0.1):**

- Admin API, customer accounts, orders, fulfillment, draft orders.
- Checkout (cart-to-payment). `Cart.checkoutUrl` is `"#"`.
- Real auth or `Storefront-Access-Token` validation. CORS allows the
  header but does not check it.
- Persistence. Cart state lives in-process.
- Subscriptions, webhooks, real-time updates.
- Inventory queries (no GraphQL field reads `inventory.json`). Added in
  v0.2; see §5.3 + §8.1.2.
- Storefront API features beyond §5.2: customer mutations, gift cards
  beyond cart-side codes, selling plans, shop policies markup beyond
  `body`/`url`, product bundles, B2B.

### 4.2 Success criteria

| ID  | Criterion                                                                                                  |
| --- | ---------------------------------------------------------------------------------------------------------- |
| SC1 | `loadShopData(<sample dataset>)` returns a fully-typed `SandboxShopData` with no `any`/`unknown` escapes.  |
| SC2 | The server boots against a fixture dataset and responds to one Storefront-API canonical query per area in §5.2 (shop, product, collection, menu, page, search, predictiveSearch, cart). |
| SC3 | A full cart lifecycle (`cartCreate` → `cartLinesAdd` → `cartLinesUpdate` → `cartLinesRemove`) succeeds and totals + GIDs round-trip correctly. |
| SC4 | A versioned URL (`POST /api/2024-01/graphql.json`) is routed to `/graphql` and returns the same response.  |
| SC5 | An image URL written by `loadShopData` (e.g. `<server>/images/<file>.jpg`) returns the file with the expected MIME type. |
| SC6 | `tsc --strict` and `biome check` are clean; `vitest` passes with no `any` casts in shipped code.           |

---

## 5. Proposal

### 5.1 File layout

Follow the Google TypeScript Style Guide and the project conventions
in `CLAUDE.md`. Tests are co-located as `*.test.ts` next to the unit.

```
packages/shop_backend/src/
├── index.ts                     # Public exports
├── cli.ts                       # `shop-backend <data-dir> [port]`
├── server.ts                    # createSandboxServer(...)
├── http.ts                      # /images/*, /health, versioned routing
├── schema.ts                    # SDL (typeDefs)
├── schema.test.ts
├── data/
│   ├── types.ts                 # SandboxShopData + dataset schema types
│   ├── loader.ts                # loadShopData(dir)
│   ├── loader.test.ts
│   ├── pagination.ts            # paginate(items, args)
│   └── pagination.test.ts
└── resolvers/
    ├── index.ts                 # combined resolvers + ResolverContext
    ├── builders.ts              # gid, buildProductNode, buildCollectionNode, buildImageNode, buildMoneyV2
    ├── builders.test.ts
    ├── shop.ts                  # Query.shop, Query.menu, Query.localization, Shop policies
    ├── product.ts               # Query.product(s), Query.collection(s), Product/Collection nested
    ├── product.test.ts
    ├── content.ts               # Query.page, Query.blog(s), Article (optional)
    ├── search.ts                # Query.search, Query.predictiveSearch, Query.productRecommendations
    ├── search.test.ts
    ├── cart.ts                  # Query.cart + cart mutations, CartStore class
    ├── cart.test.ts
    └── metafields.ts            # Product/Collection.metafield(s) (optional)
```

### 5.2 GraphQL surface (mirrored subset)

The schema mirrors enough of the Storefront API that a vanilla
Hydrogen / Storefront-API client can issue canonical queries against
it. The full SDL lives in §8.2; the surface is:

| Area              | Queries                                                                                                | Mutations |
| ----------------- | ------------------------------------------------------------------------------------------------------ | --------- |
| **Shop**          | `shop` (incl. `paymentSettings`, `primaryDomain`, `brand`, `*Policy`)                                  | —         |
| **Menu**          | `menu(handle)`                                                                                         | —         |
| **Product**       | `product(handle)`, `products(first/after/sortKey/reverse/query)`, `productRecommendations(productId)`  | —         |
| **Collection**    | `collection(handle)`, `collections(first/after/sortKey/reverse)`                                       | —         |
| **Content**       | `page(handle)`, `blog(handle)`, `blogs(first/after)`, `Blog.articles`, `Blog.articleByHandle`          | —         |
| **Search**        | `search(query, types, first/after, sortKey, reverse, ...)`, `predictiveSearch(query, limit, types)`    | —         |
| **Localization**  | `localization` (single country/language pair derived from `store.country_code`/`currency_code`)        | —         |
| **Cart**          | `cart(id)`                                                                                             | `cartCreate`, `cartLinesAdd`, `cartLinesUpdate`, `cartLinesRemove`, `cartDiscountCodesUpdate`, `cartBuyerIdentityUpdate`, `cartNoteUpdate`, `cartAttributesUpdate`, `cartGiftCardCodesUpdate` |
| **Metafields**    | `Product.metafield(s)`, `Collection.metafield(s)` (only if `metafields.json` present)                  | —         |

Out of this subset (deferred): `Customer`, `Article` standalone (only
via blog), `selling_plan`, and `Variant.metafield(s)` beyond what
`metafields.json` covers.

The `@inContext` directive is declared in the SDL on `QUERY` /
`MUTATION` and validated against the dataset locale (see §5.3
"Localization & `@inContext`").

### 5.3 Resolver semantics

- **GIDs.** Numeric ids → `gid://shopify/<Type>/<n>`. String keys
  (cart ids, menu handles) → `gid://shopify/<Type>/<32-bit hash>`.
  Same hashing as mock-api `data.ts:gid()` to keep ids stable across
  reloads of the same dataset.
- **Pagination.** Relay-style `nodes` + `edges` + `pageInfo` cursors.
  Cursors are `base64("cursor:<index>")`. `first`/`after` and
  `last`/`before` honored. `totalCount` only on connections that
  expose it in real Shopify.
- **Search.** Substring, lowercased, AND-of-terms, scanning
  `title`, `description_html`, `vendor`, `product_type`, `tags` for
  products; `title` for pages and articles.
- **Sorting.** `products`: TITLE / PRICE (min variant price) /
  CREATED_AT / UPDATED_AT / VENDOR / PRODUCT_TYPE / BEST_SELLING
  (falls back to dataset order) / RELEVANCE (search-only). `reverse`
  honored. `collections`: TITLE / UPDATED_AT / ID.
- **Cart.** `cart(id)` returns an existing cart if present; if not
  present, returns `null` (Shopify behavior is to return `null` for
  unknown cart ids, not auto-create — fix vs. mock-api).
- **Currency.** Single currency from `store.currency_code`. All
  `MoneyV2.currencyCode` echoes that value.
- **Images.** `Image.url` is the raw `images[].src` from the dataset
  if it's an absolute URL; otherwise rewritten to
  `<base-url>/images/<path>`.
- **Brand colors.** Plumbed from `store.brand.colors.{primary,secondary}`
  (mock-api hardcodes `#000000`/`#ffffff` — fix here).
- **Localization & `@inContext`** (since v0.2). The dataset is
  single-locale: `Query.localization` returns `Store.country_code` /
  `Store.currency_code` and a static `EN` language. Operations that
  carry an `@inContext(country:, language:)` directive are validated
  against that locale at validation time. A `country` enum that does
  not match `Store.country_code`, or a `language` enum that is not
  `EN`, fails validation with a `GraphQLError` whose
  `extensions.code` is `UNSUPPORTED_LOCALE`; the response carries no
  `data` field. `visitorConsent` is accepted without locale checks.
  Operations with no `@inContext` directive, or with arg values
  expressed via variables, are unaffected.
- **Inventory** (since v0.2). When `inventory.json` provides a tracked
  count for a variant, `ProductVariant.quantityAvailable` reads that
  count and `availableForSale` derives from `count > 0`. When the file
  is absent, the variant is missing from it, or the entry's
  `quantity_available` is `null` (tracked-but-unknown), `quantityAvailable`
  is `null` and `availableForSale` falls back to the dataset's
  `variants[].available` flag. `Product.availableForSale` is `true` iff
  any variant is available under this rule.

### 5.4 HTTP layer

- `/graphql` mounted via `createYoga`.
- `/images/*` static handler reads from `<data-dir>/images/` if the
  directory exists. MIME from extension (PNG, JPG, JPEG, WEBP).
  `Cache-Control: public, max-age=31536000`,
  `Access-Control-Allow-Origin: *`. Strips query string before
  filesystem lookup (Hydrogen appends `?width=&height=&crop=`).
- `/health` returns `200 application/json` with
  `{ "status": "ok", "store": "<dataset.store.name>" }`.
- `/api/<version>/graphql.json` rewritten to `/graphql` (compatibility
  with versioned Storefront API clients).
- CORS: `Access-Control-Allow-Origin: *`,
  methods `POST, OPTIONS`,
  headers `Content-Type, X-Shopify-Storefront-Access-Token`.

### 5.5 Cart store

A `CartStore` class encapsulates per-server in-memory state:

```ts
class CartStore {
  create(input?: CartInput): Cart;
  get(id: string): Cart | undefined;
  addLines(cart: Cart, lines: readonly CartLineInput[]): void;
  updateLines(cart: Cart, lines: readonly CartLineUpdateInput[]): void;
  removeLines(cart: Cart, lineIds: readonly string[]): void;
  clear(): void;
}
```

Constructed once per `createSandboxServer`. Cleared on `server.close()`.
This replaces mock-api's module-level `Map` + `cartCounter` globals;
multiple test instances no longer share state.

### 5.6 Loader behavior

`loadShopData(dir)`:

1. Required files (`store.json`, `products.json`, `collections.json`,
   `navigation.json`, `pages.json`, `policies.json`) are read eagerly.
   Missing required file → throw `MissingDatasetFileError`.
2. Optional files (`blogs.json`, `metafields.json`) default to empty
   structures when missing.
3. Each file is `JSON.parse`'d, then validated against the v0.1
   dataset schema (§8.1). On failure → throw
   `InvalidDatasetError(file, path, message)`.
4. Builds two indices:
   - `productsByHandle: Map<string, Product>`
   - `variantsByGid: Map<string, { product, variant }>` — used by cart
     resolvers to look up merchandise on `cartLinesAdd`.
5. Returns a `readonly SandboxShopData`.

No file watching, no lazy reads, no caching across calls — one server
instance owns one snapshot.

### 5.7 Type strictness

Unlike mock-api, the resolvers must compile under shop-gym's strict
config (`strict`, `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`). Concrete consequences:

- `ResolverContext = { data: SandboxShopData; carts: CartStore; baseUrl: string }`.
  No `(data as any).metafields` casts — metafields are a typed,
  optional field on `SandboxShopData`.
- Resolver argument types are imported from generated GraphQL types
  (via `@graphql-codegen/typescript-resolvers`) — generation happens
  in M2; until then, hand-typed argument interfaces.
- No non-null assertions (`!`) without an in-line justification
  comment (per CLAUDE.md TS style).

---

## 6. Alternatives

### 6.1 Direct port of mock-api

Drop the six files in verbatim, suppress strict-mode errors with
`any`, ship in one PR. Fastest to v0.1.

Rejected: the project's TS style is `strict` + `noUncheckedIndexedAccess`
+ no `any` without justification. A direct port would require either
sweeping `// @ts-expect-error` comments or a per-file relaxation, both
of which contradict the CLAUDE.md guidance to "match existing style"
and "no patching or hacking for short-term success."

### 6.2 Schema-first via SDL → codegen

Author the SDL alone, generate resolver types from it
(`@graphql-codegen/typescript-resolvers`), and let CI fail the build
when SDL and resolvers diverge.

Adopted as a M2 task, not as a v0.1 prerequisite. v0.1 ships with
hand-typed argument interfaces; codegen is added once the surface
stabilizes.

### 6.3 Apollo Server instead of graphql-yoga

Apollo gives more out-of-the-box features (caching, persisted
queries, federation). graphql-yoga is lighter, the existing scaffold
already uses it, and we don't need any Apollo-specific feature.
Rejected — keep the existing stack.

### 6.4 Materialize all GraphQL nodes at load time

Build full Product/Collection nodes once during `loadShopData` instead
of per-resolver-call. Faster on hot paths.

Rejected for v0.1: the dataset already fits in memory (1.6k products
≈ 4 MB JSON), and per-resolver-call building lets us pass field
arguments (e.g. `selectedOrFirstAvailableVariant(selectedOptions:)`)
without a second pass. Revisit if a benchmark shows resolver overhead.

---

## 7. Open Questions

- **GraphQL codegen.** Is codegen required for v0.1 or can it land in
  v0.2? Default in this spec: v0.2 (M5 follow-up). Decided once we
  see the resolver-type pain in M2.
- **Dataset versioning.** Should `store.json` carry a
  `dataset_version: "0.1"` field so the loader can refuse forward-
  incompatible inputs? Default: yes, add an optional field;
  unenforced in v0.1 but reserved.
- **Top-level `metafieldsByIdentifiers` query.** A flat batch read
  taking owner-keyed identifiers across product/collection/shop
  buckets in one call. **Deferred** (not in §5.2). The per-owner
  `Product.metafields(identifiers:)`,
  `Collection.metafields(identifiers:)`, and
  `Shop.metafields(identifiers:)` resolvers already cover scoped batch
  reads; adding a flat variant requires a new owner-keyed input type
  plus a fan-out resolver and has no consumer in the v0.1 fixtures or
  harness. Revisit only if a concrete client (e.g. a Hydrogen surface
  that issues cross-owner batches) lands.

---

## 8. Appendix

### 8.1 SandboxShop dataset schema (v0.1)

Source-of-truth shape that ShopArena `shop_arena.gen` produces and
`shop_backend` consumes.

#### 8.1.1 Required files

**`store.json`** — single object.

```ts
interface Store {
  shop_id: number;
  name: string;
  domain: string;
  description: string;
  currency_code: string;        // ISO 4217 (USD, CAD, EUR, ...)
  country_code: string;         // ISO 3166-1 alpha-2
  payment_settings: {
    accepted_card_brands: string[];   // VISA, MASTER, AMEX, ...
  };
  brand: {
    logo_url: string | null;
    colors: { primary: string; secondary: string };
  };
  dataset_version?: string;     // optional; reserved for future use
}
```

Fields **dropped** vs the live sample: `myshopify_domain`,
`published_products_count`, `published_collections_count`,
`payment_settings.supports_3d_secure`, `contact.*`,
`brand.social_links`. None are read by any resolver.

**`products.json`** — array of `Product`.

```ts
interface Product {
  id: number;
  title: string;
  handle: string;
  description_html: string;
  vendor: string;
  product_type: string;
  tags: string[];
  published_at: string;         // ISO 8601
  created_at: string;
  updated_at: string;
  options: ProductOption[];
  variants: ProductVariant[];
  images: ProductImage[];
}

interface ProductOption {
  name: string;
  position: number;             // 1-indexed
  values: string[];
}

interface ProductVariant {
  id: number;
  title: string;
  sku: string | null;
  price: string;                // decimal as string, e.g. "12.99"
  compare_at_price: string | null;
  available: boolean;
  option1: string | null;
  option2: string | null;
  option3: string | null;
  position: number;
  requires_shipping: boolean;
}

interface ProductImage {
  id: number;
  src: string;                  // absolute URL or path under /images/
  alt: string | null;
  width: number;
  height: number;
  position: number;
}
```

Fields **dropped** vs the live sample: top-level `status`, `category`,
`full_category`, `is_gift_card`; variant `currency_code` (uses
`store.currency_code`), `image_id`, `barcode`, `weight`,
`weight_unit`, `inventory_item_id`. None are read by any resolver.

**`collections.json`** — array of `Collection`.

```ts
interface Collection {
  id: number;
  title: string;
  handle: string;
  description: string | null;
  description_html: string | null;
  image: ProductImage | null;
  published_at: string | null;
  updated_at: string | null;
  sort_order: string | null;    // e.g. "manual", "best-selling"
  product_handles: string[];    // members in this collection
}
```

All sample fields kept — every one maps to a resolver.

**`navigation.json`** — keyed map of menu handle → root nav items.

```ts
interface Navigation {
  [menuHandle: string]: NavigationItem[];
}

interface NavigationItem {
  title: string;
  url: string;                                            // absolute or path
  type: "COLLECTION" | "PRODUCT" | "PAGE" | "BLOG" | "HTTP";
  children: NavigationItem[];
}
```

Conventional handles: `main-menu`, `footer`. Others may exist;
`Query.menu(handle)` returns the list under that handle, or `null` if
absent.

**`pages.json`** — array of `Page`.

```ts
interface Page {
  handle: string;
  title: string;
  body_html: string;
}
```

`published_at` from the sample is **dropped** — not surfaced by the
GraphQL `Page` type.

**`policies.json`** — array of `Policy`. May be empty.

```ts
interface Policy {
  handle: string;        // privacy-policy | shipping-policy | terms-of-service | refund-policy | subscription-policy
  title: string;
  body_html: string;
}
```

#### 8.1.2 Optional files

**`blogs.json`** — array of `Blog`. Defaults to `[]` if absent.

```ts
interface Blog {
  handle: string;
  title: string;
  articles: Article[];
}

interface Article {
  handle: string;
  title: string;
  content_html: string;            // body
  author: string | null;           // resolved as ArticleAuthor.name
  published_at: string | null;
}
```

Fields outside this set (image, tags) are reserved for later
milestones — the v0.1 GraphQL `Article` type ignores them.

**`inventory.json`** (since v0.2) — keyed map of variant id → inventory
entry. Defaults to `{}` if absent.

```ts
interface InventoryFile {
  // Variant id (numeric) as a string key.
  [variantId: string]: InventoryEntry;
}

interface InventoryEntry {
  // Stock quantity for this variant. `null` means tracked-but-unknown
  // (returns `null` to GraphQL); a number is read verbatim.
  quantity_available: number | null;
}
```

Variants without a matching entry are treated as untracked (per §5.3
inventory rules).

**`metafields.json`** — defaults to `{ shop: [], products: {}, collections: {} }`.

```ts
interface MetafieldsFile {
  shop: Metafield[];
  products: Record<string, Metafield[]>;       // keyed by product handle
  collections: Record<string, Metafield[]>;    // keyed by collection handle
}

interface Metafield {
  namespace: string;
  key: string;
  value: string;
  type: string;                                // "single_line_text_field", "json", ...
}
```

Variant metafields are **out of v0.1**.

#### 8.1.3 Files NOT in the v0.1 dataset contract

- `stats.json` — ShopArena exploration artifact, not consumed by the
  server. Lives next to the dataset but is invisible to
  `loadShopData`.
- `inventory.json` — added to the contract in v0.2 (see §8.1.2). Not
  read in v0.1.

#### 8.1.4 Image assets

`<data-dir>/images/<path>` is served by `/images/<path>`. The
directory is optional; if absent, `/images/*` returns 404. Files
referenced in `products[].images[].src` may be absolute (CDN URL,
passed through) or paths under `/images/` (rewritten to
`<base-url>/images/<path>` at resolve time).

### 8.2 GraphQL SDL

The full SDL is the mock-api `schema.ts` (~775 lines) verbatim, with
two changes:

- `enum CurrencyCode` and `enum CountryCode` extended to cover the
  ISO codes appearing in the v0.1 fixtures (currently CAD/USD/CA/US;
  add fixtures' values as we discover them).
- `Variant.requiresShipping` resolves from the dataset's
  `requires_shipping` field instead of being hardcoded to `true`.

The full text lives in `packages/shop_backend/src/schema.ts` once M2
lands. This appendix does not duplicate it; the SDL is the
implementation.

### 8.3 Public surface (`src/index.ts`)

```ts
export { loadShopData } from "./data/loader.js";
export { createSandboxSchema } from "./schema.js";
export { createSandboxServer } from "./server.js";
export type { SandboxShopData } from "./data/types.js";
export type { ServerOptions, SandboxServer } from "./server.js";
```

Nothing else. Internal builders, the cart store, and resolver
internals are package-private.
