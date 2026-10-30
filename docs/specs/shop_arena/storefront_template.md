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
- Header shows Log in / Account; cart links to checkout; v1.0 routes are
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
    app/lib/addresses.ts      ADDRESS_FIELDS, address book mutations
    app/components/account.tsx   LogoutLink, FormErrors, AddressBlock, OrderHistory, OrderDetails
    app/components/addresses.tsx AddressBook, DELETE_ADDRESS_CONFIRM
    app/components/reviews.tsx   RatingBlock, ReviewsSection
    app/components/announcement-bar.tsx AnnouncementBar
    app/routes/account/*.tsx  login, register, logout, profile, addresses, orders, order
    app/routes/checkout.tsx   real checkout
    app/routes/cart-json.ts   `/cart.js`, the cart as Shopify's AJAX cart JSON
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
| `/account/login` | redirect to `redirectTo` when already logged in | intent `recover`: `customerRecover`, then the login form with the sent message, or with the backend's errors if there are any; else `customerAccessTokenCreate`, then `cartBuyerIdentityUpdate` when a cart exists; sets the cookie | `CustomerRecover`, `CustomerAccessTokenCreate`, `CartBuyerIdentityUpdate`, `Customer` |
| `/account/register` | same redirect | `customerCreate`, then the login action's steps | `CustomerCreate`, plus login |
| `/account/logout` | redirect to `/account` | `customerAccessTokenDelete`, clears the token, redirects to `/` | `CustomerAccessTokenDelete` |
| `/account` | H1 "Account" with "Log out"; the "Order history" table and "Account details" (default address with phone, "View addresses (<n>)") | - | `Customer`, `CustomerOrders(first: 100)`, `CustomerAddresses` |
| `/account/addresses` | the address book: all `Customer.addresses`, "Default" above the default, the add and edit forms (country options from `localization.availableCountries`) | intent `create` / `update`: `customerAddressCreate` / `customerAddressUpdate`, then `customerDefaultAddressUpdate` when "Set as default address" is checked; intent `delete`: `customerAddressDelete`; redirects to `/account/addresses`, or returns the errors and the submitted fields | `Customer`, `CustomerAddresses`, `Countries`, `CustomerAddressCreate`, `CustomerAddressUpdate`, `CustomerAddressDelete`, `CustomerDefaultAddressUpdate` |
| `/account/orders` | the same "Order history" table on its own page, with "Return to Account details" | - | `Customer`, `CustomerOrders(first: 100)` |
| `/account/orders/:orderNumber` | "Order #<n>": lines (product, SKU, price, quantity, total), totals, billing and shipping address with the statuses; 404 unless `order.email` matches the customer | - | `Customer`, `Order`, `CommerceSettings` |
| `/checkout` | cart, `commerceSettings`, customer (prefill) | intent `discount` / `discount-remove`: `cartDiscountCodesUpdate`; else `cartBuyerIdentityUpdate` when logged in, then `checkoutComplete`; clears `cartId`; redirects | `Cart`, `CommerceSettings`, `Customer`, `CartDiscountCodesUpdate`, `CartBuyerIdentityUpdate`, `CheckoutComplete` |
| `/checkout/confirmation/:orderNumber` | the thank-you page: order detail, `commerceSettings` for method titles | - | `Order`, `CommerceSettings` |
| `/cart.js` | the session's cart as Shopify's AJAX cart JSON (below); read only, no login | - | `Cart` |
| `/products/:handle` | product detail with the Reviews: `?reviews_sort=<order>` picks the order, `?reviews_pages=<n>` shows the first `5 * n` Reviews | - | `Product` (with `reviews(first, sortKey)` and the `reviews.rating` / `reviews.rating_count` metafields) |

Protected loaders go through `requireCustomer`, which redirects to
`/account/login?redirectTo=<path>` and clears a stale token cookie when the
backend no longer recognises it. The root loader adds `customer` so the
header can render Log in / Account, and `discountCodeHints` for the
announcement bar.

`/cart.js` returns the session's cart in the request's episode with the
field names of Shopify's AJAX Cart API (`GET /{locale}/cart.js`), so Task
generation reads the cart the same way on a SandboxShop and on a Live
storefront. Every amount is an integer in cents. `items` has, per line,
`id` and `variant_id` (the numeric variant id), `product_title`,
`variant_title` (null for "Default Title"), `quantity`, `price` (the unit
price) and `line_price` (price times quantity). `item_count` is the sum of
the quantities. `total_discount` is what the Discount code takes off the
merchandise (0 for a free-shipping code), and `total_price` is the
merchandise subtotal less `total_discount`, before tax and shipping.
`discount_codes` lists each code on the cart with `code` and `applicable`,
so a code that stopped applying below its minimum shows as not
applicable. Shopify's reference documents every field but
`discount_codes`, which Shopify's `/cart.js` returns with the fields of
the Storefront API's `CartDiscountCode`. The other Shopify fields are left
out. With no cart, or a cart id that the episode does not know, the route
returns the empty cart. It has no action and sets no cookie.

The announcement bar follows the Standard sub-manual. It is a full-width
strip above the header on every page, with one slide for each Discount
code, `<code> - <hint>`, in Dataset order. With two or more codes it is a
region named "Announcement bar" that shows only the current slide, a group
named "<n> of <total>", between the "Previous announcement" and "Next
announcement" arrow buttons; Next on the last slide goes to the first, and
Previous on the first goes to the last. It has no auto-rotate, and it starts
at the first code on each page: the root keys it by path, as a full page
load resets Dawn's bar. One code shows as a region named "Announcement"
with no arrows, and with no codes there is no bar. No code or hint is in
the template code.

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

The address book follows the Standard sub-manual. "Add a new address" and
each "Edit" (named "Edit address <n>") open their form under the button;
"Cancel" closes it. The forms have the checkout field names (`firstName`,
`lastName`, `company`, `address1`, `address2`, `city`, `country`,
`province`, `zip`, `phone`) with floating labels, a "Country/region"
select and the "Set as default address" checkbox (`default`). "Delete"
(named "Delete <n>") asks the browser's own confirm dialog. A turned-down
form opens again with the submitted fields under "Please adjust the
following:" and the backend's errors. The page renders the address book
with a new key after each action, so the forms close when the new list
shows. Checkout fills its form from the default address.

The login and register pages follow the Standard sub-manual: a narrow
centered column, centered headings and buttons, and floating labels. Login
has "Email", "Password", the link "Forgot your password?", "Sign in" and
"Create account". The link opens "Reset your password" in place of the
login form, with a CSS `:target` toggle. Its "Submit" sends
`customerRecover`. Then the page shows the login form with "We've sent you
an email with a link to update your password." above it, for any email,
or with the backend's errors if there are any. "Cancel" goes back to the
login form. Register has "First name", "Last name", "Email", "Password"
and "Create"; a backend error on a field shows under that field and in
the list under "Please adjust the following:". The form field names
(`email`, `password`, `firstName`, `lastName`) are the same as before.

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
customer's order, `/cart.js` with no cart, with a Discount code that
applies, after a quantity change that leaves the code not applicable and
with a one-variant product, and episode isolation under
`x-shopgym-episode: ep1`, also for `/cart.js`.

`src/templates.browser.test.ts` is not gated, so it runs in every `pnpm test`
and in CI. It seeds and builds the template, serves it through
`StorefrontSidecar` over the in-process backend on the template fixture, and
walks one shopper in Chromium with the shared browser steps of the final eval:
sign up, log out, a taken email on the register page, "Forgot your
password?", log in, the Reviews of a product page (show more, sort, a
half star, left-out fields, and a product with none), add to cart, every
Discount code in the announcement bar with its arrows (and, on a fake
clock, no move by itself), an unknown and a valid Discount code,
`/cart.js` with that code (and the empty cart from another episode),
check out, the thank-you page, the new order in the order history and its
account order page, the address book (the errors of a blank address,
add an address, add and edit a second one, make it the default, see it
prefilled at checkout, delete the first after the confirm dialog), then a
seeded Persona's order history and one past order. Last, it serves the
same build over two more backends, on the fixture with only its first
Discount code and with none, and checks the plain announcement and the
missing bar.
Each test is one step; it asserts on the page and, where
the step changes state, on the episode's StateSnapshot from the Control API.
New template features add a test that calls one more shared step.

### 5.6 Out of scope

Payment methods on the customer, return requests, order cancellation,
reorder, and `customerUpdate` have no backend operations in M4, so the
template has no UI for them.

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
| 9 | Payment-method management, returns, cancellation | blocked on backend operations (spec 5.6.2 later rows) |
| 10 | Ungated browser suite in every `pnpm test` and CI (`src/templates.browser.test.ts`) | done |
| 11 | Checkout and thank-you page per the Standard sub-manual, with the "Discount code" field; discount shown on the cart and the order detail | done |
| 12 | Account page, order history and order page per the Standard sub-manual; fixture Personas with seeded orders | done |
| 13 | Reviews on the product page per the Standard sub-manual; fixture `reviews.json` | done |
| 14 | Address book on `/account/addresses` per the Standard sub-manual; checkout prefilled from the default address | done |
| 15 | Announcement bar with the Discount codes per the Standard sub-manual, fed by `discountCodeHints` | done |
| 16 | Login and register per the Standard sub-manual, with the "Forgot your password?" mock on `customerRecover` | done |
| 17 | Read-only `/cart.js` in the fields of Shopify's AJAX cart, checked by `cart_conformance` | done |

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
