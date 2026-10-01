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
templates/
  storefront/   React Router 7 SSR storefront template seeded into every shop
```
