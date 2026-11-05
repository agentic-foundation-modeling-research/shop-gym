# ShopBackend

Local GraphQL server that backs **SandboxShop** sandboxes.

ShopBackend loads one synthesized storefront dataset and exposes a
Storefront-API-compatible GraphQL surface for generated storefronts,
shopping-agent benchmarks, and local environment validation.

## Status

Implemented as a TypeScript ESM package. The server boots against a
SandboxShop dataset directory, serves dataset images, and answers canonical
Storefront API queries across shop metadata, menus, products, variants,
collections, content, search, predictive search, localization, product
recommendations, metafields, cart state, customer accounts, checkout, and
orders.

The package doubles as the **backend template** for generated shops; see
`AGENTS.md` in this directory for how it is organised and which files a
generated shop may change.

The current GraphQL contract is the per-domain SDL under `src/schema/`
(merged by `src/schema/index.ts`). It includes:

| Area | Surface |
| --- | --- |
| Shop | `shop`, `Shop.paymentSettings`, `Shop.primaryDomain`, `Shop.brand`, policies, `Shop.metafield(s)` |
| Menu | `menu(handle)` |
| Product | `product(handle)`, `products(...)`, product options, variants, images, encoded variant fields, inventory-backed `availableForSale` / `quantityAvailable`, `Product.metafield(s)`, `Product.reviews(...)` (sandbox-only) |
| Collection | `collection(handle)`, `collections(...)`, `Collection.products(...)`, `Collection.metafield(s)` |
| Content | `page(handle)`, `blog(handle)`, `blogs(...)`, `Blog.articles(...)`, `Blog.articleByHandle(...)` |
| Search | `search(...)`, `predictiveSearch(...)`, `productRecommendations(productId)` |
| Localization | `localization`, plus validation for literal `@inContext(country:, language:)` values |
| Cart | `cart(id)` and cart mutations for create, line add/update/remove, Discount codes (one per cart, priced into `cost` and `discountAllocations`), buyer identity (including `customerAccessToken`), note, attributes, and gift-card codes |
| Customer | `customerCreate`, `customerAccessTokenCreate`, `customerAccessTokenDelete`, `customerRecover` (a mock that sends nothing), the address book (`customerAddressCreate`, `customerAddressUpdate`, `customerAddressDelete`, `customerDefaultAddressUpdate`), `customer(customerAccessToken)` with profile, addresses, and `orders` |
| Checkout | `commerceSettings`, `discountCodeHints` and `checkoutComplete(cartId, input)` (sandbox-only) converting a cart into an order |
| Order | `order(id)` (sandbox-only) plus `Order`, `OrderLineItem`, and `MailingAddress` types |

Fields and operations with no Storefront API equivalent carry the `@sandbox`
directive in the SDL.

Read paths are deterministic for a given dataset. Mutable state (carts,
customers, sessions, password reset requests, orders, inventory) lives in a
per-episode `ShopState`; see "Episodes" below. There is no Admin API, real
payment processing, webhook support, or Storefront access-token validation.

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
any origin for `POST` / `OPTIONS` requests with the `Content-Type` and
`x-shopgym-episode` headers.

### Episodes

Every request belongs to an **episode**: an isolated branch of mutable shop
state (carts, customer accounts, access tokens, orders, inventory) forked
lazily from the loaded dataset. The `x-shopgym-episode: <id>` header selects
the episode; requests without it use `default`. Ids are 1-64 characters of
`[A-Za-z0-9._-]` and must not start with punctuation; anything else is
rejected with HTTP 400.

Episodes are deterministic: ids come from sequential counters (`cart-1`,
`sandbox-token-1`, order `#1002`, ...) and timestamps from a clock that starts
at `2026-01-01T00:00:00Z` and advances one second per mutation, so the same
action sequence always yields the same state.

The control API manages episodes outside GraphQL:

| Route | Behavior |
| --- | --- |
| `GET /__shopgym/episodes/<id>/state` | `200` with the episode's `StateSnapshot` (creates it if needed). |
| `POST /__shopgym/episodes/<id>/reset` | Re-seed the episode from the dataset; `200` with the fresh snapshot. |
| `DELETE /__shopgym/episodes/<id>` | Forget the episode; `204`, or `404` if it was never materialised. |

`StateSnapshot` (`stateSnapshotSchema`, exported) is the grader-facing view:
`{ episodeId, now, customers, sessions, passwordResetRequests, carts, orders,
inventory }`, where
`inventory` lists only variants whose quantity differs from the dataset.
Carts show `discountCodes` and the `appliedDiscountCode` (the stored code
when it applies now, else `null`); orders show `discountCode` and
`discountAmount`.

### Checkout flow

```graphql
mutation {
  customerAccessTokenCreate(input: { email: "jane.doe@example.com", password: "password123" }) {
    customerAccessToken { accessToken }
  }
}
mutation {
  cartBuyerIdentityUpdate(cartId: "gid://shopify/Cart/cart-1", buyerIdentity: { customerAccessToken: "sandbox-token-1" }) {
    cart { buyerIdentity { customer { displayName } } }
  }
}
mutation {
  checkoutComplete(
    cartId: "gid://shopify/Cart/cart-1"
    input: {
      shippingAddress: { firstName: "Jane", lastName: "Doe", address1: "123 Bank Street", city: "Ottawa", country: "Canada", zip: "K2P 1X3" }
      shippingMethodHandle: "standard"
      paymentMethodHandle: "card"
    }
  ) {
    order { name totalPrice { amount currencyCode } }
    userErrors { code field message }
  }
}
```

`checkoutComplete` validates the cart, methods, address, and stock, then
creates a `PAID` / `UNFULFILLED` order, decrements episode inventory, and
deletes the cart. Guest checkout works with `input.email` or a cart
`buyerIdentity.email`. Totals follow `commerce.json`: flat `tax_rate` on the
subtotal after the discount, the chosen shipping method's price, waived at
`free_shipping_threshold` (checked before the discount).

### Discount codes

`commerce.json` lists `discount_codes`, each with `code`, `kind`
(`percentage`, `fixed_amount` or `free_shipping`), `amount`, an optional
`minimum_subtotal` and a `hint`. A cart holds one code:
`cartDiscountCodesUpdate` with two codes returns an `INVALID` user error and
stores nothing, and a new code replaces the old one. Codes match in any case
and are stored in their `commerce.json` spelling; an unknown code is stored as
typed. A code applies while the merchandise subtotal before the discount
reaches its minimum, so a cart that drops below the minimum keeps the code
with `applicable: false`. A percent or fixed code lowers `cost.totalAmount`
(never below zero) and adds a `LINE_ITEM` allocation; a free-shipping code
adds a `SHIPPING_LINE` allocation of `0.00`, and `checkoutComplete` waives the
shipping charge. The order records the code and the amount it removed (the
waived shipping charge for free shipping) in the sandbox field
`Order.discountCode { code targetType amount }`. The sandbox query
`discountCodeHints` lists every code with its `hint` in `commerce.json` order,
for the storefront's announcement bar; Shopify has no such query, because a
merchant types announcement text into the theme.

### Address book

A logged-in customer adds, edits and deletes addresses and picks the default
one with `customerAddressCreate`, `customerAddressUpdate`,
`customerAddressDelete` and `customerDefaultAddressUpdate`. An address needs
the same lines as a checkout shipping address (`address1`, `city`,
`country`, `zip`); a blank one is a `BLANK` user error on
`['address', <field>]`. An update changes only the fields it sends. An
unknown token is `UNIDENTIFIED_CUSTOMER`, and an address of another customer
is `NOT_FOUND`. The first address becomes the default, and when the default
is deleted the first remaining address takes its place. The country code is
the store's, and a changed province clears the province code. Each change
moves the Episode clock and shows in the StateSnapshot customers.

### Password recovery

`customerRecover(email)` is a mock of "Forgot your password?". It always
answers with no user errors, for a known or an unknown email, so the answer
does not tell which emails have an account. It sends no email and changes
no password. It records the trimmed email and the Episode clock time, and
the StateSnapshot lists these requests in `passwordResetRequests`, in
request order.

### Reviews

`reviews.json` lists read-only product Reviews. `Product.reviews(first,
after, sortKey)` (sandbox-only) pages them in the order `MOST_RECENT` (the
default), `HIGHEST_RATING`, `LOWEST_RATING` or `MOST_HELPFUL`; ties put the
more recent Review first, then keep the file order. Each `Review` has a
`rating` (1 to 5), `title`, `body`, `reviewerName`, `createdAt`,
`verifiedBuyer`, `helpfulCount` and the `variant` bought. The product
metafields `reviews.rating` (Shopify's `rating` JSON, the mean rounded to one
decimal, for example `{"value":"4.5","scale_min":"1.0","scale_max":"5.0"}`)
and `reviews.rating_count` (`number_integer`) are computed from the same
Reviews, and a product with no Reviews has neither. `metafields.json` entries
with these two keys are ignored.

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
`default` episode's cart store with a JSON snapshot file (other episodes are
always in-memory):

```bash
pnpm --filter @shop-gym/shop-backend shop-backend \
  tests/fixtures/sandbox_shop_v0 4000 \
  --cart-store ./outputs/cart-store.json
```

The file is rewritten synchronously after every cart mutation. Pointing a
later run at the same path rehydrates carts (and the cart-id counter) so
ids minted in run A remain queryable from run B.

## Dataset layout

`loadShopData(dir)` reads one snapshot from a SandboxShop dataset directory
and validates each file against the zod schemas in `src/data/schema.ts`
(exported as `datasetSchema`). Missing required files or malformed optional
files fail startup.

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
| `customers.json` | `[]` | Seeded customer accounts (plain-text sandbox passwords) with addresses |
| `orders.json` | `[]` | Seeded order history, with an optional `discount_code` and `discount_amount`; new orders are numbered after the highest seed (minimum `#1001`) |
| `commerce.json` | `DEFAULT_COMMERCE` | `tax_rate`, `free_shipping_threshold`, `shipping_methods`, `payment_methods`, `discount_codes` |
| `reviews.json` | `[]` | Product Reviews: `id`, `product_handle`, `variant_id`, `rating`, `title`, `body`, `reviewer_name`, `created_at` (ISO 8601 date and time), `verified_buyer`, `helpful_count` |

`DEFAULT_COMMERCE` is no tax, no free-shipping threshold, one free `standard`
shipping method, one `card` payment method, and no Discount codes. A partial `commerce.json`
fills the omitted keys with `0` / `null` / `[]`, not with these defaults.

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

Public exports include `loadShopData`, `createSandboxSchema`, `typeDefs`,
`createSandboxServer`, `ShopState`, `EpisodeStore`, `exportSnapshot`,
`stateSnapshotSchema`, `EPISODE_HEADER`, `DEFAULT_EPISODE_ID`,
`DEFAULT_COMMERCE`, and the dataset / state record types.

## Build & test

```bash
pnpm --filter @shop-gym/shop-backend build
pnpm --filter @shop-gym/shop-backend test
```

`tests/contract/` pins read-only catalog, search, and cart behaviour against
the bundled fixture so generated storefronts keep working as the template
evolves.

`src/data/schema.parity.test.ts` additionally loads every shop found under
`SHOPGYM_SHOPS_DIR` (default `<repo>/outputs/shops`) to confirm generated
datasets still match the schema; it is skipped when that directory is absent.
