# ShopGym Storefront Template

React + Vite + React Router 7 SSR storefront seeded into every generated
SandboxShop. It talks only to `shop_backend` through one hand-written GraphQL
client (`app/lib/storefront.ts`); there is no vendor SDK and no client-side
GraphQL. Styling is intentionally sparse so the build agent can restyle it.

## Commands

```bash
pnpm install --ignore-workspace --frozen-lockfile
pnpm dev          # Vite middleware, http://localhost:3000
pnpm build        # react-router typegen + build into dist/
pnpm start        # NODE_ENV=production node server.mjs
pnpm typecheck    # react-router typegen + tsc --noEmit
```

Run it against the backend on the bundled fixture:

```bash
# from the repo root
node packages/shop_backend/dist/cli.js \
  packages/shop-arena/templates/storefront/fixtures/sandbox_shop_v0 4000
# in this directory
PUBLIC_STORE_DOMAIN=http://127.0.0.1:4000 pnpm start
```

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `PUBLIC_STORE_DOMAIN` | `http://localhost:4000` | `shop_backend` origin (`SHOP_BACKEND_URL` is an accepted alias) |
| `SESSION_SECRET` | `react-vite-dev-secret` | Signs the session cookie |
| `PUBLIC_FOOTER_MENU_HANDLES` | `footer` | Footer menu handle(s), comma separated |
| `PORT` | `3000` | Listen port |

`server.mjs` reads a `.env` file next to it before applying these defaults.

## Routes

| Path | Purpose |
| --- | --- |
| `/` | Home: shop, featured collections and products |
| `/collections`, `/collections/:handle` | Collection list and detail |
| `/products/:handle` | Product detail with variant radios and add-to-cart |
| `/search?q=` | Products, pages, and articles |
| `/cart` | Cart page; its action handles `add`, `update`, `remove`, `discount` intents |
| `/checkout` | Shipping address, email, shipping and payment method radios, backend-matching totals; the action calls `checkoutComplete` |
| `/checkout/confirmation/:orderNumber` | Guest order confirmation |
| `/account/login`, `/account/register` | Credentials forms; on success the token is stored and attached to the cart |
| `/account/logout` | POST only; deletes the token and clears the cookie |
| `/account` | Profile, default address, recent orders |
| `/account/addresses` | Saved addresses (read-only) |
| `/account/orders`, `/account/orders/:orderNumber` | Order history and detail |
| `/pages/:handle`, `/policies/:handle` | Static content |

Account loaders redirect to `/account/login?redirectTo=<path>` when there is
no valid session. Checkout works for guests; logged-in customers get the
form prefilled from their default address and land on
`/account/orders/<n>` after placing the order.

## Cookies and headers

- `__shop_gym_session`: httpOnly, `SameSite=Lax`, signed with
  `SESSION_SECRET`. Holds `cartId` and `customerAccessToken`. Only route
  actions set it (helpers in `app/lib/context.ts`).
- `x-shopgym-episode`: when the incoming request carries it, every backend
  call made while serving that request forwards it, so SSR stays inside the
  caller's episode. Requests without it use the backend's `default` episode.

## Code map

- `app/lib/queries.ts`: every GraphQL document, exported as `*_QUERY`,
  `*_MUTATION`, or `*_FRAGMENT` `#graphql` template literals.
- `app/lib/types.ts`: hand-written response types for those documents.
- `app/lib/customer.ts`: `loadCustomer`, `requireCustomer`, `loginCustomer`.
- `app/components/storefront.tsx`: header, footer, grids, cart drawer.
- `app/components/account.tsx`: account nav, forms errors, address and order
  rendering shared by account and checkout pages.

## Fixture

`fixtures/sandbox_shop_v0/` is a small synthetic shop (catalog, navigation,
policies, two local images per product) plus `customers.json`
(`jane.doe@example.com` / `password123`), `orders.json` (order `#1001`), and
`commerce.json` (two shipping methods, two payment methods, free shipping
over 75.00). It is byte-identical to the backend's fixture for those three
files so both packages agree.
