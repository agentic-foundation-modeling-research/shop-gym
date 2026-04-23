# ShopGym

Sandbox shop websites with modern features for **building and evaluating
shopping LLM agents**. ShopGym is a mono-repo of three components that
together produce reproducible shopping environments and evaluation datasets.

## Components

| Package | Lang | Role |
|---|---|---|
| [`packages/shop_arena`](packages/shop_arena) | Python | **ShopArena** — Environment Factory that generates deterministic, self-contained sandbox shops (**SandboxShops**) from any live storefront. Ships two modules: `shop_gen` (generation pipeline) and `shop_explore` (storefront exploration). |
| [`packages/shop_guru`](packages/shop_guru) | Python | **ShopGuru** — Automated dataset generation pipeline that ingests a sandbox shop's catalog, navigation structure, and policies to synthesize grounded evaluation tasks across 7 skill categories. |
| [`packages/shop_backend`](packages/shop_backend) | TypeScript | **ShopBackend** — Local GraphQL API server that mirrors Shopify's Storefront/Admin API against SandboxShop data. Serves both as a benchmarking backend and an RL environment. |

A typical loop:

```
ShopArena  →  SandboxShop (static shop + data)  →  ShopBackend (GraphQL API)
                                ↓
                             ShopGuru  →  Evaluation dataset
```

## Requirements

- Python ≥ 3.11 with [`uv`](https://docs.astral.sh/uv/)
- Node ≥ 20 with [`pnpm`](https://pnpm.io/) ≥ 9

## Setup

```bash
# Python workspace (shop_guru, shop_arena)
uv sync

# TypeScript workspace (shop_backend)
pnpm install
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

## Repository layout

```
shop-gym/
├── AGENT.md                    # agent behavior + coding guidelines
├── CLAUDE.md -> AGENT.md
├── README.md
├── docs/
│   └── specs/                  # design specifications (intent, not reality)
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

## Status

Early scaffolding. Packages contain smoke tests and placeholder entrypoints
only. See `docs/specs/` for planned design.

## License

MIT
