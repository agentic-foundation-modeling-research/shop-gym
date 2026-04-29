# ShopProbe

Reproducible measurement instrument that scores any deployed
storefront on three independent axes — **capability coverage**, **surface
area**, and **agent indistinguishability** — and produces group-vs-group
fidelity numbers between a population of generated SandboxShops and a
population of real Shopify storefronts.

`shop-probe` is deployment-agnostic: it takes a base URL and assumes a storefront (`/`, `/collections/*`, `/products/*`, `/cart`,
`/search`, `/policies/*`, `/pages/*`). It does not care whether the target is
a real Shopify shop, a SandboxShop served by `shop_backend`, or another
vendor's storefront. Specs:
[`docs/specs/shop_arena/web_probe.md`](../../../../docs/specs/shop_arena/web_probe.md)
plus the
[`web_probe_patch.md`](../../../../docs/specs/shop_arena/web_probe_patch.md)
that drops pair semantics and adopts the three-stage population pipeline this
README documents.

`shop-probe` ships as a module of the [`shop-arena`](../../) distribution,
sibling to [`shop_gen`](../shop_gen) and [`shop_explore`](../shop_explore).

## Pipeline

The fast path is a single `eval` invocation that runs every stage end-to-end
for every target in a benchmark YAML:

```
shop-probe eval --benchmark benchmark.yaml --out OUT/ [--reruns N]
  → OUT/reports/<label>__<name>__rerunK.json (one per target × rerun)
  → OUT/reports/<label>__<name>.json         (when N >= 2)
  → OUT/figures/{group_comparison,per_shop_table}.md
  → OUT/figures/{radar,surface,turing}.svg
```

The lower-level subcommands stay available for power users:

```
Stage 1: per-shop probe
  shop-probe run <url> --name shop_alpha --label sandbox --out OUT/

Stage 1.5: per-target rerun consolidation
  shop-probe aggregate-reruns --runs OUT/reports/sandbox__shop_alpha__rerun{1,2,3}.json --out OUT/

Stage 2: group aggregation + group-vs-group comparison
  shop-probe report --benchmark benchmark.yaml --out OUT/

Stage 3 (reserved): cherry-pick one shop, compare to others
  shop-probe compare --benchmark benchmark.yaml --shop shop_alpha
  → NotImplementedError stub for now
```

| Axis | What it measures | Implementation |
| ---- | ---------------- | -------------- |
| **A — Capability coverage** | Does it have the modern-web features a real Shopify storefront has? (predictive search, filter URL-state sync, accordion PDP, …) | ~80 deterministic Playwright probes from a versioned rubric. `core / modern / advanced` levels. `probes/`, `rubric/v1.yaml` and `v1.1.yaml`. |
| **B — Surface area** | Is the action/observation space rich enough to be non-trivial for an agent? | Crawl-derived metrics: distinct templates, interactables/template, forms/fields, routes, catalog combinatorics, DOM size. `surface/`. |
| **C — Agent indistinguishability** | From an agent's POV, is the sandbox group distinguishable from the real-shop group? | Per-shop Turing-test classifier over anonymized agent trajectories; group-level accuracy aggregated at stage 2. `judge/`. |

The v0.1 benchmark template — three sandboxes vs three reals — is shipped
as [`benchmark.example.yaml`](benchmark.example.yaml). Copy it to
`outputs/shop_probe/benchmark.yaml` (or anywhere else) and substitute the
real `base_url` values before running.

## Install (dev)

```bash
uv sync
uv run --package shop-arena playwright install chromium
```

## Usage

The `shop-arena` distribution installs the `shop-probe` console script with
five subcommands:

| Subcommand          | Purpose                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| `eval`              | End-to-end driver: probes every benchmark target N times, consolidates reruns, renders figures.  |
| `run`               | Drive Playwright probes (axes A/B/C) against one storefront and emit a `ProbeReport` JSON.       |
| `aggregate-reruns`  | Consolidate an N≥2 rerun group for one target into a canonical report with per-probe flake rate. |
| `report`            | Aggregate a benchmark's reports into the group comparison + paper figures.                       |
| `compare`           | Stage-3 cherry-pick inspection (reserved; raises `NotImplementedError`).                         |

### Run-root layout

Every subcommand takes a single `--out` argument pointing at a *run-root
directory* (default `outputs/shop_probe`). The run root has a fixed
subdirectory layout:

| Subdirectory          | Written by                       | Contents                                                                    |
| --------------------- | -------------------------------- | --------------------------------------------------------------------------- |
| `<out>/reports/`      | `run`, `aggregate-reruns`, `eval` | One `ProbeReport` JSON per (target, rerun). Raw runs are `<label>__<name>__rerun<N>.json`; consolidated runs are `<label>__<name>.json`. |
| `<out>/evidence/`     | `run`, `eval`                    | Per-run evidence directory `<label>__<name>__rerun<N>/`.                    |
| `<out>/figures/`      | `report`, `eval`                 | Paper figures (group_comparison, per_shop_table, radar, surface, turing).   |

### One-shot pipeline (`eval`)

The simplest way to score a benchmark end-to-end:

```bash
uv run shop-probe eval \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out outputs/shop_probe \
    --reruns 3 \
    --rubric v1 \
    --axes A,B
```

For each target in `benchmark.yaml`:
1. probes it `--reruns` times → `<label>__<name>__rerun{1..N}.json`
2. when `--reruns >= 2`, consolidates → `<label>__<name>.json` (and applies
   `--gate` if set)
3. once every target is done, runs the `report` stage → `figures/`

`eval` aborts on the first failed probe or rerun-gate violation, exiting
non-zero. Re-running `eval` re-probes from scratch (no skip-existing in v1).

Flag forwarding:

| `eval` flag         | Forwarded to                                |
| ------------------- | ------------------------------------------- |
| `--rubric`, `--axes`, `--include-auth`, `--record-har` | each `run` invocation |
| `--gate`            | each `aggregate-reruns` invocation (only when `--reruns >= 2`) |
| `--baselines-dir`   | the final `report` invocation               |

### Run probes against one storefront

```bash
uv run shop-probe run https://shop-alpha.example.invalid \
    --name shop_alpha \
    --label sandbox \
    --rubric v1 \
    --axes A,B \
    --rerun-index 1 \
    --out outputs/shop_probe
# writes outputs/shop_probe/reports/sandbox__shop_alpha__rerun1.json
# writes outputs/shop_probe/evidence/sandbox__shop_alpha__rerun1/...
```

Notable flags:

- `--name` — filename-friendly identifier; unique within the benchmark.
- `--label` — `sandbox` or `real`.
- `--axes` — `A` or `A,B` today; axis C lands in a follow-on patch.
- `--rubric` — `v1` / `v1.1` / `v1.2` / `v1.3` (packaged) or a path to a custom YAML.
  `v1.2` adds an 8-probe `level: advanced` behavioral tier on top of v1.1
  that drives interactions (sort, filter, pagination, variant swap, qty
  spinner, predictive search, cart-count badge update) and asserts the page
  state actually changes via deterministic Playwright selectors. `v1.3`
  replaces that 8-probe tier with `level: agent_driven` entries scored by
  an LLM agent + LLM judge — see [v1.3 agent-driven tier](#v13-agent-driven-tier).
- `--include-auth` — opt into the v1.1 authenticated/transactional slice
  (default: skipped). The 8 v1.2 advanced probes are unauthenticated and
  ship without this gate.
- `--record-har` — save a HAR per probe under
  `<out>/evidence/<label>__<name>__rerun<N>/<probe_id>/network.har`.
- `--rerun-index` — 1-indexed slot in a rerun group, consumed by
  `aggregate-reruns`.

### v1.3 agent-driven tier

`--rubric v1.3` resolves a 74-entry rubric (66 v1.1 entries verbatim + 8
agent-driven entries replacing the v1.2 advanced tier). Each agent-driven
entry carries an inline `agent_task:` block (`goal`, `judge_prompt`,
`precondition_url_attr`, optional `step_budget` / `timeout_s`) that drives
one run of `harness.run_plan_exec_loop` against the `playwright-browser`
skill. Before/after screenshots plus the projected trajectory are then
passed to a vision Anthropic Messages API judge that returns a structured
pass/fail verdict; the verdict and its reasoning land on the emitted
`ProbeOutcome`, and per-probe agent + judge cost is recorded on the
report. Adding a 9th task is one YAML edit — no Python wrapper needed.

Five `--agent-*` flags are accepted by both `run` and `eval` (`eval`
forwards them verbatim into each spawned `run` invocation). They are inert
when the selected rubric has no `level: agent_driven` entries (e.g. `v1`,
`v1.1`, `v1.2`):

| Flag                          | Default            | Purpose                                                                                  |
| ----------------------------- | ------------------ | ---------------------------------------------------------------------------------------- |
| `--agent-runtime`             | `claude_code`      | Harness runtime back-end for v1.3 agent-driven probes (`claude_code` or `pi`).           |
| `--agent-model`               | `claude-opus-4-7`  | Model id passed to the agent runtime for plan/exec turns.                                |
| `--agent-step-budget`         | `15`               | Default max iterations for the harness plan/exec loop; per-task overrides win.           |
| `--agent-timeout-s`           | `180`              | Default wall-clock budget (seconds) for one agent task run; per-task overrides win.      |
| `--agent-judge-model`         | `claude-opus-4-7`  | Model id used for the vision completion judge.                                           |

```bash
uv run shop-probe run https://shop-alpha.example.invalid \
    --name shop_alpha --label sandbox \
    --rubric v1.3 --reruns 1 \
    --out outputs/shop_probe
```

Each agent-driven probe persists its harness trajectory under
`<out>/evidence/<label>__<name>__rerun<N>/<probe_id>/harness/` (plan,
iteration screenshots, `trajectory.json`). Per-probe `judge_cost_usd` and
`agent_cost_usd` are recorded on the `ProbeResult`; `ProbeReport` exposes
`total_judge_cost_usd` and `total_agent_cost_usd`.

**Cost expectation** (defaults; one cohort = 7 shops × 8 probes × 4 reruns
= 224 agent runs + 224 judge calls):

| Configuration                              | Cohort cost |
| ------------------------------------------ | ----------- |
| Default (`--agent-model claude-opus-4-7`)  | ~$72        |
| Sonnet (`--agent-model claude-sonnet-4-6`) | ~$15        |

`v1` / `v1.1` / `v1.2` cohorts are unaffected — they issue zero Anthropic
calls regardless of the `--agent-*` flag values.

### Consolidate reruns

```bash
uv run shop-probe aggregate-reruns \
    --runs outputs/shop_probe/reports/sandbox__shop_alpha__rerun{1,2,3}.json \
    --out outputs/shop_probe \
    --gate 0.1
# writes outputs/shop_probe/reports/sandbox__shop_alpha.json (consolidated)
```

Exits non-zero when any probe's flake rate exceeds `--gate` (spec §5.8).

### Render the benchmark figures

```bash
uv run shop-probe report \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out outputs/shop_probe
# reads outputs/shop_probe/reports/, writes outputs/shop_probe/figures/
```

`<out>/reports/` must contain one report per benchmark `Target`. The
consolidated `<label>__<name>.json` is preferred; the highest-N raw
`<label>__<name>__rerun<N>.json` is used as a fallback. Outputs:

| File                     | Content                                                                            |
| ------------------------ | ---------------------------------------------------------------------------------- |
| `group_comparison.md`    | Three-row table: sandbox group / real group / delta.                               |
| `per_shop_table.md`      | One row per shop with coverage_weighted, in-real-envelope count, judge accuracy.   |
| `radar.svg`              | Axis-A coverage radar over the real-shop envelope.                                 |
| `surface.svg`            | Axis-B per-metric bar chart with real-shop envelope rectangles + sandbox dots.     |
| `turing.svg`             | Axis-C two-bar chart of group judge accuracy plus the indistinguishability gap; emitted only when judge calls are present. |
| `supplement_table.md`    | Prior-work environment table when `--baselines-dir` is supplied.                   |

## Tests

```bash
uv run pytest packages/shop_arena/tests/shop_probe
```

Tests are hermetic — probe / surface / judge tests run against an in-process
sandbox storefront (`tests/shop_probe/_sandbox.py`); no network or LLM access
required.
