# ShopArena

Environment Factory that generates deterministic, self-contained sandbox shops
(**SandboxShops**) from any live storefront using modern web development stacks.

The `shop-arena` distribution ships three top-level modules:

- **`shop_gen`** — main SandboxShop generation pipeline. *v0.1.0* —
  step DAG runner, manual merge, data synthesis, hosting validation,
  build-harness loop, and advisory final eval. See
  [`src/shop_gen/README.md`](src/shop_gen/README.md) for module-level docs.
- **`shop_explore`** — storefront exploration pipeline that produces an
  anonymized **Shop Manual** (prose + structured capabilities + stats) from a
  live storefront. *v0.1 in progress* — prefetch, capabilities schema/merge,
  stats, synthesis, and the harness-driven plan/exec loop are wired up; live
  runtime smoke + release tasks are pending. See
  [`src/shop_explore/README.md`](src/shop_explore/README.md) for module-level
  docs.
- **`shop_probe`** — structural-fidelity measurement instrument. *v0.1
  (M1–M7 landed)* — Playwright capability probes (axis A), surface-area
  crawl (axis B), and a blinded LLM judge over agent trajectories (axis C),
  with cohort aggregation and paper figures. See
  [`src/shop_probe/README.md`](src/shop_probe/README.md) for module-level
  docs.

## Install (dev)

```bash
uv sync
```

## Usage

```bash
uv run shop-gen --help        # functional v0.1 surface
uv run shop-explore --help    # functional v0.1 surface
uv run shop-probe --help      # functional v0.1 surface
```

`shop-explore` exposes the full pipeline plus `--prefetch-only` and
`--synthesize-only` shortcuts; see the
[`shop_explore` README](src/shop_explore/README.md#usage) for details and the
output layout.

`shop-probe` ships three subcommands (`run` / `aggregate-reruns` / `report`)
and requires `playwright install chromium`; see the
[`shop_probe` README](src/shop_probe/README.md#usage) for details.

## Tests

```bash
uv run pytest packages/shop_arena/tests
```

`shop_explore` pipeline tests run against `harness.runtimes.replay`
cassettes — no network or LLM access required. The cassette record workflow
is documented in
[`src/shop_explore/README.md`](src/shop_explore/README.md#record-cassette-workflow).

`shop_probe` tests are hermetic: probe / surface / judge tests run against
an in-process sandbox storefront (`tests/shop_probe/_sandbox.py`); no
network or LLM access required.
