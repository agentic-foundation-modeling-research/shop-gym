# Packages depend strictly downward, and the backend depends on none

Dependencies go in one direction only: `cli -> {shop-arena, shop-guru} -> {shop-backend, harness, browser} -> agent -> core`. A package uses another only through its `src/index.ts`. `@shop-gym/shop-backend` has no workspace dependencies at all, because it is also the template that generation copies into every shop, and that copy must install alone with `pnpm install --ignore-workspace`.

## Consequences

The dataset schema lives in `shop-backend/src/data/schema.ts`, not in `core`. Arena and guru import it from the backend package. Do not move it to `core`: a seeded backend copy would then fail to install outside the monorepo.
