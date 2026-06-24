# ShopGym React Vite SSR Template

Minimal React + Vite + React Router SSR storefront template for
`shop_arena.gen`.

## Commands

```bash
pnpm install --ignore-workspace --frozen-lockfile
pnpm dev
pnpm build
pnpm start
pnpm typecheck
```

`PUBLIC_STORE_DOMAIN` is the primary `shop_backend` URL. `SHOP_BACKEND_URL`
is accepted as a fallback alias. `SESSION_SECRET` signs the cart session
cookie.

The fixture shop at `fixtures/sandbox_shop_v0/` is synthetic data used to
validate the template against `shop_backend`; generated shops receive their
own data under `outputs/shops/<name>/data/`. Fixture products include at
least two local product images so card rendering and product-detail gallery
switching can be validated without external media.

The template includes the baseline storefront routes, a right-side cart
popup with a dimmed page backdrop in addition to `/cart`, promo-code
apply/remove forms backed by `shop_backend` cart discount-code mutations,
a cookie preference popup, a small subscription popup, and a local
`/checkout` review page. Styling is intentionally sparse so `shop_gen` can
replace the presentation easily.
