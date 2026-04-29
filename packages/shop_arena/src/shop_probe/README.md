# ShopProbe

Reproducible measurement instrument that scores any deployed Shopify-shaped
storefront on three independent axes — **capability coverage**, **surface
area**, and **agent indistinguishability** — to quantify the structural
fidelity of a generated SandboxShop relative to its source storefront, and
against external benchmark environments.

`shop-probe` is deployment-agnostic: it takes a base URL and assumes a
Shopify-shaped storefront (`/`, `/collections/*`, `/products/*`, `/cart`,
`/search`, `/policies/*`, `/pages/*`). It does not care whether the target is
a real Shopify shop, a SandboxShop served by `shop_backend`, or another
vendor's storefront. Spec:
[`docs/specs/shop_arena/web_probe.md`](../../../../docs/specs/shop_arena/web_probe.md);
implementation plan:
[`docs/impl/web_probe_implementation.md`](../../../../docs/impl/web_probe_implementation.md).

`shop-probe` ships as a module of the [`shop-arena`](../../) distribution,
sibling to [`shop_gen`](../shop_gen) and [`shop_explore`](../shop_explore).

## Status

v0.1 (M1–M7 landed). The three axes, the cohort aggregation, and the four
paper figures all render from versioned reports without manual editing.

| Axis | What it measures | Implementation |
| ---- | ---------------- | -------------- |
| **A — Capability coverage** | Does it have the modern-web features a real Shopify storefront has? (predictive search, filter URL-state sync, accordion PDP, …) | ~80 deterministic Playwright probes from a versioned rubric. `core / modern / advanced` levels. `probes/`, `rubric/v1.yaml` and `v1.1.yaml`. |
| **B — Surface area** | Is the action/observation space rich enough to be non-trivial for an agent? | Crawl-derived metrics: distinct templates, interactables/template, forms/fields, routes, catalog combinatorics, DOM size. `surface/`. |
| **C — Agent indistinguishability** | From an agent's POV, is the sandbox distinguishable from a real shop? | Blinded LLM judge over agent trajectories: Likert + pairwise, with anonymization, swap-consistency and cross-judge κ checks. `judge/`. |

The v0.1 cohort — 3 (source, sandbox) pairs + 3 unpaired real shops — is
defined in [`cohort.yaml`](cohort.yaml); rationale and the
anonymization-sufficiency ablation live in spec
[`web_probe.md`](../../../../docs/specs/shop_arena/web_probe.md) §8.6.
Two sandbox URLs in the cohort are `TBD` pending a `shop-gen` deployment
(spec §8.5 Q3).

## Install (dev)

```bash
uv sync
uv run --package shop-arena playwright install chromium
```

## Usage

The `shop-arena` distribution installs the `shop-probe` console script with
three subcommands:

| Subcommand        | Purpose                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------ |
| `run`             | Drive Playwright probes (axes A/B/C) against one storefront and emit a `ProbeReport` JSON.       |
| `aggregate-reruns`| Consolidate an N=3 rerun group for one target into a canonical report with per-probe flake rate. |
| `report`          | Aggregate a cohort of reports into the four paper figures (radar, surface, Turing, fidelity).    |

### Run-root layout

Every subcommand takes a single `--out` argument pointing at a *run-root
directory* (default `outputs/shop_probe`). The run root has a fixed
subdirectory layout:

| Subdirectory          | Written by         | Contents                                                                    |
| --------------------- | ------------------ | --------------------------------------------------------------------------- |
| `<out>/reports/`      | `run`, `aggregate-reruns` | One `ProbeReport` JSON per (target, rerun). Raw runs are `<safe(label)>__rerun<N>.json`; consolidated runs are `<safe(label)>.json`. |
| `<out>/evidence/`     | `run`              | Per-run evidence directory `<safe(label)>__rerun<N>/`.                      |
| `<out>/figures/`      | `report`           | Paper figures (radar, surface, Turing, fidelity table, supplement table).   |

`/` in `Target.label` is rewritten to `__` for filename safety
(e.g. `source/1` → `source__1`).

### Run probes against one storefront

```bash
uv run shop-probe run https://source-1.example.invalid \
    --label source/1 \
    --kind source \
    --pair-id pair_1 \
    --rubric v1 \
    --axes A,B \
    --rerun-index 1 \
    --out outputs/shop_probe
# writes outputs/shop_probe/reports/source__1__rerun1.json
# writes outputs/shop_probe/evidence/source__1__rerun1/...
```

Notable flags:

- `--axes` — `A`, `A,B`, or `A,B,C`.
- `--rubric` — `v1` / `v1.1` (packaged) or a path to a custom YAML.
- `--kind` (`sandbox|source|real_unpaired`) and `--pair-id` — required pair
  membership for cohort aggregation (spec §5.2).
- `--include-auth` — opt into the v1.1 authenticated/transactional slice
  (default: skipped).
- `--record-har` — save a HAR per probe under
  `<out>/evidence/<safe(label)>__rerun<N>/<probe_id>/network.har`.
- `--rerun-index` — 1-indexed slot in an N=3 rerun group, consumed by
  `aggregate-reruns`.

### Consolidate N=3 reruns

```bash
uv run shop-probe aggregate-reruns \
    --runs outputs/shop_probe/reports/source__1__rerun{1,2,3}.json \
    --out outputs/shop_probe \
    --gate 0.1
# writes outputs/shop_probe/reports/source__1.json (consolidated)
```

Exits non-zero when any probe's flake rate exceeds `--gate` (spec §5.8).

### Render the cohort figures

```bash
uv run shop-probe report \
    --cohort packages/shop_arena/src/shop_probe/cohort.yaml \
    --out outputs/shop_probe
# reads outputs/shop_probe/reports/, writes outputs/shop_probe/figures/
```

`<out>/reports/` must contain one report per cohort `Target`. The
consolidated `<safe(label)>.json` is preferred; the highest-N raw
`<safe(label)>__rerun<N>.json` is used as a fallback. Outputs:

| File                     | Content                                                     |
| ------------------------ | ----------------------------------------------------------- |
| `fidelity_table.md`      | Per-pair fidelity table (T6.1).                             |
| `radar.svg`              | Axis-A coverage radar over the real-shop envelope (T6.2).   |
| `surface.svg`            | Axis-B per-metric bar chart with real-shop range bars (T6.3). |
| `turing.svg`             | Axis-C judge accuracy with bootstrap CIs (T6.4); emitted only when judge calls are present. |
| `supplement_table.md`    | Prior-work environment table when `--baselines-dir` is supplied (T7.5). |

## Tests

```bash
uv run pytest packages/shop_arena/tests/shop_probe
```

Tests are hermetic — probe / surface / judge tests run against an in-process
sandbox storefront (`tests/shop_probe/_sandbox.py`); no network or LLM access
required.
