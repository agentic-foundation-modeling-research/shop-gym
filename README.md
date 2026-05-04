# ShopGym

[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)


Sandbox shop websites with modern features for **building and evaluating
shopping LLM agents**. ShopGym is a mono-repo of three components that
together produce reproducible shopping environments and evaluation datasets.

## Components

| Package | Lang | Role |
|---|---|---|
| [`packages/shop_arena`](packages/shop_arena) | Python | **ShopArena** — Environment Factory that generates deterministic, self-contained sandbox shops (**SandboxShops**) from any live storefront. |
| [`packages/shop_guru`](packages/shop_guru) | Python | **ShopGuru** — Automated dataset generation pipeline that ingests a sandbox shop's catalog, navigation structure, and policies to synthesize grounded evaluation tasks across 7 skill categories. |
| [`packages/shop_backend`](packages/shop_backend) | TypeScript | **ShopBackend** — Local GraphQL API server hosting SandboxShop data. |

A typical loop:

```
ShopArena  →  SandboxShop (static shop + data)  →  ShopBackend (GraphQL API)
                                ↓
                             ShopGuru  →  Evaluation dataset
```

## Requirements

- Python ≥ 3.12 with [`uv`](https://docs.astral.sh/uv/)
- Node ≥ 20 with [`pnpm`](https://pnpm.io/) ≥ 9
- A coding-agent CLI is required for `shop_arena.explore` and the
  `shop_arena.gen` build loop. The runtime is pluggable; any CLI that
  accepts a single `-p <prompt>` argument and writes a structured trace
  to disk can be wired in via `harness.runtimes`.

## Setup

```bash
# Python workspace (shop_guru, shop_arena)
uv sync

# TypeScript workspace (shop_backend) — also installs the
# Playwright skill used by `shop_arena.explore` and the build loop's
# visual verifier (no extra global install needed).
pnpm install
```

Storefront templates live under
`packages/shop_arena/src/shop_arena/gen/templates/`. The generation build
step expects a Hydrogen-compatible template at
`packages/shop_arena/src/shop_arena/gen/templates/hydrogen/`; an open-source
template can be adapted there to bootstrap generated shops.

`shop_arena.gen` reads `OPENAI_API_KEY` / `OPENAI_BASE_URL` from a project
`.env` for `--image-backend openai` runs. Copy the template and fill in
your key when needed:

```bash
cp .env.example .env
# then edit .env to set OPENAI_API_KEY and/or ANTHROPIC_API_KEY
```

Shell exports take precedence over `.env` values.

## Quick start

A full ShopArena pipeline is three commands: **explore** a real
storefront → **generate** a SandboxShop from the resulting manual →
**serve** it locally for agents to interact with.

### 1. Explore a storefront

```bash
uv run shop-explore https://example-shop.com
# → outputs/shop_manuals/<domain>/<run_id>/manual.md (+ artifact/, run.json)
```

`<run_id>` is timestamped; the printed final line shows the exact path.

### 2. Generate a SandboxShop

```bash
# Without image gen — placeholder PNGs (fast, deterministic, offline).
uv run shop-gen outputs/shop_manuals/<domain>/<run_id> --name mock_shop
```

Output lands in `outputs/shops/mock_shop/`. Re-running with the same `--name` resumes from the cached state.

### 3. Serve the shop

```bash
pnpm shop:host start mock_shop 4000  # hosting the mock_shop on localhost:4000
```

See [Hosting a generated shop](#hosting-a-generated-shop) for stop / logs / list management.

### 4. Generate a benchmark for the shop

Add the shop to a `shop_guru` config (see [`packages/shop_guru/configs/default.yaml`](packages/shop_guru/configs/default.yaml)
for the format — `shop_url` should match the Hydrogen URL printed in step 3), then:

```bash
uv run shop-guru build --shop mock_shop
# → outputs/shop_guru/mock_shop/benchmarks/ — one file per skill
```

### 5. Run evaluation against the shop

Requires `OPENAI_API_KEY` in `.env` and Playwright's Chromium (`uv run playwright install chromium`). 
The shop from step 3 must be running.

```bash
uv run shop-guru eval --shop mock_shop
# → outputs/shop_guru/mock_shop/<timestamp>_.../aggregate.json
```

## Common commands

```bash
# Python
uv run pytest                    # run all Python tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run pyright                   # typecheck

# TypeScript
pnpm -r build                    # build all TS packages
pnpm -r test                     # test all TS packages
pnpm --filter @shop-gym/shop-backend dev   # run the GraphQL server
pnpm lint                        # biome lint
pnpm format                      # biome format
```

## Hosting a generated shop

`pnpm shop:host` (alias for [`scripts/run-shop.sh`](scripts/run-shop.sh)) brings
up a generated shop end-to-end: the `shop_backend` GraphQL server pointed at
`outputs/shops/<name>/data/` plus the Hydrogen storefront wired to it. Both
processes run detached; logs live under `.run/shops/`.

Hydrogen runs on `<port>`, `shop_backend` on `<port>+1000`. The port arg is
optional — if omitted, a free port is auto-picked from `4100..4199` (api:
`5100..5199`). The script also refuses to start if either port is already
bound by another process.

```bash
pnpm shop:host start mock_shop             # auto-pick a free port
pnpm shop:host start mock_shop 8000        # or pick explicitly
# → shop_backend on http://localhost:9000, Hydrogen on http://localhost:8000

pnpm shop:host list -a                      # all shops, running + available
pnpm shop:host stop mock_shop           # or `stop all`
pnpm shop:host restart mock_shop
```

The script picks the Hydrogen tree in this order: `HYDROGEN_DIR` env override
→ `outputs/shops/<name>/hydrogen/` (if `node_modules` exists) →
`outputs/shops/<name>/runs/build/artifact/hydrogen/` (the build-loop output,
where deps live by default).

## Repository layout

```
shop-gym/
├── README.md
├── packages/
│   ├── shop_arena/             # Python: SandboxShop factory
│   ├── shop_guru/              # Python: dataset generation
│   └── shop_backend/           # TypeScript: GraphQL API server
├── pyproject.toml              # uv workspace root
├── pnpm-workspace.yaml         # pnpm workspace root
├── package.json                # TS tooling at repo root
├── tsconfig.base.json
├── biome.json
└── .editorconfig
```

## License

MIT
