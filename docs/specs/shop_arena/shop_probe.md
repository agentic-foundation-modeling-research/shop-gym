# ShopProbe (`packages/shop_arena/src/shop_probe`)

Status: **Spec (current)** · Version: **0.3**
Owners: ShopGym
Last updated: **2026-04-30**

> A reproducible measurement tool that scores a deployed storefront on
> two axes — **capability coverage** and **surface area** — to quantify
> the structural fidelity of generated SandboxShops relative to a
> population of real Shopify storefronts.

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
that quantifies the storefront on two orthogonal axes:

- **Axis A — Capability coverage.** A closed, versioned rubric of
  presence probes covering core / modern / advanced tiers. Most
  entries are deterministic Playwright probes. A handful of advanced
  entries are **capture-judge** entries (a single Anthropic Messages
  API call over a per-shop screenshot + accessibility-tree bundle).
  *Answers: does this storefront expose the modern-web features a real
  Shopify storefront has?*
- **Axis B — Surface area.** Quantitative crawl-derived metrics:
  distinct templates, interactables per template, forms / fields,
  routes, catalog combinatorics, DOM size. *Answers: is the
  action / observation space rich enough to be non-trivial for an
  agent?*

The pipeline runs over two flat populations — `sandboxes:` and
`reals:` — defined in a `benchmark.yaml`. Group-vs-group fidelity is
the headline metric; pair semantics are intentionally absent.

---

## 2. Terminology

| Term            | Meaning                                                                                                         |
| --------------- | --------------------------------------------------------------------------------------------------------------- |
| Target          | A single deployed storefront URL plus its `(name, label)` identity. Labels are `sandbox` or `real`.             |
| Benchmark       | A YAML file listing two flat groups of targets (`sandboxes:` and `reals:`) — the input to `shop-probe eval`.    |
| Rubric          | The closed set of capability checks. Pinned to one version (`v2`) and content-addressed by SHA-256.             |
| Probe           | A deterministic Playwright callable that loads a target page and returns `passed: bool`.                        |
| Capture-judge   | A rubric entry whose verdict is produced by one Anthropic Messages API call over a screenshot + a11y bundle.    |
| Surface metrics | Crawl-derived numerical features of a target (axis B).                                                          |
| ProbeReport     | The closed Pydantic schema written per target under `<out>/reports/<label>__<name>.json`.                       |

---

## 3. Current Status

The single-rubric, single-subcommand simplification is implemented:

- One rubric file: `packages/shop_arena/src/shop_probe/rubric/v2.yaml`
  (74 entries). The hash is recomputed at load time and embedded in
  every report.
- One CLI entrypoint: `shop-probe eval`. The earlier `run`,
  `aggregate-reruns`, `compare`, and `report` subcommands are gone.
- Reruns / flake-gate machinery is removed. The only resilience layer
  is the per-shop file cache (§5).
- The axis-C agent-judge pipeline is removed. Capture-judge entries
  inside axis A are the only LLM-driven verdicts shop-probe issues.

---

## 4. CLI

```
shop-probe eval --benchmark <yaml> --out <dir> [flags]
```

| Flag                        | Default                | Effect                                                                    |
| --------------------------- | ---------------------- | ------------------------------------------------------------------------- |
| `--benchmark <path>`        | _required_             | Benchmark YAML listing sandboxes and reals.                               |
| `--out <dir>`               | `outputs/shop_probe`   | Run-root. Writes `<out>/reports/`, `<out>/evidence/`, `<out>/figures/`.   |
| `--axes A` / `--axes A,B`   | `A,B`                  | Run capability-coverage only, or coverage + surface metrics.              |
| `--include-auth`            | _off_                  | Include rubric entries flagged `authenticated:` / `transactional:`.       |
| `--force`                   | _off_                  | Recompute every target instead of using the per-shop cache.               |
| `--capture-judge-model <id>`| `claude-haiku-4-5`     | Anthropic model id for the capture-judge tier.                            |

Behavior:

1. Load `benchmark.yaml` and the pinned `v2` rubric.
2. For each target (sandboxes first, then reals) check the per-shop
   cache. On a hit, reuse it; on a miss, run probes + capture-judge
   bundle + (optionally) the surface crawl, then write
   `<out>/reports/<label>__<name>.json`.
3. After every target has a report, render the two cohort tables
   under `<out>/figures/`:
   - `group_comparison.md` — three rows (sandbox, real, delta).
   - `per_shop_table.md` — one row per shop with per-axis coverage.

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

Each entry has:

| Field            | Type                                                              | Notes                                                              |
| ---------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| `id`             | string                                                            | Stable dot-separated identifier; unique within a rubric.           |
| `category`       | enum                                                              | `site_shell`, `homepage`, `collection`, `product`, `search`, …     |
| `level`          | `core` \| `modern` \| `advanced` \| `capture_judge`               | Tier; rolls up into `coverage_core` / `_modern` / `_advanced`.     |
| `weight`         | int 1–3                                                           | Per-category weight in the coverage formula `Σ wᵢ·passedᵢ / Σ wᵢ`. |
| `probe`          | dotted ref \| null                                                | Required for deterministic levels; must be `null` for capture-judge.|
| `capture_judge`  | inline block \| null                                              | Required for `level: capture_judge`; must be `null` otherwise.     |
| `description`    | string                                                            | Human-readable rationale.                                          |
| `authenticated`  | bool                                                              | Gated behind `--include-auth`.                                     |
| `transactional`  | bool                                                              | Gated behind `--include-auth`.                                     |

A `capture_judge` block has:

```yaml
capture_judge:
  judge_prompt: "Is the cart drawer affordance reachable from the header on every page?"
  pages: [home, collection, product]
```

The dispatcher slices the per-shop bundle by `pages` (in order) before
calling the Anthropic Messages API.

The shipped rubric lives at
`packages/shop_arena/src/shop_probe/rubric/v2.yaml`.

---

## 7. Output schema

One file per target: `<out>/reports/<label>__<name>.json`. The closed
Pydantic schema is `shop_probe.report.ProbeReport`:

```text
ProbeReport
├── target            : Target (name, base_url, label)
├── rubric_version    : str   (e.g. "v2")
├── rubric_hash       : str   (sha256 hex of v2.yaml — cache key)
├── runner_version    : str
├── runtime           : BrowserMeta (python, playwright, chromium, viewport, …)
├── timestamp         : datetime (UTC, run start)
├── probe_results     : tuple[ProbeResult, …]
├── categories        : tuple[CategoryScore, …]   (per-category coverage)
├── coverage_core     : float ∈ [0, 1]
├── coverage_modern   : float ∈ [0, 1]
├── coverage_advanced : float ∈ [0, 1]            (includes capture-judge)
├── coverage_weighted : float ∈ [0, 1]
├── surface           : SurfaceMetrics | null     (axis B; null when --axes=A)
└── total_judge_cost_usd : float | null           (sum of capture-judge costs)
```

Each `ProbeResult` carries `id`, `passed`, `evidence` (paths under
`<out>/evidence/<label>__<name>/`), `notes`, `duration_ms`, and — for
capture-judge entries — `judge_cost_usd` and `judge_model`.

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
  `Coverage core`, `Coverage modern`, and an `In real envelope` count
  (sandbox shops only) showing how many surface metrics fall inside
  the real-group min/max envelope.

---

## 8. Appendix

### 8.1 Layout

```
packages/shop_arena/src/shop_probe/
├── cli.py                  # single `eval` entrypoint
├── report.py               # ProbeReport + inner schemas
├── fidelity.py             # GroupSummary, BenchComparison, compute_bench_comparison
├── targets.py              # Bench, Target schemas
├── bench.py                # benchmark.yaml loader
├── capture/                # 5-page screenshot + a11y bundle (with on-disk reuse)
├── agent/                  # Anthropic client + capture-judge runner
├── probes/                 # deterministic Playwright probes (one module per category)
├── rubric/                 # schema, loader, v2.yaml
├── report_writer/          # group_comparison + per_shop tables
└── surface/                # axis-B crawler + metrics
```

### 8.2 Verification commands

```bash
cd packages/shop_arena
uv run pyright src/shop_probe                       # 0 errors expected
uv run pytest tests/shop_probe                      # green (browser tests need Playwright)

# Smoke run: produces 8 reports + 2 figures.
uv run --package shop-arena shop-probe eval \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out /tmp/sp_smoke --axes A,B

# Re-run is a full cache-hit; no Anthropic calls.
uv run --package shop-arena shop-probe eval \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out /tmp/sp_smoke --axes A,B
```
