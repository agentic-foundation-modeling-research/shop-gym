# ShopBackend template - agent guide

This package is the **backend template** every generated SandboxShop starts
from. A build agent copies it next to a dataset, extends it, and the result is
served by `shop-backend <data-dir> <port>`. Read this file before editing.

## How the backend is organised

```
src/
  data/        dataset contract: zod schemas (schema.ts), inferred types, loader
  schema/      GraphQL SDL, one module per domain, merged in schema/index.ts
  resolvers/   resolver maps, one module per domain, merged in resolvers/index.ts
  state/       per-episode mutable state (ShopState), episode registry, pricing
  sandbox/     ShopGym contract: episode header, StateSnapshot, control API
  __generated__/ resolver types produced by `pnpm codegen` from src/schema/*.ts
  server.ts    createSandboxServer: yoga + HTTP wrapper + episode routing
  http.ts      node:http wrapper: /health, /images, control route, GraphQL
  cli.ts       `shop-backend` entry point
tests/
  fixtures/sandbox_shop_v0/   small complete dataset used by every test
  contract/                   read-only behaviour pinned for generated shops
```

Request flow: `http.ts` answers `/health`, `/images/*`, and the control API,
then hands GraphQL to yoga. The yoga context resolves the request's episode
(`x-shopgym-episode` header, `default` when absent) to a `ShopState` and
exposes `{ data, state, carts, baseUrl }` to resolvers. `state.data` is the
episode's view of the dataset with live inventory; read resolvers never need
to know about episodes.

Domains: `shop`, `catalog`, `content`, `search` are read-only over the
dataset; `cart`, `customer`, `order`, `checkout` mutate the episode state.
Anything with no Storefront API equivalent is marked `@sandbox` in the SDL.

## Who owns which files

Template-owned (do not edit in a generated shop; changes here are made in the
ShopGym repo and flow to every shop):

- `src/data/schema.ts` - the dataset contract shared with the generator.
- `src/sandbox/**` - episode header, `StateSnapshot` schema, control API.
  Graders read only `StateSnapshot`; changing it breaks grading.
- `tests/contract/**` - read-only behaviour storefronts already depend on.
- `scripts/`, `codegen.ts`, `tsconfig.json`, `biome` settings.

Generated-shop-owned (extend freely to model the shop being built):

- `src/schema/**` and `src/resolvers/**` - add fields, types, and domains.
  Run `pnpm codegen` after SDL edits; `pnpm codegen:check` guards drift.
- `src/state/**` - add collections to `ShopState` when the shop needs new
  mutable concepts. Keep `fork()` cheap and keep every mutation calling
  `clock.tick()` so episodes stay deterministic.
- `src/data/loader.ts` and `src/data/types.ts` only to wire new optional
  files whose schema was added to `schema.ts` upstream.
- Co-located `*.test.ts` files and the fixture under `tests/fixtures/`.
- `package.json` dependencies, as long as the package still installs
  standalone with `pnpm install --ignore-workspace`.

If `exportSnapshot` no longer satisfies `stateSnapshotSchema`, the snapshot
test fails; fix the exporter, not the schema.

## Rules

- Every episode-visible mutation goes through `ShopState` (or `CartStore`
  inside it). Never hold mutable module-level state; it leaks across episodes.
- Resolvers read inventory through `ctx.data.inventoryByVariantId`, never the
  base dataset, so checkout decrements are visible.
- Keep read-only queries deterministic for a given dataset: no wall-clock
  time, no randomness. Use `state.clock` for timestamps.
- Follow `AGENTS.md` at the repo root for style: strict TypeScript, biome,
  `.js` import extensions, named exports, no `any`.

## Commands

```bash
pnpm install                     # inside the ShopGym workspace
pnpm install --ignore-workspace  # standalone copy (tsconfig.json extends ../../tsconfig.base.json; copy it too)
pnpm typecheck                   # tsc --noEmit
pnpm test                        # vitest: unit + contract suites
pnpm codegen && pnpm codegen:check
pnpm build                       # emits dist/
pnpm shop-backend tests/fixtures/sandbox_shop_v0 4000
```

Run the contract suite alone with `pnpm exec vitest run tests/contract`.
