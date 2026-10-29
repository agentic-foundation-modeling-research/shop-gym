# Storefront Template v2 (`packages/shop-arena/templates/storefront`)

Status: **Implemented** (v1.1 M6) · Version: **0.1**
Owners: ShopArena

> The single storefront template seeded into every generated SandboxShop:
> the React Router 7 SSR app from the earlier React + Vite template, moved to the
> TypeScript `@shop-gym/shop-arena` package and extended with customer
> accounts, a real checkout against the stateful backend, and
> `x-shopgym-episode` forwarding so SSR requests stay inside the caller's
> episode.

---

## 1. Overview

v1.0 shipped two storefront templates (Hydrogen and `react-vite`) that only
read the catalog and mutate carts; `/checkout` was a review page with no
submit. The v1.1 backend (M4, `shop_backend/stateful_commerce.md`) adds
customers, access tokens, `commerceSettings`, `checkoutComplete`, and orders
behind one episode-scoped `ShopState`.

This spec covers milestone M6 of `v1_1_typescript_redesign.md`: the
`react-vite` template becomes the only template, lives at
`packages/shop-arena/templates/storefront/`, and gains the account and
checkout routes the backend now supports. The template stays what the build
agent is told it is: plain React Router route modules, one hand-written typed
GraphQL client (`storefrontQuery`), Storefront-API-shaped documents, sparse
CSS the agent restyles.

## 2. Terminology

- **Storefront template**: the tracked file set under
  `packages/shop-arena/templates/storefront/`, copied into
  `runs/build/artifact/storefront/` of a generated shop by M5/M7.
- **Session cookie**: the signed, httpOnly `__shop_gym_session` cookie
  created by `server.mjs` (`createCookieSessionStorage`). It holds `cartId`
  and `customerAccessToken`.
- **Episode header**: `x-shopgym-episode`, read from the incoming request by
  `server.mjs` and re-sent by `storefrontQuery` on every backend call.
- **Customer access token**: the opaque token returned by
  `customerAccessTokenCreate`; the only credential the storefront stores.
- **Order number**: the integer `Order.orderNumber` (`1001`). Storefront
  URLs carry it; `Query.order(id)` takes `gid://shopify/Order/<n>`.

## 3. Current Status

Before M6:

- `packages/shop_arena/src/shop_arena/gen/templates/{hydrogen,react-vite}`
  are the Python generator's templates; Hydrogen is its default.
- `react-vite` has home, collections, collection, product, search, cart,
  checkout (review only), page, and policy routes, a cart drawer, promo
  codes, and cookie / subscribe popups.
- SSR backend calls carry no episode header, so every hosted shop shares the
  backend's `default` episode.
- No account surface: no login, no profile, no orders.

## 4. Desired Status

- One template at `packages/shop-arena/templates/storefront/`, standalone
  (`pnpm install --ignore-workspace`), lint-clean under the root biome config,
  with `pnpm typecheck` and `pnpm build` green.
- Every backend call made while serving a request forwards that request's
  `x-shopgym-episode` header.
- Account routes under `/account/*` backed by the M4 customer and order
  domains, with the access token in the httpOnly session cookie.
- `/checkout` completes orders through `checkoutComplete`, prices the summary
  exactly as the backend does, renders `CheckoutUserError`s inline, and works
  for guests.
- Header shows Login / Account; cart links to checkout; v1.0 routes are
  unchanged.
- A gated vitest proves the whole flow against the real backend.

## 5. Proposal

### 5.1 Layout

```
packages/shop-arena/
  src/templates.ts            STOREFRONT_TEMPLATE_DIR
  src/templates.test.ts       slow smoke (SHOPGYM_SLOW_TESTS=1)
  templates/storefront/
    server.mjs                express + Vite SSR, session cookie, episode header
    app/routes.ts             route table
    app/lib/storefront.ts     storefrontQuery, EPISODE_HEADER
    app/lib/context.ts        AppLoadContext, cart id + access token cookie helpers
    app/lib/customer.ts       loadCustomer, requireCustomer, loginCustomer
    app/lib/queries.ts        GraphQL documents (`*_QUERY`, `*_MUTATION`, `*_FRAGMENT`)
    app/lib/types.ts          hand-written response types
    app/lib/reviews.ts        Reviews URL parameters, sort options, page size, product rating
    app/components/account.tsx   AccountNav, LogoutLink, FormErrors, AddressBlock, OrderHistory, OrderDetails
    app/components/reviews.tsx   RatingBlock, ReviewsSection
    app/routes/account/*.tsx  login, register, logout, profile, addresses, orders, order
    app/routes/checkout.tsx   real checkout
    app/routes/checkout-confirmation.tsx
    fixtures/sandbox_shop_v0/ catalog fixture + customers.json, orders.json, commerce.json, reviews.json
```

The Python tree under `packages/shop_arena/.../templates/` is left in place:
Python `shop-gen` still defaults to Hydrogen and selects `react-vite` by
name, and both are deleted with the rest of the Python packages at M11.
Nothing in v1.1 reads the Python copy.

### 5.2 Route table

| Path | Loader | Action | Backend operations |
| --- | --- | --- | --- |
| `/account/login` | redirect to `redirectTo` when already logged in | `customerAccessTokenCreate`, then `cartBuyerIdentityUpdate` when a cart exists; sets the cookie | `CustomerAccessTokenCreate`, `CartBuyerIdentityUpdate`, `Customer` |
| `/account/register` | same redirect | `customerCreate`, then the login action's steps | `CustomerCreate`, plus login |
| `/account/logout` | redirect to `/account` | `customerAccessTokenDelete`, clears the token, redirects to `/` | `CustomerAccessTokenDelete` |
| `/account` | H1 "Account" with "Log out"; the "Order history" table and "Account details" (default address with phone, "View addresses (<n>)") | - | `Customer`, `CustomerOrders(first: 100)`, `CustomerAddresses` |
| `/account/addresses` | all `Customer.addresses`, default marked (read-only: the backend has no address mutations) | - | `Customer`, `CustomerAddresses` |
| `/account/orders` | the same "Order history" table on its own page, with "Return to Account details" | - | `Customer`, `CustomerOrders(first: 100)` |
| `/account/orders/:orderNumber` | "Order #<n>": lines (product, SKU, price, quantity, total), totals, billing and shipping address with the statuses; 404 unless `order.email` matches the customer | - | `Customer`, `Order`, `CommerceSettings` |
| `/checkout` | cart, `commerceSettings`, customer (prefill) | intent `discount` / `discount-remove`: `cartDiscountCodesUpdate`; else `cartBuyerIdentityUpdate` when logged in, then `checkoutComplete`; clears `cartId`; redirects | `Cart`, `CommerceSettings`, `Customer`, `CartDiscountCodesUpdate`, `CartBuyerIdentityUpdate`, `CheckoutComplete` |
| `/checkout/confirmation/:orderNumber` | the thank-you page: order detail, `commerceSettings` for method titles | - | `Order`, `CommerceSettings` |
| `/products/:handle` | product detail with the Reviews: `?reviews_sort=<order>` picks the order, `?reviews_pages=<n>` shows the first `5 * n` Reviews | - | `Product` (with `reviews(first, sortKey)` and the `reviews.rating` / `reviews.rating_count` metafields) |

Protected loaders go through `requireCustomer`, which redirects to
`/account/login?redirectTo=<path>` and clears a stale token cookie when the
backend no longer recognises it. The root loader adds `customer` so the
header can render Login / Account.

Checkout and the thank-you page follow the Standard sub-manual. Checkout
redirects every shopper to the thank-you page `/checkout/confirmation/<n>`.
Guest checkout needs no login: the contact email is sent as
`CheckoutCompleteInput.email`. The order summary takes the subtotal, the
Discount code and the tax from the cart cost and adds the shipping with the
backend's rules (integer cents, waived at `freeShippingThreshold` on the
subtotal before the discount, or by a free-shipping code), reacting to the
selected shipping method client-side. The "Discount code" field on checkout,
the cart page and the cart drawer replaces the cart's code; a code that does
not apply is not kept (the earlier code comes back) and the field shows
"Enter a valid discount code".

The product page shows Reviews per the Standard sub-manual. Near the title,
the stars (half stars for a decimal part from 0.3 to 0.7), "3.8 / 5.0" and
"(6)" come from the rating metafields; the stars are named "3.8 out of 5.0
stars". Below the product details, a "Reviews" section shows the rating
and the number of Reviews, a "Sort by" control ("Most recent", "Highest
rating", "Lowest rating", "Most helpful") with a "Sort" button, five
Reviews a page, and a "Show more reviews" button while more remain. Each
Review shows its stars, title, text, reviewer name, date, a "Verified
Buyer" badge when flagged, the options of the variant bought, and the
helpful count as text ("1 person found this helpful"; nothing for 0). Both
controls are GET forms that reload the page at `#reviews`, so the order
and the page count live in the URL. A product with no Reviews has no
stars and no section. There is no Review form, photo, summary, topic chip,
filter or helpful vote.

### 5.3 Cookies and headers

- `__shop_gym_session` (renamed from `__shop_gym_cart`, which only ever held
  the cart id): httpOnly, `SameSite=Lax`, signed with `SESSION_SECRET`. Keys
  `cartId` and `customerAccessToken`. Route actions commit it through the
  helpers in `app/lib/context.ts`; loaders never set cookies except the
  stale-token clear in `requireCustomer`.
- `x-shopgym-episode`: `server.mjs` copies the incoming header into
  `AppLoadContext.episodeId` (`null` when absent) and `storefrontQuery` sends
  it on every backend request. There are no client-side GraphQL calls; every
  form posts to a route action, so the browser only ever talks to the
  storefront. A client that sends the header with cookies from another
  episode sees an empty cart and that episode's own orders, which the smoke
  test checks.

### 5.4 Fixtures

`fixtures/sandbox_shop_v0/` gains `customers.json`, `orders.json`,
`commerce.json` and `reviews.json` copied from
`packages/shop_backend/tests/fixtures/`, so the four Personas (all with
password `password123`), two shipping methods, two payment methods, the
free-shipping threshold, the Discount codes `WELCOME10`, `SAVE5` and
`FREESHIP`, and the Reviews of four products are identical on both sides.
The toy `shopliseum-mushroom-dog-toys` has six Reviews, more than one page;
`cartanvil-mackerel-and-sardines-70g` has none. The
Personas and their seeded orders `#1001`-`#1006`:

| Persona | Addresses | Orders |
| --- | --- | --- |
| `jane.doe@example.com` | 1 | `#1001` paid, shipped |
| `marc.tremblay@example.com` | 2 | `#1002` partly refunded; `#1005` paid, not shipped, express |
| `priya.nair@example.com` | 3 | `#1003` refunded; `#1004` paid, shipped, `SAVE5`; `#1006` paid, partly shipped |
| `sam.okafor@example.com` | 1 | none |

### 5.5 Verification

`src/templates.test.ts` (gated by `SHOPGYM_SLOW_TESTS=1`) copies the tracked
template files to a temp dir, runs `pnpm install --ignore-workspace
--frozen-lockfile` and `pnpm build`, boots `shop_backend/dist/cli.js` on the
template fixture and `server.mjs` in production mode on free ports, and
drives: home and product 200, add to cart, guest checkout to confirmation,
inline `CheckoutUserError`, register, profile, logout, login with cart
attach, Discount codes on the cart page, prefilled checkout to the
thank-you page and `/account/orders/<n>`, 404 on another
customer's order, and episode isolation under `x-shopgym-episode: ep1`.

`src/templates.browser.test.ts` is not gated, so it runs in every `pnpm test`
and in CI. It seeds and builds the template, serves it through
`StorefrontSidecar` over the in-process backend on the template fixture, and
walks one shopper in Chromium with the shared browser steps of the final eval:
sign up, log out, log in, the Reviews of a product page (show more, sort, a
half star, left-out fields, and a product with none), add to cart, an
unknown and a valid Discount code,
check out, the thank-you page, the new order in the order history and its
account order page, then a seeded Persona's order history and one past order.
Each test is one step; it asserts on the page and, where
the step changes state, on the episode's StateSnapshot from the Control API.
New template features add a test that calls one more shared step.

### 5.6 Out of scope

Payment methods on the customer, return requests, order cancellation,
reorder, address create / update / delete, and `customerUpdate` have no
backend operations in M4, so the template has no UI for them. `/account/addresses`
is read-only until the backend grows `customerAddress*` mutations.

## 6. Alternatives

| Alternative | Why not |
| --- | --- |
| Separate cookie for the access token | Two session storages to configure and commit; one signed cookie with two keys is the smallest change and keeps the cart-cookie behaviour. |
| Look up `/account/orders/:n` through `Customer.orders` | Needs the full order list per detail view; `Query.order(id)` plus an email ownership check is one call and also serves the guest confirmation page. |
| Nested `/account` layout route | A flat route table is easier for the build agent to read and rename; each page renders its own heading and links instead. |
| Keep Hydrogen alongside | Rejected in `v1_1_typescript_redesign.md` decision 2; its account routes need Shopify's hosted auth. |

## 7. Execution Table

| # | Task | Status |
| --- | --- | --- |
| 1 | Copy the tracked `react-vite` file set to `packages/shop-arena/templates/storefront/`; keep it standalone; make it biome-clean | done |
| 2 | Episode header forwarding (`server.mjs`, `AppLoadContext.episodeId`, `storefrontQuery`) | done |
| 3 | Session helpers for the access token; `customer.ts` (`loadCustomer`, `requireCustomer`, `loginCustomer`) | done |
| 4 | Account routes, `account.tsx` components, header Login / Account link | done |
| 5 | Real `/checkout`, confirmation route, backend-matching totals, inline errors | done |
| 6 | Fixture files, queries, and types | done |
| 7 | `STOREFRONT_TEMPLATE_DIR` export and gated smoke test | done |
| 8 | Delete the Python template trees (Hydrogen and `react-vite`) | deferred to M11 |
| 9 | Address and payment-method management, returns, cancellation | blocked on backend operations (spec 5.6.2 later rows) |
| 10 | Ungated browser suite in every `pnpm test` and CI (`src/templates.browser.test.ts`) | done |
| 11 | Checkout and thank-you page per the Standard sub-manual, with the "Discount code" field; discount shown on the cart and the order detail | done |
| 12 | Account page, order history and order page per the Standard sub-manual; fixture Personas with seeded orders | done |
| 13 | Reviews on the product page per the Standard sub-manual; fixture `reviews.json` | done |

## 8. Appendix

### 8.1 Running the template against the backend

```bash
node packages/shop_backend/dist/cli.js \
  packages/shop-arena/templates/storefront/fixtures/sandbox_shop_v0 4000
cd packages/shop-arena/templates/storefront
pnpm install --ignore-workspace --frozen-lockfile
pnpm build
PUBLIC_STORE_DOMAIN=http://127.0.0.1:4000 pnpm start   # http://localhost:3000
```

### 8.2 Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PUBLIC_STORE_DOMAIN` | `http://localhost:4000` | Backend origin; `SHOP_BACKEND_URL` is accepted as a fallback alias |
| `SESSION_SECRET` | `react-vite-dev-secret` | Signs `__shop_gym_session` |
| `PUBLIC_FOOTER_MENU_HANDLES` | `footer` | Footer menu handle(s) |
| `PORT` | `3000` | Storefront port |

### 8.3 GraphQL document naming

Every document in `app/lib/queries.ts` is an exported `#graphql` template
literal named `<OPERATION>_QUERY`, `<OPERATION>_MUTATION`, or
`<TYPE>_FRAGMENT`, with a named operation (`query Customer`, `mutation
CheckoutComplete`) whose name matches the constant. The `data_in_use`
verifier extracts operations from these literals.
