# ShopGym

[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)


ShopGym is an integrated framework for realistic simulation and scalable benchmarking of e-commerce web agents, functions as both as a simulation environment and as a benchmark construction pipeline.

![shop-gym-pipeline](docs/imgs/shop-gym-pipeline.png)

## Components

The package is a mono-repo of three components:

| Package | Lang | Role |
|---|---|---|
| [`packages/shop_arena`](packages/shop_arena) | Python | **ShopArena** — Environment Factory that generates deterministic, self-contained sandbox shops (**SandboxShops**) from any live storefront. |
| [`packages/shop_guru`](packages/shop_guru) | Python | **ShopGuru** — Automated dataset generation pipeline that ingests a sandbox shop's catalog, navigation structure, and policies to synthesize grounded evaluation tasks across 7 skill categories. |
| [`packages/shop_backend`](packages/shop_backend) | TypeScript | **ShopBackend** — Local GraphQL API server hosting SandboxShop data. |
| [`packages/harness`](packages/harness) | Python | **Harness** — Runtime-agnostic plan-then-loop engine that orchestrates LLM agents; provides process lifecycle, workspace state, and telemetry for build / eval loops. |

A typical loop:

```
ShopArena  →  SandboxShop (static shop + data)  →  ShopBackend (GraphQL API)
                                ↓
                             ShopGuru  →  Evaluation dataset
```

## Requirements

- Python ≥ 3.12 with [`uv`](https://docs.astral.sh/uv/)
- Node ≥ 20 with [`pnpm`](https://pnpm.io/) ≥ 9
- One of the supported coding-agent CLIs (required for `shop_arena.explore`
  and the `shop_arena.gen` build loop):
  - `pi` (default agent runtime) — install per the
    [pi coding agent docs](https://pi.dev/). ShopGym runs `pi` with an
    isolated per-iteration config directory and disables user-installed
    extensions, skills, prompt templates, themes, context-file walk-up,
    and session persistence, so runs do not depend on `~/.pi/agent` or
    `~/.agents`. The harness loads the project `.env` into the `pi`
    subprocess for credentials such as `PI_PROXY_API_KEY`,
    `ANTHROPIC_API_KEY`, or `ANTHROPIC_OAUTH_TOKEN`, and writes isolated
    `models.json` provider overrides for `.env` routing values such as
    `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`; shell exports take
    precedence over `.env`.
  - `claude` (Anthropic Claude Code CLI) — install per the
    [Claude Code docs](https://docs.claude.com/claude-code/).

## Setup

```bash
# Python workspace (shop_guru, shop_arena)
uv sync

# TypeScript workspace (shop_backend) — also installs the
# `pi-playwright` skill into `node_modules/`. The repo's
# `.claude/skills/playwright-browser` symlink exposes that same skill
# tree to Claude Code; ShopArena renders the workspace skill path into
# each harness `AGENTS.md` and passes it as an explicit `pi --skill`
# path. No extra global install is needed.
pnpm install
```

Storefront templates live under
`packages/shop_arena/src/shop_arena/gen/templates/`. Hydrogen remains the
default generation template. A minimal React Vite SSR template is also
available and can be selected explicitly with `shop-gen --template react-vite`.

`shop_arena.gen` reads `OPENAI_API_KEY` / `OPENAI_BASE_URL` from a project
`.env` for `--image-backend openai` runs. The `pi` harness runtime also
loads the project `.env` into the isolated `pi` subprocess for
credentials such as `PI_PROXY_API_KEY` or provider API keys, and uses
`ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` to write isolated Pi provider
routing. Copy the template and fill in your keys when needed:

```bash
cp .env.example .env
# then edit .env to set OPENAI_API_KEY, PI_PROXY_API_KEY,
# provider API keys, and provider BASE_URL values
```

Shell exports take precedence over `.env` values.

If a `shop-gen` run fails during an early LLM-backed step such as
`synth_identity`, first verify the provider credentials visible to the
`pi` subprocess. The isolated runtime resolves `PI_PROXY_API_KEY` or provider
API keys through the generated Pi `models.json`; stale shell exports override
corrected values in `.env`.

### Verify Playwright installs

Run the doctor from the repo root after `uv sync` and `pnpm install`:

```bash
uv run shop-doctor
```

The command verifies the Python Playwright package and its Chromium
browser, which are used by BrowserGym-backed evaluation. It also verifies
the `pi-playwright` browser skill that ShopArena passes to agent runtimes
during exploration and visual checks.

If the Chromium check fails, install it once with:

```bash
uv run playwright install chromium
```

If the skill check fails, rerun `pnpm install`. ShopArena resolves the
workspace skill first at
`node_modules/pi-playwright/skills/playwright-browser`, then falls back
to global `pnpm` / `npm` installs.

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
# Optional: use the minimal React Vite SSR storefront instead of Hydrogen.
uv run shop-gen outputs/shop_manuals/<domain>/<run_id> --name mock_shop --template react-vite
```

Output lands in `outputs/shops/mock_shop/`. Re-running with the same `--name` resumes from the cached state.
Long LLM-backed data-synthesis stages persist cache artifacts as they
complete where possible; for example, `synth_product_details` writes
one details file per collection before the final manifest, so an
interrupted run can resume from valid partial collection files.
If the final visual sweep is resource-constrained on your machine, reduce
browser fan-out with `--final-eval-visual-max-concurrency 1` or `2`; this is
separate from the in-loop `--visual-judge-max-concurrency` setting.

### 3. Serve the shop

```bash
pnpm shop:host start mock_shop 4000  # hosting the mock_shop on localhost:4000
```

See [Hosting a generated shop](#hosting-a-generated-shop) for stop / logs / list management.

### 4. Generate a benchmark for the shop

Add the shop to a `shop_guru` config (see [`packages/shop_guru/configs/default.yaml`](packages/shop_guru/configs/default.yaml)
for the format — `shop_url` should match the storefront URL printed in step 3), then:

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

See [`packages/shop_guru/README.md`](packages/shop_guru/README.md) for
single-task debugging, skill filters, and the full output layout.

## Common commands

```bash
# Python
uv run pytest                    # run all Python tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run pyright                   # typecheck strict-clean Python packages

# ShopArena env-eval (measure an environment)
uv run shop-env-eval run <url> --no-rubric    # one-shot measurement → outputs/shop_env_evals/<host>/<run_id>/
uv run shop-env-eval compare <url-a> <url-b> [...]  # LLM-free AXTree distance from cohort mean → variance.json
uv run shop-env-eval visualize <run_dir>      # render the transition graph as interactive HTML

# TypeScript
pnpm -r build                    # build all TS packages
pnpm -r test                     # test all TS packages
pnpm --filter @shop-gym/shop-backend dev   # run the GraphQL server
pnpm lint                        # biome lint for shop_backend
pnpm format                      # biome format
```

## Hosting a generated shop

`pnpm shop:host` (alias for [`scripts/run-shop.sh`](scripts/run-shop.sh)) brings
up a generated shop end-to-end: the `shop_backend` GraphQL server pointed at
`outputs/shops/<name>/data/` plus the selected storefront artifact wired to it.
Both processes run detached; logs live under `.run/shops/`.

The storefront runs on `<port>`, `shop_backend` on `<port>+1000`. The port arg
is optional — if omitted, a free port is auto-picked from `4100..4199` (api:
`5100..5199`). The script also refuses to start if either port is already bound
by another process.

Generated local product images are exposed as same-origin `/images/...` URLs in
new storefront markup. The storefront server proxies those requests to
`shop_backend`, which serves the files from `outputs/shops/<name>/data/images/`.
For older Hydrogen artifacts with the legacy static `/images` route,
`shop:host` wires that route to the generated dataset images. For storefront
artifacts with no `/images` route at all, `shop:host` falls back to
backend-origin image URLs.

```bash
pnpm shop:host start mock_shop             # auto-pick a free port
pnpm shop:host start mock_shop 8000        # or pick explicitly
# → shop_backend on http://localhost:9000, storefront on http://localhost:8000

pnpm shop:host list -a                      # all shops, running + available
pnpm shop:host stop mock_shop           # or `stop all`
pnpm shop:host restart mock_shop
```

By default the script reads `outputs/shops/<name>/.shop_gen/template.json` and
hosts the matching build-loop artifact at
`outputs/shops/<name>/runs/build/artifact/<app-dir>/`, where dependencies and
the compiled production bundle live. Older Hydrogen shops without metadata
fall back to `artifact/hydrogen/`. Set `STOREFRONT_DIR=<path>` only when you
intentionally want to host a different hydrated storefront tree; `HYDROGEN_DIR`
is still accepted for older Hydrogen-only workflows.

## Repository layout

```
shop-gym/
├── AGENTS.md                   # agent behavior + coding guidelines
├── CLAUDE.md -> AGENTS.md
├── README.md
├── docs/
│   └── specs/                  # design specifications (intent, not reality)
├── packages/
│   ├── shop_arena/             # Python: SandboxShop factory
│   ├── shop_guru/              # Python: dataset generation
│   ├── shop_backend/           # TypeScript: GraphQL API server
│   └── harness/                # Python: plan-then-loop agent engine
├── pyproject.toml              # uv workspace root
├── pnpm-workspace.yaml         # pnpm workspace root
├── package.json                # TS tooling at repo root
├── tsconfig.base.json
├── biome.json
└── .editorconfig
```

## Citation

This repository contains code for the ShopGym paper:
[*ShopGym: An Integrated Framework for Realistic Simulation and Scalable
Benchmarking of E-Commerce Web Agents*](https://arxiv.org/abs/2605.16116).

```bibtex
@misc{savadikar2026shopgym,
    title         = {ShopGym: An Integrated Framework for Realistic Simulation and Scalable Benchmarking of E-Commerce Web Agents},
    author        = {Chinmay Savadikar and Mingyu Zhao and Yuanzheng Zhu and Han Li and Shuang Xie and Alberto Castelo and Tianfu Wu and Lingyun Wang},
    year          = {2026},
    eprint        = {2605.16116},
    archivePrefix = {arXiv},
    primaryClass  = {cs.AI},
    url           = {https://arxiv.org/abs/2605.16116}
}
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, coding standards, tests, and
pull request expectations. External contributions must pass the Shopify CLA
check, and all project spaces follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

MIT
