# ShopBackend Stateful Commerce (`packages/shop_backend`)

Status: **Implemented** (v1.1 M4) · Version: **0.1**
Owners: ShopBackend

> Turns the read-mostly SandboxShop server into a stateful, episode-scoped
> commerce backend: customer accounts, checkout, orders, live inventory, a
> grader-facing state snapshot, and a plain-HTTP control API, shipped as the
> agent-editable backend template for generated shops.

---

## 1. Overview

`storefront_api.md` defines a deterministic read surface plus a per-server
cart store. Shopping-agent benchmarks need more: an agent must be able to log
in, check out, and see the order it placed; a grader must be able to read the
resulting state; and many episodes must run against one server without
leaking state into each other.

This spec adds:

- a per-episode mutable `ShopState` layered over the immutable dataset;
- `customer`, `checkout`, and `order` GraphQL domains, each in its own SDL
  module, with sandbox-only additions marked `@sandbox`;
- three optional dataset files (`customers.json`, `orders.json`,
  `commerce.json`) feeding the state;
- a `StateSnapshot` contract and a control API for episode lifecycle;
- template packaging: standalone install, an in-package `AGENTS.md`, and a
  read-only contract suite.

---

## 2. Terminology

- **Episode** - one isolated branch of mutable shop state, named by the
  `x-shopgym-episode` request header. `default` is used when the header is
  absent.
- **ShopState** - the in-memory object holding an episode's carts, customers,
  sessions, orders, and inventory. Seeded from the dataset; forkable.
- **EpisodeStore** - the per-server registry mapping episode ids to
  `ShopState` instances, created lazily.
- **Episode clock** - deterministic clock starting at
  `2026-01-01T00:00:00.000Z`, advancing one second per mutation.
- **StateSnapshot** - the zod-validated, grader-facing JSON view of one
  episode, served by the control API.
- **Control API** - plain HTTP routes under `/__shopgym/` for resetting,
  reading, and deleting episodes.
- **`@sandbox`** - SDL directive marking operations, types, fields, and
  arguments with no Storefront API equivalent.
- **Template-owned / shop-owned files** - the split between files a
  generated shop must not edit (dataset contract, sandbox contract,
  contract tests) and files it is expected to extend.

---

## 3. Current Status

Before this work (`storefront_api.md` v0.2):

- One `CartStore` per server; every client shared it. No notion of episodes.
- No customer accounts, sessions, checkout, or orders. `checkoutUrl` was a
  placeholder and `CartBuyerIdentity.customer` was always `null`.
- Inventory was read straight from the frozen dataset and never changed.
- A single `src/schema.ts` held the whole SDL.
- Graders had no sanctioned way to observe server state.

After this work:

- Everything listed in §5 is implemented under `packages/shop_backend`
  with 287 passing tests (220 before), typecheck, codegen drift check, and
  biome clean.

---

## 4. Desired Status

1. Any number of episodes run concurrently against one process with no shared
   mutable state; a request without the header behaves exactly as before.
2. An agent can create an account or log in, attach the session to a cart,
   complete checkout, and query the resulting order; inventory reflects the
   purchase within that episode only.
3. A grader can `POST .../reset` before an episode and `GET .../state` after
   it, receiving a stable, schema-validated `StateSnapshot`.
4. Identical action sequences produce identical ids, tokens, and timestamps.
5. Existing read-only queries and the cart lifecycle keep their exact
   behaviour (pinned by `tests/contract/`).
6. The package installs and tests standalone (`pnpm install
   --ignore-workspace`) so it can be copied into a generated shop.

---

## 5. Proposal

### 5.1 File layout

```
src/
  data/schema.ts        + addressSchema, customerSchema, orderSchema, commerceSchema, reviewSchema
  data/loader.ts        + customers.json / orders.json / commerce.json / reviews.json, DEFAULT_COMMERCE
  schema/               directives, common, shop, catalog, content, search, cart,
                        customer, order, checkout, index (merge order)
  resolvers/            + address.ts, customer.ts, order.ts, checkout.ts, review.ts; cart.ts and metafields.ts extended
  state/money.ts        cents <-> decimal strings
  state/pricing.ts      Discount codes, tax, shipping, order totals from commerce.json
  state/episode_clock.ts EpisodeClock, DEFAULT_EPISODE_START
  state/shop_state.ts   ShopState, records
  state/episodes.ts     EpisodeStore, DEFAULT_EPISODE_ID
  sandbox/episode.ts    EPISODE_HEADER, isValidEpisodeId, episodeIdFromHeaders
  sandbox/snapshot.ts   stateSnapshotSchema, exportSnapshot
  sandbox/control_api.ts createControlApi
  http.ts               + optional `route` hook before GraphQL
  server.ts             EpisodeStore wiring, episode context, 400 on bad header
tests/contract/         catalog, search, cart (read-only, no new features); later discount, reviews, addresses
AGENTS.md               template guide
```

### 5.2 ShopState

`new ShopState(data, episodeId, { cartStorePath?, startTime? })` seeds:

- inventory: a copy of `inventoryByVariantId`;
- customers and addresses from `customers.json`;
- orders from `orders.json`;
- counters: customer / address ids continue after the highest seed; order
  ids continue after `max(seeded, 1000)` so a fresh shop's first order is
  `#1001`; tokens are `sandbox-token-<n>`.

`state.data` is `Object.freeze({ ...data, inventoryByVariantId: live })`, so
existing read resolvers and builders see decrements without changes.

Methods: `fork(id)`, `getCustomer`, `findCustomerByEmail`
(case-insensitive), `createCustomer`, `listCustomers`, `createAddress`,
`updateAddress`, `deleteAddress`, `setDefaultAddress`, `createSession`
(14-day TTL on the episode clock), `resolveSession`, `deleteSession`,
`listSessions`, `getOrder`, `ordersForCustomer`, `listOrders`,
`placeOrder`, `inventoryDeltas`. Every mutation calls `clock.tick()`.
The episode's `CartStore` shares the clock: each cart change stamps
`Cart.updatedAt` with `clock.now()` and does not tick, so cart activity
never shifts account or order timestamps.

`placeOrder({ cart, email, shippingAddress, shippingMethod, paymentMethod })`
checks stock for all lines first (tracked quantity, or `variant.available`
when untracked) and returns `{ ok: false, shortfalls }` without side effects;
otherwise it builds line items at catalog prices, decrements inventory,
allocates an address id, computes totals via `state/pricing.ts`, stores a
`PAID` / `UNFULFILLED` order, and deletes the cart.

`CartStore` stays the cart implementation, embedded in `ShopState`, extended
with `list`, `delete`, `purge`, `setCustomer`, and
`buyerIdentity.customerId`.

### 5.3 Episodes and HTTP

- `EpisodeStore.get(id)` lazily constructs a `ShopState`; only `default`
  receives `cartStorePath`, so file-backed carts keep working for the
  header-less case and never mix episodes. `reset(id)` builds a fresh state
  and purges the cart file; `delete(id)` forgets it; `clear()` drops all.
- `episodeIdFromHeaders` accepts `Headers` (duck-typed, yoga ponyfills it)
  or node `IncomingHttpHeaders`; ids match
  `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`. The HTTP route rejects malformed
  headers with `400 { error }` before GraphQL; the yoga context then maps
  the id to `{ data: state.data, state, carts: state.carts, baseUrl }`.
- CORS adds `x-shopgym-episode` to allowed headers.
- `buildHttpHandler` gains an optional `route` consulted after `/health`
  and `/images/*`; the server passes the control API plus the header check.

Control API (`sandbox/control_api.ts`):

| Method | Path | Response |
| --- | --- | --- |
| `POST` | `/__shopgym/episodes/<id>/reset` | `200` StateSnapshot of the re-seeded episode |
| `GET` | `/__shopgym/episodes/<id>/state` | `200` StateSnapshot (materialises the episode) |
| `DELETE` | `/__shopgym/episodes/<id>` | `204`, or `404` when unknown |
| any | invalid id / other path / other method | `400` / `404` / `405` |

### 5.4 StateSnapshot

```
{ episodeId, now,
  customers[]: { id, email, firstName, lastName, phone, acceptsMarketing, createdAt, defaultAddressId, addresses[] },
  sessions[]:  { accessToken, customerId, expiresAt },
  carts[]:     { id, customerId, email, lines[]: { id, merchandiseId, quantity }, discountCodes[], appliedDiscountCode, note },
  orders[]:    { id, name, customerId, email, processedAt, financialStatus, fulfillmentStatus, currencyCode,
                 lineItems[]: { variantId, title, quantity, price }, shippingAddress, shippingMethod, paymentMethod,
                 subtotalPrice, totalShippingPrice, totalTax, totalPrice, discountCode, discountAmount },
  inventory[]: { variantId, baseQuantityAvailable, quantityAvailable } }
```

All ids are GIDs; money is a two-decimal string; `inventory` lists deltas
only. `exportSnapshot` parses its own output through `stateSnapshotSchema`.

### 5.5 GraphQL surface

New SDL modules and operations (names follow the Storefront API):

| Domain | Operation / type | `@sandbox` |
| --- | --- | --- |
| customer | `Query.customer(customerAccessToken: String!): Customer` | no |
| customer | `Mutation.customerCreate(input: CustomerCreateInput!)` | no |
| customer | `Mutation.customerAccessTokenCreate(input: CustomerAccessTokenCreateInput!)` | no |
| customer | `Mutation.customerAccessTokenDelete(customerAccessToken: String!)` | no |
| customer | `Mutation.customerAddressCreate(address: MailingAddressInput!, customerAccessToken: String!)`, `customerAddressUpdate(address, customerAccessToken, id: ID!)`, `customerAddressDelete(customerAccessToken, id: ID!)`, `customerDefaultAddressUpdate(addressId: ID!, customerAccessToken)` | no |
| customer | `Customer { id email firstName lastName displayName phone acceptsMarketing createdAt updatedAt defaultAddress addresses(first) numberOfOrders orders(first, reverse, sortKey) }` | no |
| customer | `MailingAddress`, `MailingAddressInput`, `CustomerAccessToken`, `CustomerUserError`, `CustomerErrorCode`, `CustomerAddressCreatePayload`, `CustomerAddressUpdatePayload`, `CustomerAddressDeletePayload { deletedCustomerAddressId }`, `CustomerDefaultAddressUpdatePayload { customer }` | no |
| cart | `CartBuyerIdentityInput.customerAccessToken`, `CartBuyerIdentity.customer` | no |
| cart | `Cart.discountAllocations`, `CartDiscountAllocation`, `CartCodeDiscountAllocation { code discountedAmount targetType }` | no |
| order | `Query.order(id: ID!): Order` | yes |
| order | `Order { id name orderNumber email processedAt financialStatus fulfillmentStatus currencyCode subtotalPrice totalShippingPrice totalTax totalPrice shippingAddress lineItems(first) shippingMethod paymentMethod discountCode }`, `OrderDiscountCode { code targetType amount }` | `shippingMethod`, `paymentMethod`, `discountCode` |
| order | `OrderLineItem { title quantity variant originalTotalPrice }`, `OrderSortKeys`, status enums | no |
| checkout | `Query.commerceSettings: CommerceSettings!` | yes |
| checkout | `Query.discountCodeHints: [DiscountCodeHint!]!`, `DiscountCodeHint { code hint }` | yes |
| checkout | `Mutation.checkoutComplete(cartId: ID!, input: CheckoutCompleteInput!): CheckoutCompletePayload!` | yes |
| checkout | `CommerceSettings`, `ShippingMethod`, `PaymentMethod`, `CheckoutCompleteInput`, `CheckoutCompletePayload`, `CheckoutUserError` | yes |
| catalog | `Product.reviews(first, after, sortKey: ReviewSortKeys = MOST_RECENT): ReviewConnection!` | yes |
| catalog | `Review { id rating title body reviewerName createdAt verifiedBuyer helpfulCount variant }`, `ReviewConnection`, `ReviewEdge`, `ReviewSortKeys { MOST_RECENT HIGHEST_RATING LOWEST_RATING MOST_HELPFUL }` | yes |

`@sandbox(reason: String)` is declared on `FIELD_DEFINITION | OBJECT |
INPUT_OBJECT | ENUM | ARGUMENT_DEFINITION`.

Validation and error codes:

- `customerCreate`: `BLANK` email, `TAKEN` email, `TOO_SHORT` password (< 5).
- `customerAccessTokenCreate`: `UNIDENTIFIED_CUSTOMER` on bad credentials.
- Address book mutations: `UNIDENTIFIED_CUSTOMER` on
  `['customerAccessToken']` for an unknown token; `NOT_FOUND` on `['id']`
  (`['addressId']` for the default) for an address the customer does not
  have; `BLANK` on `['address', <field>]` for a blank `address1`, `city`,
  `country` or `zip`, the lines that `checkoutComplete` requires. An update
  changes only the fields it sends.
- `cartBuyerIdentityUpdate` with an invalid token: `INVALID` on
  `['buyerIdentity', 'customerAccessToken']`; a valid token sets
  `customerId` and the customer's email on the cart.
- `checkoutComplete`: `INVALID` cart / shipping / payment handle, `EMPTY`
  cart, `BLANK` address lines (`address1`, `city`, `country`, `zip`) or
  missing email, `INSUFFICIENT_STOCK` per short line. Email falls back to
  the cart's buyer identity, then the attached customer. Omitted method
  handles default to the first configured method.

Cart cost: `totalTaxAmount` is non-null only when `commerce.tax_rate > 0`,
mirroring Shopify's null-until-calculated behaviour, so datasets without
`commerce.json` keep their previous cart responses.

Discount codes: a cart holds one code (`cartDiscountCodesUpdate` with two
or more returns an `INVALID` user error), matched in any case and stored in
its `commerce.json` spelling. It applies while the merchandise subtotal
reaches its minimum: a percent or fixed code lowers the subtotal before tax,
never below zero, and a free-shipping code waives the shipping. Cart cost,
`discountCodes.applicable` and `discountAllocations` show it on every read.
`checkoutComplete` records the applied code and the discount amount (the
waived shipping for a free-shipping code) on the order, exposed as the
sandbox field `Order.discountCode`. `discountCodeHints` lists every code
with its hint text in `commerce.json` order, for the storefront's
announcement bar; the Storefront API has no such query, because a merchant
types announcement text into the theme.

Address book: the first address of a customer becomes the default, and
deleting the default makes the first remaining address the default, so a
customer with addresses always has one. New addresses take the next address
id, after the seeded customer and order addresses. `countryCode` is the
store's (the sandbox ships to one country), and a changed province clears
`provinceCode`. Each success ticks the clock once and sets the customer's
`updatedAt`; a user error changes nothing. The address book and
`checkoutComplete` save a `MailingAddressInput` the same way: each line is
trimmed and a blank optional line is `null`.

Reviews: read-only and the same in every Episode. `Product.reviews` sorts
by the sort key, then puts the more recent Review first, then keeps the
`reviews.json` order, so every read gives the same pages. The product
metafields `reviews.rating` (Shopify's `rating` JSON, the mean rounded half
up to one decimal, scale 1.0 to 5.0) and `reviews.rating_count`
(`number_integer`) are computed from the product's Reviews and are absent
when it has none; `metafields.json` entries with those keys are ignored.

### 5.6 Dataset additions

| File | Default | Shape (zod in `src/data/schema.ts`) |
| --- | --- | --- |
| `customers.json` | `[]` | `customerSchema[]`: `id, email, password, first_name, last_name, phone, accepts_marketing, created_at, addresses: addressSchema[], default_address_id` |
| `orders.json` | `[]` | `orderSchema[]`: `id, customer_id, email, processed_at, financial_status, fulfillment_status, currency_code, line_items: { variant_id, title, quantity, price }[], shipping_address, shipping_method, payment_method, subtotal_price, total_shipping_price, total_tax, total_price, discount_code (null), discount_amount ('0.00')` |
| `reviews.json` | `[]` | `reviewSchema[]`: `id, product_handle, variant_id, rating (integer 1 to 5), title, body, reviewer_name, created_at (ISO 8601), verified_buyer, helpful_count (integer, 0 or more)` |
| `commerce.json` | `DEFAULT_COMMERCE` | `commerceSchema`: `tax_rate (0)`, `free_shipping_threshold (null)`, `shipping_methods: { handle, title, price }[] ([])`, `payment_methods: { handle, title }[] ([])`, `discount_codes: { code, kind: percentage / fixed_amount / free_shipping, amount, minimum_subtotal, hint }[] ([])` |

`addressSchema`: `id, first_name, last_name, company, address1, address2,
city, province, province_code, country, country_code, zip, phone`.

### 5.7 Template packaging

- `pnpm install --ignore-workspace` succeeds from the package directory
  (no `workspace:` dependencies).
- `packages/shop_backend/AGENTS.md` documents layout, ownership, and
  commands for build agents.
- `tests/contract/` pins shop, product, collection, search, and cart
  behaviour with no episode, customer, or checkout features.

---

## 6. Alternatives

- **Replace `CartStore` with a cart collection inside `ShopState`.** Cleaner
  long term, but the store already owns persistence, line merging, and 50
  tests; embedding it keeps the change surgical. Revisit when persistence is
  dropped.
- **Episode id in the URL (`/episodes/<id>/graphql`).** Would avoid a custom
  header but breaks Storefront-API-shaped clients that hardcode `/graphql`
  and `/api/<v>/graphql.json`. The header is invisible to such clients.
- **Separate `checkoutCreate` + `checkoutComplete`.** Shopify retired the
  Checkout API; a single cart-to-order mutation is simpler and sufficient
  for grading.
- **Wall-clock timestamps.** Rejected for determinism.

---

## 7. Execution Table

| # | Item | Status |
| --- | --- | --- |
| 1 | Dataset schemas, types, loader defaults, fixture files | done |
| 2 | `ShopState`, `EpisodeClock`, pricing, `EpisodeStore` | done |
| 3 | Per-domain SDL split, `@sandbox`, codegen config | done |
| 4 | Customer / order / checkout resolvers; cart customer association | done |
| 5 | Episode header, `StateSnapshot`, control API, server wiring | done |
| 6 | Contract suite, template `AGENTS.md`, README, standalone install check | done |
| 7 | `customerUpdate`, `cartDeliveryAddressesAdd`, delivery options, `orderCancel`/return/reorder | not started (follow-up) |
| 8 | Cross-episode cart id namespacing (ids are per-episode deterministic and may coincide) | not started (decide when graders need global ids) |
| 9 | Discount codes: `commerce.json` codes, cart pricing and allocations, codes on orders and in the StateSnapshot | done |
| 10 | Reviews: `reviews.json`, `Product.reviews` paging and sorting, computed rating metafields | done |
| 11 | Address book: `customerAddressCreate`, `customerAddressUpdate`, `customerAddressDelete`, `customerDefaultAddressUpdate` | done |

---

## 8. Appendix

### 8.1 Determinism example

Fresh episode, fixture dataset: `customerAccessTokenCreate` ->
`sandbox-token-1` expiring `2026-01-15T00:00:01.000Z`; a following
`checkoutComplete` -> order `#1007` processed at
`2026-01-01T00:00:02.000Z`.

### 8.2 Known limitations

- Passwords are stored and compared in plain text; the sandbox has no
  credential store.
- Session expiry only advances with mutations (the clock is not wall time),
  so tokens effectively never expire during an episode.
- `Customer.orders(query:)` filtering and `cart.deliveryGroups` are not
  implemented; `checkoutUrl` remains `'#'`.
- Cart ids restart at `cart-1` in every episode.
