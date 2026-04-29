# ShopProbe v1.2 / `advanced` tier — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/shop_arena/web_probe_v1_2_advanced.md`](../specs/shop_arena/web_probe_v1_2_advanced.md)
Target module: `packages/shop_arena/src/shop_probe`

> Pure task list. Each task references the spec section that defines its
> behavior.

---

## 1. Overview

Three milestones from the v1.2 spec. M1 lands the rubric file + structural
tests. M2 implements the 8 behavioral probe functions. M3 runs a smoke pass
against one sandbox + one real shop to confirm the wiring lights up.

## 2. Terminology

Uses the v1.2 spec's vocabulary verbatim (§Terminology). No new terms.

## 3. Current Status

`packages/shop_arena/src/shop_probe/rubric/` ships `v1.yaml` (61 entries) and
`v1.1.yaml` (66 entries). `level: advanced` is defined in the schema
(`RubricLevel = Literal["core", "modern", "advanced"]`) but no rubric file
emits any `advanced` entries. `cli.py:577-620` already aggregates
`by_level["advanced"]` — the bucket exists, it's just empty.

## 4. Desired Status

After M3: `--rubric v1.2` resolves a 74-entry rubric where 8 entries drive
real interactions, `coverage_advanced` returns a non-zero (or
informationally-zero, for thin shops) value, and the report's
`probe_results[]` carry behavioral evidence (before/after screenshots
showing the state change).

---

## 5. Proposal — Task list

### M1 · Rubric file + structural tests (spec §Proposal §1, §Appendix A.2)

- [ ] **T1.1** — Copy `rubric/v1.1.yaml` → `rubric/v1.2.yaml`. Bump
  `version: v1.2` in the header. Update the leading comment to describe the
  v1.2 expansion (advanced tier; 66 v1.1 + 8 advanced = 74 entries).
  **Check:** YAML still parses via existing loader.
- [ ] **T1.2** — Append the 8 advanced entries from spec §Proposal §2 to
  `rubric/v1.2.yaml`. All `level: advanced`, `authenticated: false`,
  `transactional: false`. Probe callables match the function names planned
  in M2 (`probes.collection.sort_changes_order`, etc.). Distribute weights:
  collection +7 (4 probes), product +3 (2), search +2 (1), dynamics +2 (1).
  **Check:** loader still parses; total entry count = 74.
- [ ] **T1.3** — Write `tests/shop_probe/test_rubric_v1_2.py` mirroring
  `test_rubric_v1_1.py`: pin `EXPECTED_V1_2_HASH` (compute SHA-256 over raw
  bytes after T1.2), `EXPECTED_V1_2_VERSION = "v1.2"`,
  `EXPECTED_V1_2_PROBE_COUNT = 74`, `EXPECTED_V1_2_ADVANCED_COUNT = 8`,
  `EXPECTED_V1_2_CATEGORY_COUNTS` per spec §A.2. Test cases:
  hash-pinning, loader returns expected version + hash, probe count,
  advanced-count, category distribution, every advanced entry is
  `authenticated=false` + `transactional=false`, advanced probes live
  in `probes.<category>.*`. **Check:** all tests green.

**M1 acceptance:** `uv run pytest tests/shop_probe/test_rubric_v1_2.py -v`
green; existing v1 + v1.1 tests still green.

### M2 · 8 behavioral probe functions (spec §Proposal §2, §Failure modes)

- [ ] **T2.1** — `probes/collection.py`: add `sort_changes_order`,
  `filters_apply_to_results`, `pagination_advances`,
  `filter_click_advances_url`. Each follows the skeleton in spec §A.1:
  precondition checks → return `passed=None` if not applicable → drive
  interaction → wait with 3 s ceiling → assert delta. Capture
  before/after screenshot + snapshot pairs. **Check:** strict pyright
  passes; functions resolvable as `probes.collection.<name>` by the
  rubric loader.
- [ ] **T2.2** — `probes/product.py`: add `variant_swap_updates_state`,
  `qty_spinner_increments`. Same skeleton. **Check:** pyright + import.
- [ ] **T2.3** — `probes/search.py`: add `predictive_listbox_populates`.
  Skeleton uses `page.locator(...).type("shi", delay=50)` and
  `page.wait_for_timeout(1500)` to honour debounce. **Check:** pyright +
  import.
- [ ] **T2.4** — `probes/dynamics.py`: add `cart_count_badge_updates`.
  Reuse `probes/cart.py:_add_sample_to_cart` (import in module). **Check:**
  pyright + import.
- [ ] **T2.5** — Update `probes/__init__.py` module docstring to list the
  new advanced probes under their existing module bullets (no new module).
  **Check:** docstring renders cleanly.

**M2 acceptance:** `uv run pyright packages/shop_arena/src/shop_probe/probes/`
strict-clean; rubric loader resolves all 8 callables without `AttributeError`.

### M3 · Smoke run (spec §Milestones M3)

- [ ] **T3.1** — Run `shop-probe run <real-storefront> --rubric v1.2
  --reruns 1 --out /tmp/v1_2_smoke/`. Confirm: report loads; 8 advanced
  probes appear in `probe_results[]`; `coverage_advanced` is non-zero or
  every advanced probe returned `passed=None`; evidence dirs contain
  before/after screenshots; no probe exceeds the 10 s default timeout.
- [ ] **T3.2** — Run the same command against one sandbox storefront.
  Same checks. Compare `coverage_advanced` between real and sandbox to
  validate the new axis discriminates the two populations.

**M3 acceptance:** spec §Milestones M3 — both reports validate; advanced
coverage axis produces a non-trivial signal.

### M4 *(stretch)* · Cohort re-run + result_v1_2.md (spec §Milestones M4)

- [ ] **T4.1** — Re-run the existing 7-target cohort under
  `outputs/shop_probe/result/` against v1.2 (4 reruns each). Generate
  `outputs/shop_probe/result/result_v1_2.md` mirroring the existing
  `result.md` but with the 3-tier coverage table and updated
  always-fail / always-pass lists.
- [ ] **T4.2** — Update `packages/shop_arena/src/shop_probe/README.md`
  with a mention of `--rubric v1.2` and a one-liner on what the advanced
  tier asserts.

**M4 acceptance:** stretch — `result_v1_2.md` written; README updated.

## 6. Verification

End-to-end:

1. `cd packages/shop_arena && uv run pytest tests/shop_probe/test_rubric_v1_2.py -v` — hash + structural pins green.
2. `cd packages/shop_arena && uv run pyright src/shop_probe/probes/` — strict clean.
3. Smoke run from M3: `coverage_advanced` non-zero on a real shop with sort + filter functionality.
4. Diff `outputs/.../result.md` (v1) against `result_v1_2.md` (v1.2) — the always-fail list should still contain the 8 v1 probes whose presence-fail blocks behavioral exercise; the new advanced probes should populate the report's tail.

## 7. Out of scope

- Auth/checkout probes — owned by v1.1.
- Backfilling existing v1 reports against v1.2 (rubric content-hash invariant).
- Tightening existing core/modern presence probes in place.
- Mock HTML fixtures for unit-testing the advanced probes (codebase pattern: integration-only).
