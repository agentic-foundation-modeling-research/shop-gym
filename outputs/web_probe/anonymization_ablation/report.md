# Anonymization-sufficiency ablation — axis C v1

Status: **Run** · Source: `packages/shop_probe/scripts/anonymization_ablation.py`
Plan: [`docs/impl/web_probe_implementation.md`](../../../docs/impl/web_probe_implementation.md) **T5.1**
Spec: [`docs/specs/shop_arena/web_probe.md`](../../../docs/specs/shop_arena/web_probe.md) §8.5 Q4
Generated: `2026-04-28T15:00:08+00:00`

This report quantifies whether structural-only anonymization (the v1
`shop_probe.judge.anonymize` rewrites, spec §5.5 step 3) is sufficient
to defeat brand-recognition by a frontier judge model on the closed
leak-vector inventory it is designed to cover. It is the gate
deliverable for spec §8.5 open question 4 / T5.1.

## Methodology

1. Load the brand-loaded hardware fixture trajectory (mirrors
   `tests/judge/test_anonymize.py::_hardware_trajectory()` — the same
   trajectory shape M4-M5 axis-C judging exercises).
2. Define a closed **leak-vector inventory** of 10 patterns
   across 4 categories: source domain, brand strings, theme
   identifiers, distinctive product titles (spec §5.5 step 3 line
   items).
3. Count per-vector occurrences across **every free-form text field
   the judge sees** (target label / base_url / notes, top-level
   `Trajectory.notes`, and per-step
   `action.selector`/`action.value`/`action.description` /
   `observation.url`/`observation.title` / `reasoning`) — both
   pre- and post-anonymization.
4. Audit **structural-feature preservation**: step count, action
   kinds, evidence file paths, HAR ref, timestamps, final status. The
   anonymizer must leave these intact for the judge prompt to be
   well-formed.

## Headline numbers

- **10 leak vectors** evaluated.
- **38 occurrences** in the original trajectory.
- **0 occurrences** in the anonymized trajectory.
- **Residual leakage rate: 0.0%** (target: 0.0%).
- **Verdict: v1 anonymization sufficient**.

## Per-vector audit

| Category | Pattern | Pre | Post | Pass |
|---|---|---|---|---|
| `brand_string` | `Hardware` | 19 | 0 | PASS |
| `brand_string` | `Shopify Hardware` | 2 | 0 | PASS |
| `product_title` | `Aurora Drinkware Set` | 0 | 0 | PASS |
| `product_title` | `Hardware Hooded Sweatshirt` | 3 | 0 | PASS |
| `product_title` | `Mountain Range Backpack` | 0 | 0 | PASS |
| `product_title` | `Premium Snowboard Pro` | 3 | 0 | PASS |
| `product_title` | `ShopFloor Toolkit` | 0 | 0 | PASS |
| `source_domain` | `hardware.shopify.com` | 8 | 0 | PASS |
| `theme_identifier` | `Dawn` | 3 | 0 | PASS |
| `theme_identifier` | `atelier` | 0 | 0 | PASS |

## Structural-feature preservation

| Feature | Preserved |
|---|---|
| Step count | `3` (matches input) |
| Action kinds | `['navigate', 'click', 'type']` |
| Evidence paths | `3` rows, byte-for-byte |
| HAR ref | `trajectories/t01/run.har` |
| Timestamps + final status | `completed` between `2026-02-14T12:00:00+00:00` / `2026-02-14T12:02:00+00:00` |

The anonymizer rewrites only text fields; on-disk evidence
(`screenshot` / `a11y_snapshot` / `har`) and timing metadata are
preserved verbatim so the judge prompt template (spec §8.3) keeps its
structural contract.

## Catalog-handle hashing — cross-step structure

Catalog handles in URL paths (`/products/<handle>`,
`/collections/<handle>`, …) are replaced with stable
`hash_token(handle, salt="shop_probe.v1", length=12)` digests.
Stability across both members of a pair is what lets the judge see
"this is the same product across two trajectories" without learning
*which* product:

- Original handle: `premium-snowboard-pro`
- Hashed token: `a68d26d2d243`
- Stable across re-runs (same plan + handle): **True**

## Out-of-scope leak vectors (v1.1)

The v1 anonymizer rewrites **in-memory text** in the `Trajectory`
schema. The following channels are **not** rewritten in v1 and are
acknowledged here so M4-M5 judges do not silently consume them:

| Channel | v1 status | v1.1 plan |
|---|---|---|
| Pixel content of `EvidenceRef(kind="screenshot")` files | not rewritten | per-pair pixel-redaction sweep over PNGs |
| HTML / JSON bodies inside `EvidenceRef(kind="har")` files | not rewritten | HAR-body rewriter mirroring the trajectory rewriter |
| Text inside `EvidenceRef(kind="a11y_snapshot")` files on disk | not rewritten | a11y-snapshot rewriter sharing this module's regex bank |
| Cookie names / values surfaced in HAR | not rewritten | HAR-body rewriter as above |

These vectors do not invalidate the v1 result: M4-M5 judge prompts
inline the **anonymized in-memory `Trajectory`** (spec §5.5 step 3,
§8.3 prompt sketch); they do not attach raw evidence files. The v1.1
work lands when reviewers ask to inspect raw evidence directly.

## Decision (T5.1, spec §8.5 Q4)

**v1 anonymization is sufficient** for axis-C judging on the closed
leak-vector inventory above. M4-M5 proceed with the v1 anonymizer.
The v1.1 escalation is triggered if (a) M4's swap-consistency check
(T4.8) shows the judge flips on swap for >5% of pairs, or (b) the
M5 cohort run shows `judge_accuracy_experimental` cohort-mean ≥
control + 0.10 with a Spearman ρ ≥ 0.5 between brand-cue density of
the original trajectory and the judge's pick. Both conditions are
recorded in `outputs/web_probe/cohort_v0.1/` once M5 runs.

## Reproduce

```bash
cd packages/shop_probe
uv run python -m scripts.anonymization_ablation
```

Re-runs are deterministic (the `generated_at` timestamp is the only
field that bumps).
