# @shop-gym/shop-arena

TypeScript ShopArena: storefront exploration (`src/explore/`), SandboxShop
generation (`src/gen/`), and the storefront template under `templates/`.
This package replaces the Python `packages/shop_arena` during the v1.1
migration; see `docs/specs/v1_1_typescript_redesign.md`.

Layout:

```
src/
  explore/      explore pipeline: prefetch, harness tasks, capability merge, manual synthesis
  gen/
    build/      build loop: template seeding, backend sidecar, verifiers, prompts
    ...         data synth, final eval, publish (M7)
templates.ts  STOREFRONT_TEMPLATE_DIR: absolute path of templates/storefront
templates/
  storefront/   React Router 7 SSR storefront template seeded into every shop
                (catalog, cart, account/*, checkout; see its README.md)
```

The storefront template is standalone: it has its own `package.json` and
lockfile, is not a pnpm workspace member, and installs with
`pnpm install --ignore-workspace`. `SHOPGYM_SLOW_TESTS=1 pnpm test` runs
`src/templates.test.ts`, which builds the template in a temp dir and drives
the account and checkout flows against `packages/shop_backend/dist/cli.js`
(build the backend first).
