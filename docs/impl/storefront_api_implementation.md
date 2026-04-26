# ShopBackend Storefront API — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/shop_backend/storefront_api.md`](../specs/shop_backend/storefront_api.md)
Target package: `packages/shop_backend`

> Task list for landing the spec. Each task is one PR-sized unit of
> work with a deliverable and a check. Behavior comes from the spec;
> this doc only says what to do and in what order.

---

## 1. Overview

Six milestones, each independently landable: M1 dataset loader + types,
M2 SDL + read-only resolvers, M3 search + recommendations, M4 cart store
+ mutations, M5 metafields + blogs (optional surface), M6 HTTP wrapper +
versioned routing + image serving. Tasks below are ordered; later tasks
assume earlier ones.

A reference implementation lives at
`shopify-playground/shop-arena/packages/mock-api/src/{schema,data,resolvers,server}.ts`.
Treat it as a reference: copy SDL prose where it's correct, but
re-author resolvers under strict typing and drop the legacy raw-format
loader.

## 2. Terminology

Uses the spec's vocabulary verbatim. No new terms.

## 3. Current Status

`packages/shop_backend/` ships a `Query.ping` placeholder
(`src/{schema,server,cli}.ts`, `src/schema.test.ts`). Strict-mode TS,
biome, vitest are wired. No SandboxShop schema, no dataset loader, no
resolvers.

## 4. Desired Status

After M6: `shop-backend ./outputs/shops/<domain>/data` boots a
graphql-yoga server that mirrors the §5.2 surface; `pnpm --filter
@shop-gym/shop-backend test` is green; `tsc --strict` and `biome check`
are clean. SC1–SC6 from the spec satisfied.

---

## 5. Proposal — Task list

### M1 · Dataset loader + types

- [x] **T1.1** — Add a fixture dataset under
  `packages/shop_backend/tests/fixtures/sandbox_shop_v0/` covering all
  required + both optional files. Source: trim the live sample at
  `shopify-playground/shop-arena/outputs/shops/carlislepetfoods.ca/data/`
  to ~5 products / 2 collections / 1 page / 1 blog / 1 policy / 2
  metafields, anonymized. **Check:** files validate against §8.1
  shape; `git ls-files | wc -l` confirms small footprint.
- [x] **T1.2** — `src/data/types.ts`: dataset schema types (§8.1)
  with `readonly` fields, plus the internal `SandboxShopData`
  aggregate including the two indices (`productsByHandle`,
  `variantsByGid`). No `any`. **Check:** `tsc --noEmit` clean; types
  re-exported from `src/index.ts`.
- [x] **T1.3** — `src/data/loader.ts`: `loadShopData(dir)`. Reads
  required + optional files synchronously, validates shape with a
  hand-rolled type guard per file, builds indices, returns frozen
  `SandboxShopData`. Throws `MissingDatasetFileError` and
  `InvalidDatasetError`. **Check:** `loader.test.ts` covers happy
  path on the fixture, missing required file → throw, malformed JSON
  → throw, optional files default to empty.
- [x] **T1.4** — `src/data/pagination.ts`: `paginate(items, args)`
  helper porting mock-api's cursor scheme (base64 of `cursor:<index>`)
  with strict types. **Check:** `pagination.test.ts` covers
  `first`/`after`, `last`/`before`, both, neither, cursor round-trip,
  empty input.
- [x] **T1.5** — `src/index.ts`: re-export `loadShopData`,
  `SandboxShopData`. Update `src/cli.ts` to take `<data-dir>` arg and
  log loaded counts before calling the (still-placeholder) server.
  **Check:** `pnpm shop-backend tests/fixtures/sandbox_shop_v0` prints
  the expected counts and starts the ping server.

**M1 acceptance:** loader tests green, strict TS clean, biome clean.
No GraphQL schema changes yet.

### M2 · SDL + read-only resolvers

- [x] **T2.1** — `src/schema.ts`: replace the `Query.ping` SDL with
  the full Storefront-API subset (§5.2). Source: mock-api `schema.ts`
  verbatim, with the two changes from spec §8.2 (extend currency/
  country enums, document `requiresShipping`). **Check:** `tsc` clean;
  `createSandboxSchema()` returns a non-null `GraphQLSchema`; existing
  `schema.test.ts` updated to assert `Query.shop` is in the schema.
- [x] **T2.2** — `src/resolvers/builders.ts`: pure builders ported
  from mock-api `data.ts` under strict types. `gid`,
  `buildImageNode`, `buildMoneyV2`, `buildProductVariantNode`,
  `buildProductNode`, `buildCollectionNode`, `buildMenuItemNode`,
  `buildPolicyNode`, `stripHtml`, `matchesSearch`. No `any`. Image
  URL rewrite per spec §5.3. Brand colors plumbed from `store.brand`.
  **Check:** `builders.test.ts` covers GID stability, MoneyV2
  formatting, variant option mapping, image URL rewrite (absolute vs
  relative).
- [x] **T2.3** — `src/resolvers/shop.ts`: `Query.shop`,
  `Query.menu`, `Query.localization`, plus `Shop.{privacyPolicy,
  shippingPolicy, termsOfService, refundPolicy, subscriptionPolicy}`
  nested resolvers reading `policies.json`. **Check:** unit test
  fires `{ shop { name primaryDomain { host } paymentSettings {
  currencyCode } privacyPolicy { handle title } } }` against the
  fixture; values match `store.json` + `policies.json`.
- [x] **T2.4** — `src/resolvers/product.ts`: `Query.product`,
  `Query.products` (with `query`, `sortKey`, `reverse`),
  `Query.collection`, `Query.collections`, plus
  `Product.selectedOrFirstAvailableVariant(selectedOptions)` and
  `Collection.products` nested resolvers. Sort keys per spec §5.3.
  **Check:** `product.test.ts` covers product-by-handle hit + miss,
  products pagination + sort, collection-by-handle, the synthetic
  `collection(handle: "all")`.
- [x] **T2.5** — `src/resolvers/content.ts`: `Query.page`,
  `Query.blog(s)`, `Blog.articles`, `Blog.articleByHandle`. When
  `blogs.json` is absent, `Query.blog` returns `null` and
  `Query.blogs` returns an empty connection. **Check:** unit test
  covers fixture blog with 1 article + missing-blogs case (separate
  fixture variant or stripped data dir).
- [x] **T2.6** — `src/resolvers/index.ts`: combine resolver modules,
  export the typed `ResolverContext`. Wire into `createSandboxSchema`.
  **Check:** end-to-end test in `schema.test.ts` issues a multi-area
  query (`{ shop { name } products(first: 2) { nodes { handle } }
  collection(handle: "...") { products(first: 1) { nodes { handle }
  } } }`) and asserts the response shape.

**M2 acceptance:** read-only Storefront API queries return correct
shapes against the fixture; SC1 + the read half of SC2 satisfied.

### M3 · Search + recommendations

- [x] **T3.1** — `src/resolvers/search.ts`: `Query.search` per spec
  §5.3. Returns a union (`Product | Page | Article`) connection.
  Honors `types`, `first`/`after`, `sortKey` (RELEVANCE = match-rank,
  PRICE = min variant). **Check:** `search.test.ts` covers term
  matching products by title/description/tags, mixed-type result,
  empty query, `types: [PRODUCT]` filter.
- [x] **T3.2** — `Query.predictiveSearch` per spec §5.3. Returns up
  to `limit` matches per type plus a single query suggestion.
  **Check:** test covers limit honoring, term echoed in the
  suggestion, missing-blog case.
- [x] **T3.3** — `Query.productRecommendations(productId)`: pick up
  to 4 other products from the same `product_type`, fall back to the
  next-most-similar by tag overlap, then random dataset order. Mock-
  api uses naive "first 4 other products" — improve here since this
  is one of the more agent-visible surfaces. **Check:** test asserts
  same-type preferred, requesting product is excluded, fewer than 4
  available is graceful.

**M3 acceptance:** search half of SC2 satisfied. No cart yet.

### M4 · Cart store + mutations

- [x] **T4.1** — `src/resolvers/cart.ts`: define `CartStore` class
  per spec §5.5. In-memory `Map<string, Cart>`, deterministic GIDs
  (`gid://shopify/Cart/cart-<n>`), `clear()` for test isolation.
  **Check:** unit test covers create/get/addLines/updateLines/
  removeLines round-trip including line merge on duplicate
  merchandiseId.
- [x] **T4.2** — `Query.cart(id)` resolver: returns existing cart
  resolved against the dataset (line items materialize through
  `variantsByGid`), or `null` for unknown ids. **Diverges from
  mock-api**, which auto-creates on miss; spec §5.3 mandates `null`.
  **Check:** test covers known id round-trip and unknown id → null.
- [x] **T4.3** — `cartCreate`, `cartLinesAdd`, `cartLinesUpdate`,
  `cartLinesRemove` mutations. Resolve cart after each mutation
  (totals, GIDs, merchandise nodes). **Check:** end-to-end test
  fires the canonical lifecycle (`cartCreate { lines: [...] }` →
  `cartLinesAdd` → `cartLinesUpdate { quantity: 0 }` removes line →
  `cartLinesRemove`) and asserts totals + line counts at each step.
  Satisfies SC3.
- [x] **T4.4** — `cartDiscountCodesUpdate`,
  `cartBuyerIdentityUpdate`, `cartNoteUpdate`,
  `cartAttributesUpdate`, `cartGiftCardCodesUpdate`. Stored on the
  cart, returned in `Cart` shape; no real validation. **Check**:
  per-mutation unit test asserting the field is reflected in the
  next `Query.cart(id)`.
- [x] **T4.5** — `createSandboxServer` constructs a fresh `CartStore`
  per call, passes it on the `ResolverContext`, and clears it on
  `close()`. **Check:** test creating two server instances in the
  same process verifies cart ids in one are unknown in the other.

**M4 acceptance:** SC3 satisfied. No HTTP-layer changes yet.

### M5 · Metafields (optional surface)

- [x] **T5.1** — `src/resolvers/metafields.ts`:
  `Product.metafield(namespace, key)`,
  `Product.metafields(identifiers)`,
  `Collection.metafield`, `Collection.metafields`. Read from
  `data.metafields` (typed, no `any`). **Check:** test against
  fixture metafield asserts namespace + key match returns the
  metafield, missing returns `null`, `metafields([{...},{...}])`
  preserves request order with `null` for misses.
- [x] **T5.2** — `Shop.metafield(s)` reading `metafields.shop`.
  **Check:** test covers single metafield read.
- [ ] **T5.3** — `metafieldsByIdentifiers` query if convenient (a
  flat batch read used by Hydrogen). Defer to v0.2 if SDL bloat is
  not warranted; document the deferral in the spec §7. **Check:**
  decision recorded, code changes minimal either way.

**M5 acceptance:** metafield queries against the fixture round-trip;
no metafields → `null` on every query.

### M6 · HTTP wrapper + versioned routing + image serving

- [x] **T6.1** — `src/http.ts`: `buildHttpHandler({ yoga, dataDir })`
  returns a `(req, res) => void` that:
  1. Serves `GET /health` with `{ status: "ok", store }` payload
     (read from the dataset name passed in).
  2. Serves `GET /images/<path>` from `<dataDir>/images/` with the
     MIME map and cache headers from spec §5.4. Strips query string.
     Returns 404 if file missing, 404 if `<dataDir>/images/` doesn't
     exist.
  3. Rewrites `req.url` from `/api/<version>/graphql.json` to
     `/graphql` before forwarding to yoga.
  4. Falls through to yoga for everything else.
  **Check:** `http.test.ts` covers each path with a request fixture.
- [x] **T6.2** — `src/server.ts`: replace the placeholder
  `createServer` with `createSandboxServer({ data, port?, host? })`.
  Wires `createSandboxSchema()`, `CartStore`, `buildHttpHandler`.
  Returns `{ listen, close, url }` (matching the existing scaffold's
  shape). CORS configured per spec §5.4. **Check:** test boots the
  server on an ephemeral port, fires `{ shop { name } }` against
  `/graphql` and `/api/2024-01/graphql.json`, asserts both succeed.
  Satisfies SC2 + SC4.
- [x] **T6.3** — `src/cli.ts`: parse `<data-dir> [port]`, call
  `loadShopData`, then `createSandboxServer`. Print boot message.
  **Check:** `pnpm shop-backend tests/fixtures/sandbox_shop_v0 0`
  starts and serves `/health`.
- [x] **T6.4** — End-to-end test: load fixture, hit each area in
  §5.2 with a canonical query, assert SC2 + SC5. Image asset test
  uses a small PNG committed under
  `tests/fixtures/sandbox_shop_v0/images/`.
- [ ] **T6.5** — Update `packages/shop_backend/README.md`: usage,
  example query, dataset layout reference (link to spec §8.1).
  **Check:** README example query runs against the fixture.

**M6 acceptance:** SC1–SC6 satisfied. `pnpm --filter
@shop-gym/shop-backend build && pnpm --filter @shop-gym/shop-backend
test` green.

### M7 · v0.2 follow-ups

Gaps identified after M6 lands. Sequencing: T7.1 → T7.2 (codegen
needs the SDL stable). T7.3 and T7.4 are independent.

- [ ] **T7.1** — Adopt `@graphql-codegen/typescript-resolvers`. Wire
  `pnpm codegen` to regenerate `src/__generated__/resolvers-types.ts`
  from `src/schema.ts`. Resolver files import argument + return
  types from there. **Check:** removing a typeDef field breaks the
  resolver compile; CI fails on drift.
- [ ] **T7.2** — Inventory queries. Add `inventory.json` to the
  dataset contract, plumb through `ProductVariant.quantityAvailable`
  and `availableForSale` reads inventory levels. **Check:** spec
  appendix updated; test covers a low-stock variant.
- [ ] **T7.3** — `@inContext` directive enforcement. Validate
  `country`/`language` against `Query.localization`; return
  `null`/`UnsupportedLocale` for mismatches. **Check:** test fires a
  query with `@inContext(country: GB)` against a US-only dataset and
  asserts the documented behavior.
- [ ] **T7.4** — Persisted cart store. Optional file-backed cart
  store for benchmarking runs that need cart state across server
  restarts. **Check:** cart created in run A is queryable in run B
  with the same `--cart-store` flag.

**M7 acceptance:** v0.2 spec rev landed; codegen prevents
SDL/resolver drift.
