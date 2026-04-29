# ShopGym

Sandbox shop websites with modern features for **building and evaluating
shopping LLM agents**. ShopGym is a mono-repo of three components that
together produce reproducible shopping environments and evaluation datasets.

## Components

| Package | Lang | Role |
|---|---|---|
| [`packages/shop_arena`](packages/shop_arena) | Python | **ShopArena** — Environment Factory that generates deterministic, self-contained sandbox shops (**SandboxShops**) from any live storefront. Ships three modules: [`shop_gen`](packages/shop_arena/src/shop_gen) (generation pipeline; **v0.1.0** — see [spec](docs/specs/shop_arena/shop_gen.md) and [impl plan](docs/impl/shop_gen_implementation.md)), [`shop_explore`](packages/shop_arena/src/shop_explore) (storefront exploration; **v0.1 in progress** — see [spec](docs/specs/shop_arena/shop_explore.md) and [impl plan](docs/impl/shop_explore_implementation.md)), and [`shop_probe`](packages/shop_arena/src/shop_probe) (structural-fidelity measurement instrument; **v0.1 (M1–M7 landed)** — see [spec](docs/specs/shop_arena/web_probe.md) and [impl plan](docs/impl/web_probe_implementation.md)). |
| [`packages/shop_guru`](packages/shop_guru) | Python | **ShopGuru** — Automated dataset generation pipeline that ingests a sandbox shop's catalog, navigation structure, and policies to synthesize grounded evaluation tasks across 7 skill categories. |
| [`packages/shop_backend`](packages/shop_backend) | TypeScript | **ShopBackend** — Local GraphQL API server hosting SandboxShop data. |

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
uv run --package shop-arena playwright install chromium  # only if running shop-probe

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
pnpm shop:host start mock_hardware             # auto-pick a free port
pnpm shop:host start mock_hardware 8000        # or pick explicitly
# → shop_backend on http://localhost:9000, Hydrogen on http://localhost:8000

pnpm shop:host list -a                      # all shops, running + available
pnpm shop:host logs mock_hardware api       # tail shop_backend log
pnpm shop:host logs mock_hardware hydrogen  # tail Hydrogen log
pnpm shop:host stop mock_hardware           # or `stop all`
pnpm shop:host restart mock_hardware
```

The script picks the Hydrogen tree in this order: `HYDROGEN_DIR` env override
→ `outputs/shops/<name>/hydrogen/` (if `node_modules` exists) →
`outputs/shops/<name>/runs/build/artifact/hydrogen/` (the build-loop output,
where deps live by default).

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

Early development. `shop_arena/shop_gen` is at **v0.1.0** — M0–M6
landed (step DAG, manual merge, data synth, validation, build harness
loop, advisory final eval). `shop_arena/shop_explore` is at **v0.1
(in progress)** — M1–M3 plus M5 docs landed; M4 live-runtime smoke +
final tag pending. `shop_arena/shop_probe` is at **v0.1 (M1–M7
landed)** — three-axis fidelity measurement (capability / surface /
judge), cohort aggregation, and paper figures all render from
versioned reports. See
[`docs/impl/shop_gen_implementation.md`](docs/impl/shop_gen_implementation.md),
[`docs/impl/shop_explore_implementation.md`](docs/impl/shop_explore_implementation.md),
and
[`docs/impl/web_probe_implementation.md`](docs/impl/web_probe_implementation.md)
for milestone status. Other packages contain placeholder entrypoints only.
See `docs/specs/` for planned design.

## License

MIT
