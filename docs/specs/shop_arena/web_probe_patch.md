# `web_probe` patch: drop pair semantics, adopt 3-stage population pipeline

Status: **Patch (proposed)** · Applies to: `docs/specs/shop_arena/web_probe.md` v0.1
Owners: ShopGym
Last updated: **2026-04-28**

> This patch supersedes the pair-based design in `web_probe.md`. The
> probe pipeline no longer compares one sandbox shop against one
> source shop; instead it evaluates two **populations** (N sandboxes
> vs M reals) and produces group-level fidelity numbers. A future
> stage-3 command can cherry-pick a single shop and compare it
> against others, but the per-pair join key is gone.

## Motivation

The original spec encoded pair identity in three places: the CLI
flags (`--label`, `--kind`, `--pair-id`), the `Pair` model, and the
`PairFidelity`/`PairwisePair` types. In practice:

- Pair identity is brittle to maintain across runs — sandbox and
  source filenames must agree on a join key.
- Per-pair fidelity rows are noisy at small N and hard to read.
- The judge's "pairwise + swap" protocol is over-engineered: a
  per-shop Turing-test classification produces the same
  indistinguishability signal with half the LLM calls.
- Most consumers want one group-vs-group answer, not N individual
  scores.

The patched pipeline collapses these into two flat populations
plus a clean three-stage execution model.

## Stage model

```
Stage 1: per-shop probe
  shop-probe run <url> --name x --label sandbox --out OUT/
  → OUT/reports/sandbox__x__rerun1.json (one ProbeReport)

Stage 2: group aggregation + group-vs-group comparison
  shop-probe report --bench bench.yaml --out OUT/
  → OUT/figures/group_comparison.md
  → OUT/figures/{radar,surface,turing}.svg

Stage 3 (optional, future): cherry-pick one shop, compare to others
  shop-probe compare --bench bench.yaml --shop shop_x
  → side-by-side detail report
```

Stage 3 is reserved in the CLI dispatch but not implemented in this
patch.

## Renames and deletions

| Old | New |
|---|---|
| `Cohort` (`cohort.yaml`, `cohort.py`) | `Bench` (`bench.yaml`, `bench.py`) |
| `Cohort.pairs: tuple[Pair, ...]` + `Cohort.real_unpaired` | `Bench.sandboxes: tuple[Target, ...]` + `Bench.reals: tuple[Target, ...]` |
| `Pair` model | **deleted** |
| `PairFidelity` | **deleted** — replaced by `GroupSummary` + `BenchComparison` |
| `compute_pair_fidelity` | **deleted** |
| `compute_cohort_fidelity` | `compute_bench_comparison(sandbox_reports, real_reports) -> BenchComparison` |
| `judge/pairwise.py` (`PairwisePair`, `build_experimental_pairs`, `build_control_pairs`, `real_shop_pool`) | **deleted** |
| `judge/swap.py` | **deleted** (swap consistency was a pairwise invariant) |
| `JudgeCall` (pairwise context) | `JudgeCall` (per-shop classification) |

## `bench.yaml` shape

```yaml
version: "0.1"
sandboxes:
  - { name: shop_alpha, base_url: https://..., label: sandbox }
  - { name: shop_beta,  base_url: https://..., label: sandbox }
reals:
  - { name: real_a, base_url: https://..., label: real }
  - { name: real_b, base_url: https://..., label: real }
  - { name: real_c, base_url: https://..., label: real }
```

- `name` must be unique across the entire bench (not per group).
- `label` must agree with the group the target appears in
  (`sandboxes:` → `label: sandbox`; `reals:` → `label: real`).
- No pair join key. No `real_unpaired`. Both groups are flat lists.

## CLI

### `run` (stage 1) — unchanged from current `--name`/`--label` design

```
shop-probe run <base_url>
  --name NAME            # filename-friendly identifier (no join semantics)
  --label {sandbox,real}
  --rubric v1
  --axes A
  --out OUT/
  [--rerun-index N]
  [--notes "..."]
```

Writes `OUT/reports/<label>__<name>__rerun<N>.json`.

### `report` (stage 2)

```
shop-probe report
  --bench bench.yaml
  --out OUT/
  [--baselines-dir DIR]
```

1. Loads `bench.yaml`.
2. Resolves each `Target` to a `ProbeReport` under `OUT/reports/` by
   matching `(label, name)`.
3. Calls `compute_bench_comparison(sandbox_reports, real_reports)`.
4. Writes:
   - `figures/group_comparison.md` (2 group rows + delta row)
   - `figures/per_shop_table.md` (one row per shop, used for
     stage-3 inspection)
   - `figures/radar.svg` (real envelope + sandbox overlays)
   - `figures/surface.svg` (sandbox dots + real envelope rectangles;
     the old "source triangle" layer is removed)
   - `figures/turing.svg` (two grouped bars: judge accuracy on
     sandbox group vs real group, plus indistinguishability gap)
   - `figures/supplement_table.md` (when `--baselines-dir` provided)

### `aggregate-reruns` — unchanged

Operates on rerun groups keyed by `(label, name, rubric_*,
runner_version)`. Already aligned with the patch.

### `compare` (stage 3) — reserved

Dispatch entry exists; implementation is a `NotImplementedError`
stub for now. Future shape:

```
shop-probe compare --bench bench.yaml --shop shop_alpha [--against shop_beta,real_a]
```

## Schema

### `targets.py`

```python
TargetLabel = Literal["sandbox", "real"]

class Target(BaseModel):
    name: str
    base_url: str
    label: TargetLabel
    notes: str | None = None

class Bench(BaseModel):
    version: str
    sandboxes: tuple[Target, ...]
    reals: tuple[Target, ...]
    # Validators:
    #   - all sandboxes have label == "sandbox"
    #   - all reals have label == "real"
    #   - names are unique across the union of sandboxes + reals
```

### `fidelity.py`

```python
class GroupSummary(BaseModel):
    label: TargetLabel
    n_shops: int
    coverage_weighted_mean: float
    coverage_per_axis_mean: dict[str, float]
    surface_metric_means: dict[str, float]      # distinct_templates, catalog_products, …
    surface_metric_envelope: dict[str, tuple[float, float]]
    judge_accuracy: float | None                 # share of judge calls predicting target.label
    judge_calls_total: int

class BenchComparison(BaseModel):
    sandbox: GroupSummary
    real: GroupSummary
    coverage_gap_weighted: float                 # real.mean - sandbox.mean
    coverage_gap_per_axis: dict[str, float]
    surface_ratio: dict[str, float]              # sandbox.mean / real.mean per metric
    sandbox_in_real_envelope: dict[str, dict[str, bool]]   # sandbox name → metric → in-envelope?
    judge_indistinguishability: float | None     # |real.judge_acc - sandbox.judge_acc|

def compute_bench_comparison(
    sandbox_reports: Sequence[ProbeReport],
    real_reports: Sequence[ProbeReport],
) -> BenchComparison: ...
```

`coverage_gap_weighted` is a single scalar (population delta), not a
per-pair vector. Per-shop deltas are derivable from `per_shop_table`
in stage 3.

### Judge

The judge becomes a **per-shop Turing-test classifier**: shown the
evidence for a single shop, it predicts whether that shop is
`sandbox` or `real` (or `abstain`).

```python
class JudgeCall(BaseModel):
    predicted_label: Literal["sandbox", "real", "abstain"]
    prompt_hash: str
    response: str
    latency_ms: float
    cost_usd: float
    model_id: str
    # No pair_id, no swap_index.
```

`ProbeReport.judge_calls: tuple[JudgeCall, ...]` carries the per-shop
calls.

Group accuracy is computed at stage 2:

```
judge_accuracy(group) =
    sum(1 for r in group_reports for c in r.judge_calls
        if c.predicted_label == r.target.label)
    / sum(len(r.judge_calls) for r in group_reports)
```

`judge_indistinguishability = |judge_accuracy(real) - judge_accuracy(sandbox)|`.
Closer to 0 means the judge cannot tell the two groups apart.

## Report figures

| File | Change |
|---|---|
| `report_writer/tables.py` | Delete `render_pair_fidelity_table`. Add `render_group_comparison_table(BenchComparison)` (sandbox row, real row, delta row). Add `render_per_shop_table(reports, comparison)` (one row per shop). |
| `report_writer/figures.py` (radar) | API unchanged: `render_radar_chart_svg(real_reports=..., sandbox_reports=...)`. |
| `report_writer/surface_chart.py` | Drop `source_reports` parameter and triangle layer. Real shops form the envelope rectangle; sandboxes plot as dots. |
| `report_writer/turing_chart.py` | Rewrite. New: 2 grouped bars showing per-group judge accuracy + indistinguishability gap. |
| `report_writer/supplement.py` | One row per shop, keyed by `target.name` for display. Already in the right shape after the `--name`/`--label` pre-patch. |

## File migration

1. `targets.py` — replace `Cohort` with `Bench`; delete `Pair`.
2. `cohort.yaml` → `bench.yaml`; `cohort.py` → `bench.py`;
   `load_cohort` → `load_bench`.
3. `fidelity.py` — full rewrite around `GroupSummary` +
   `BenchComparison`.
4. Delete `judge/pairwise.py`, `judge/swap.py`. Simplify
   `judge/run.py` to a per-shop classification loop.
5. `cli.py` — update `_load_*_reports` to return
   `(sandbox_reports, real_reports)`; rename
   `_build_cohort_fidelity` → `_build_bench_comparison`; add
   `--bench` flag; remove all pair-construction calls; reserve
   `compare` subcommand.
6. Report writers per the table above.
7. Tests:
   - Rewrite: `test_targets.py`, `test_bench.py` (was
     `test_cohort.py`), `test_fidelity.py`, `test_cli_report.py`.
   - Delete: `judge/test_pairwise.py`, `judge/test_swap.py`.
   - Simplify: `judge/test_run.py`, `judge/test_anonymize.py`
     (drop pair fixtures).
   - Touch up: `report_writer/test_tables.py`,
     `test_surface_chart.py`, `test_turing_chart.py`,
     `test_figures.py`.
   - Already aligned: `test_cli_run.py`,
     `test_cli_aggregate_reruns.py`, `test_stability.py`.

## Backward compatibility

**Clean break.** Existing `cohort.yaml` files do not load. There is
no shim. Callers must migrate to `bench.yaml`. Justification: no
live consumers; pair semantics carry too much weight to deprecate
incrementally.

## Decisions

1. **Top-level name**: `Bench` / `bench.yaml`. Short, neutral, lines
   up with `--rubric`/`--axes`/`--out` lingo.
2. **Name uniqueness**: enforced across the union of `sandboxes` and
   `reals` (not just per group).
3. **`judge/swap.py`**: deleted in this patch, not deprecated.
4. **Stage-3 `compare`**: reserved with a `NotImplementedError`
   stub so the CLI surface is forward-compatible.
5. **No pairwise judge**: judge runs per individual shop; group
   indistinguishability is derived at stage 2.

## Open questions

- **Judge sample budget per shop**: default `--judge-samples-per-shop`
  value? Tentatively 5; tune after first end-to-end run.
- **`per_shop_table.md` columns**: minimum viable set for stage 3 is
  `(label, name, coverage_weighted, coverage_A, coverage_B,
  in_real_envelope, judge_accuracy)`. Add as needed.
- **`compare` UX**: stage-3 syntax (`--against` list, default
  behavior) is left for the stage-3 patch.
