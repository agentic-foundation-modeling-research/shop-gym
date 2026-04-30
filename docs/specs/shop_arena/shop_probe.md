# ShopProbe (`packages/shop_arena/src/shop_probe`)

Status: **Spec (current)** · Version: **0.4**
Owners: ShopGym
Last updated: **2026-04-30**

> A reproducible measurement tool that scores a deployed storefront on
> two complementary dimensions — **capability coverage** and
> **scale / richness** — to quantify the structural fidelity of
> generated SandboxShops relative to a population of real Shopify
> storefronts.

---

## 1. Overview

The ShopGym paper validates that SandboxShops are reliable proxies for
real storefronts using **behavioral fidelity** — agreement on the
ShopGuru instruction-following benchmark run on each (source, sandbox)
pair. That answer is necessary but not sufficient: a reviewer can ask
whether agreement on a fixed task set generalizes, or whether the
sandbox is just narrow enough to look the same on those specific tasks.

`shop_probe` is the **structural fidelity** complement. It runs against
a deployed URL — sandbox or real — and emits a typed `ProbeReport`
keyed off a single, content-addressed rubric. Each rubric entry's
``type`` discriminator picks the runner:

- **`type: probe`.** Deterministic Playwright probe; pass/fail rolls
  into the headline coverage rollup.
- **`type: capture_judge`.** One LLM call over a per-shop screenshot +
  accessibility-tree bundle slice, dispatched to Anthropic or OpenAI
  based on the ``<provider>:<model>`` prefix on
  ``--capture-judge-model``. Verdict rolls into coverage_advanced.
- **`type: scale`.** Bundle-derived per-page richness (DOM size,
  interactables, form fields, accessibility-tree node counts) plus
  catalog counts (products, collections) read from the target's
  optional ``data_dir``. Descriptive only — does *not* contribute to
  coverage rollups.

`probe` + `capture_judge` answer "does this storefront expose the
modern-web features a real Shopify storefront has?"; `scale` answers
"is the action / observation space rich enough to be non-trivial for
an agent?".

The pipeline runs over two flat populations — `sandboxes:` and
`reals:` — defined in a `benchmark.yaml`. Group-vs-group fidelity is
the headline metric; pair semantics are intentionally absent.

---

## 2. Terminology

| Term            | Meaning                                                                                                         |
| --------------- | --------------------------------------------------------------------------------------------------------------- |
| Target          | A single deployed storefront URL plus its `(name, label)` identity. Labels are `sandbox` or `real`. May carry an optional `data_dir` pointing to `products.json` / `collections.json` for catalog counts. |
| Benchmark       | A YAML file listing two flat groups of targets (`sandboxes:` and `reals:`) — the input to `shop-probe eval`.    |
| Rubric          | The closed set of evals. Pinned to one version (`v3`) and content-addressed by SHA-256. Each entry has a `type` (`probe` / `capture_judge` / `scale`) that picks the runner. |
| Probe           | A deterministic Playwright callable that loads a target page and returns `passed: bool`.                        |
| Capture-judge   | A rubric entry whose verdict is produced by one LLM call (Anthropic or OpenAI) over a screenshot + a11y bundle. |
| Scale metrics   | Bundle-derived numerical features of a target (per-page richness + catalog counts). Descriptive only.           |
| ProbeReport     | The closed Pydantic schema written per target under `<out>/reports/<label>__<name>.json`.                       |

---

## 3. Current Status

The single-rubric, single-subcommand, single-axis simplification is
implemented:

- One rubric file: `packages/shop_arena/src/shop_probe/rubric/rubric.yaml`
  (75 entries: 66 deterministic probes, 8 capture-judge entries, 1
  scale entry). The hash is recomputed at load time and embedded in
  every report.
- One CLI entrypoint: `shop-probe eval`. No `--axes` flag — the
  rubric's `type` discriminator drives every runner. The earlier
  `run`, `aggregate-reruns`, `compare`, and `report` subcommands are
  gone.
- Reruns / flake-gate machinery is removed. The only resilience layer
  is the per-shop file cache (§5).
- The legacy BFS surface crawler is removed; scale metrics are now
  derived from the existing 5-page capture bundle and from each
  target's optional ``data_dir``.
- Capture-judge entries are the only LLM-driven verdicts shop-probe
  issues.

---

## 4. CLI

```
shop-probe eval --benchmark <yaml> --out <dir> [flags]
```

| Flag                        | Default                | Effect                                                                    |
| --------------------------- | ---------------------- | ------------------------------------------------------------------------- |
| `--benchmark <path>`        | _required_             | Benchmark YAML listing sandboxes and reals.                               |
| `--out <dir>`               | `outputs/shop_probe`   | Run-root. Writes `<out>/reports/`, `<out>/evidence/`, `<out>/figures/`.   |
| `--include-auth`            | _off_                  | Include rubric entries flagged `authenticated:` / `transactional:`.       |
| `--force`                   | _off_                  | Recompute every target instead of using the per-shop cache.               |
| `--capture-judge-model <id>`| `anthropic:claude-haiku-4-5` | Provider-prefixed model id for the capture-judge tier — `anthropic:<id>` or `openai:<id>`. |

Behavior:

1. Load `benchmark.yaml` and the pinned `v3` rubric.
2. For each target (sandboxes first, then reals) check the per-shop
   cache. On a hit, reuse it; on a miss, run every selected rubric
   entry through its type-specific runner (probe / capture_judge /
   scale), then write `<out>/reports/<label>__<name>.json`.
3. After every target has a report, render the two cohort tables
   under `<out>/figures/`:
   - `group_comparison.md` — three rows (sandbox, real, delta).
   - `per_shop_table.md` — one row per shop with per-tier coverage.

Exit codes: `0` on success, `2` on usage / validation errors.

---

## 5. Caching and resume

The cache key is a per-shop file: `<out>/reports/<label>__<name>.json`.
The hit/miss logic (in `shop_probe.cli._load_cached_report`) is:

1. If the file does not exist → miss.
2. If the file does not parse as `ProbeReport` → miss (will overwrite).
3. If the embedded `rubric_hash` does not match the loaded rubric →
   miss (rubric changed, results are stale).
4. Otherwise → hit; reuse the cached report verbatim.

This gives three useful properties for free:

- **Resume.** A run that crashes mid-cohort can be resumed by running
  `shop-probe eval` again — completed shops short-circuit through the
  cache.
- **Append.** Adding a new shop to `benchmark.yaml` and re-running
  processes only the new shop, then re-renders the figures.
- **Re-judge.** Bumping the rubric (any byte change → new content
  hash) invalidates every cached report at once.

Pass `--force` to ignore the cache and recompute every target.

The capture-bundle phase has its own bundle-on-disk reuse inside
`shop_probe.capture.bundle`: per-page `screenshot.png` and `a11y.json`
artifacts under `<out>/evidence/<label>__<name>/_bundle/<page>/` are
reused when present, so even a partial cache miss avoids redundant
Playwright work.

---

## 6. Rubric format

A rubric is a YAML file with a `version` string and a list of
`entries`. The loader hashes the raw UTF-8 bytes and embeds the digest
into every report.

Each entry carries a required `type` discriminator that picks the
runner. The other required fields depend on `type`:

| Field            | Type                                                              | When required                                                       |
| ---------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| `id`             | string                                                            | always — unique within a rubric.                                    |
| `type`           | `probe` \| `capture_judge` \| `scale`                             | always — picks the runner.                                          |
| `description`    | string                                                            | always — human-readable rationale.                                  |
| `category`       | enum                                                              | `probe` and `capture_judge` only — `site_shell`, `homepage`, etc.   |
| `level`          | `core` \| `modern` \| `advanced`                                  | `probe` and `capture_judge` only — rolls into `coverage_*`.         |
| `weight`         | int 1–3                                                           | `probe` and `capture_judge` only — per-category weight.             |
| `probe`          | dotted ref                                                        | `probe` only — must be `null` for the other two types.              |
| `capture_judge`  | inline block                                                      | `capture_judge` only — must be `null` for the other two types.      |
| `authenticated`  | bool                                                              | `probe` / `capture_judge` only — gated behind `--include-auth`.     |
| `transactional`  | bool                                                              | `probe` / `capture_judge` only — gated behind `--include-auth`.     |

A `capture_judge` block:

```yaml
- id: collection.sort.changes_order
  type: capture_judge
  category: collection
  level: advanced
  weight: 2
  description: Capture-judge — collection page exposes a sort control with multiple options.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [collection]
    judge_prompt: |
      Does the collection page expose a sort control (dropdown, segmented
      buttons, or similar) with two or more selectable sort options?
```

A `scale` entry (at most one per rubric):

```yaml
- id: site.scale
  type: scale
  description: |
    Per-page richness (DOM size, interactables, form fields,
    accessibility nodes) measured on the 5-page bundle, plus catalog
    counts (products, collections) from each target's data_dir.
```

`scale` entries take no inline configuration: the bundle is fixed at
five pages and the catalog source is per-target via `data_dir`.

The shipped rubric lives at
`packages/shop_arena/src/shop_probe/rubric/rubric.yaml`.

---

## 7. Output schema

One file per target: `<out>/reports/<label>__<name>.json`. The closed
Pydantic schema is `shop_probe.report.ProbeReport`:

```text
ProbeReport
├── target            : Target (name, base_url, label, data_dir?)
├── rubric_version    : str   (e.g. "v3")
├── rubric_hash       : str   (sha256 hex of rubric.yaml — cache key)
├── runner_version    : str
├── runtime           : BrowserMeta (python, playwright, chromium, viewport, …)
├── timestamp         : datetime (UTC, run start)
├── probe_results     : tuple[ProbeResult, …]
├── categories        : tuple[CategoryScore, …]   (per-category coverage)
├── coverage_core     : float ∈ [0, 1]
├── coverage_modern   : float ∈ [0, 1]
├── coverage_advanced : float ∈ [0, 1]            (deterministic + capture-judge)
├── coverage_weighted : float ∈ [0, 1]
├── scale             : ScaleMetrics | null       (null when no scale entry in rubric)
└── total_judge_cost_usd : float | null           (sum of capture-judge costs)
```

`ScaleMetrics` carries six optional numeric fields:
`median_dom_kb_gz`, `interactables_per_page_median`,
`form_fields_per_page_median`, `accessibility_nodes_per_page_median`
(medians over the bundle's applicable pages), and `catalog_products`
/ `catalog_collections` (read from `data_dir/products.json` and
`data_dir/collections.json` when `data_dir` is set; `None` otherwise).

Each `ProbeResult` carries `id`, `passed`, `evidence` (paths under
`<out>/evidence/<label>__<name>/`), `notes`, `duration_ms`, and — for
capture-judge entries — `judge_cost_usd` and `judge_model`. `scale`
entries do not produce a `ProbeResult` row.

The two figure tables under `<out>/figures/`:

- `group_comparison.md`:
  ```
  | Group                    | n_shops | Coverage weighted |
  |--------------------------|--------:|------------------:|
  | sandbox                  |       N |             0.xxx |
  | real                     |       M |             0.yyy |
  | delta (real - sandbox)   |     +d  |            +0.zzz |
  ```
- `per_shop_table.md`: one row per shop with `Coverage weighted`,
  `Coverage core`, `Coverage modern`, and an `In real envelope (scale)`
  count (sandbox shops only) showing how many populated scale metrics
  fall inside the real-group min/max envelope.

---

## 8. Appendix

### 8.1 Layout

```
packages/shop_arena/src/shop_probe/
├── cli.py                  # single `eval` entrypoint, type-dispatch on rubric entries
├── report.py               # ProbeReport + inner schemas
├── fidelity.py             # GroupSummary, BenchComparison, compute_bench_comparison
├── targets.py              # Bench, Target schemas (Target.data_dir for catalog counts)
├── bench.py                # benchmark.yaml loader
├── capture/                # 5-page screenshot + a11y + page-stats bundle (with on-disk reuse)
├── agent/                  # Anthropic + OpenAI clients + capture-judge runner
├── probes/                 # deterministic Playwright probes (one module per category)
├── rubric/                 # schema, loader, rubric.yaml
├── report_writer/          # group_comparison + per_shop tables
└── scale/                  # bundle-derived ScaleMetrics + catalog-counts reader
```

### 8.2 Verification commands

```bash
cd packages/shop_arena
uv run pyright src/shop_probe                       # 0 errors expected
uv run pytest tests/shop_probe                      # green (browser tests need Playwright)

# Smoke run: produces N reports + 2 figures.
uv run --package shop-arena shop-probe eval \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out /tmp/sp_smoke

# Re-run is a full cache-hit; no Anthropic / OpenAI calls.
uv run --package shop-arena shop-probe eval \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out /tmp/sp_smoke
```
