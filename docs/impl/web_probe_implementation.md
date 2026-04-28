# ShopProbe / `web_probe` — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/shop_arena/web_probe.md`](../specs/shop_arena/web_probe.md)
Target module: `packages/shop_arena/src/shop_probe`

> Pure task list. Each task references the spec section that defines its
> behavior. Order matches the spec milestones (§7). Gates per milestone are
> verbatim from the spec.

---

## 1. Overview

Seven milestones from spec §7. M1–M3 land axes A+B and the per-pair fidelity
table. M4–M5 land the blinded judge and full-cohort run. M6 produces every
paper figure from versioned reports. M7 is the v1.1 stretch (second judge,
Likert quality, human calibration, prior-work envs).

## 2. Terminology

Uses the spec's vocabulary verbatim (§2). No new terms.

## 3. Current Status

`packages/shop_arena/src/shop_probe` does not exist. ShopGym today has `shop_explore`
manuals + a 108-task ShopGuru benchmark (behavioral fidelity); no
structural-fidelity instrument (spec §3).

## 4. Desired Status

After M6: `shop-probe run <url>` and `shop-probe report --cohort cohort.yaml`
emit a closed `ProbeReport` per target plus all paper figures from the
versioned reports without manual editing (spec §4, §7 M6).

---

## 5. Proposal — Task list

### M1 · Package skeleton + axis A core (spec §7 M1)

- [x] **T1.1** — Add `packages/shop_arena/src/shop_probe/` as a sibling module of `shop_gen`/`shop_explore`; `packages/shop_arena/pyproject.toml` pins Python ≥ 3.11, `playwright`, `pydantic>=2`, `pyyaml`, `httpx`; declares `shop-probe` console script. Layout per spec §5.1. **Check:** `uv sync` resolves; `pyright --strict packages/shop_arena/src` clean on the empty module.
- [x] **T1.2** — `targets.py`: `Target`, `Cohort` pydantic v2 models per spec §5.2 (`label`, `base_url`, `kind ∈ {sandbox, source, real_unpaired}`, `pair_id`, `notes`); `extra="forbid"`. **Check:** unit tests cover round-trip, unknown-field rejection, `pair_id` only set on `sandbox`/`source`.
- [x] **T1.3** — `rubric/schema.py`: `RubricEntry` pydantic model per spec §5.3 (`id`, `category`, `level ∈ {core, modern, advanced}`, `weight ∈ 1..3`, `probe`, `description`, `authenticated`, `transactional`). `rubric/loader.py`: load + validate + content-hash YAML. **Check:** unit test loads a fixture YAML, asserts deterministic hash, rejects unknown fields and out-of-range weights.
- [x] **T1.4** — `rubric/v1.yaml`: 20 `core`-level probes covering `site_shell`, `collection`, `product`, `cart` subsets per spec §7 M1. Frozen + hashed. **Check:** rubric loader validates; hash committed in test fixture.
- [x] **T1.5** — `report.py`: closed pydantic schemas `ProbeResult`, `CategoryScore`, `JudgeCall`, `ProbeReport` per spec §5.6; `extra="forbid"` everywhere. **Check:** unit tests cover JSON round-trip and unknown-field rejection.
- [x] **T1.6** — `probes/_runner.py`: Playwright orchestration per spec §5.3 — isolated context, fixed viewport 1280×800, pinned UA, headless, 10 s default timeout, `retries=0`, structured `ProbeOutcome` (passed, evidence refs, notes, duration_ms). **Check:** unit test against a localhost HTML fixture exercises the timeout + evidence-capture paths.
- [x] **T1.7** — Implement the 20 M1 core probes across `probes/site_shell.py`, `probes/collection.py`, `probes/product.py`, `probes/cart.py` per spec §5.3 + §8.1 example. Each probe emits screenshot + DOM snapshot evidence. **Check:** each probe runs deterministically against a localhost SandboxShop fixture; `passed`/`notes` match expected.
- [x] **T1.8** — `cli.py`: `shop-probe run <base_url> --label … --rubric v1 --axes A --out report.json` per spec §4. Computes `coverage_core/modern/advanced/weighted` per §5.3, `categories[]` per §5.6. Embeds rubric version + hash + runner version + browser meta per spec §5.8. **Check:** `shop-probe run --axes A` against a localhost SandboxShop produces a valid `ProbeReport` (spec §7 M1 gate).

**M1 acceptance:** spec §7 M1 gate — unit tests green; `shop-probe run --axes A` against a localhost SandboxShop produces a valid `ProbeReport`.

### M2 · Axis B + cohort wiring (spec §7 M2)

- [x] **T2.1** — `surface/metrics.py`: `SurfaceMetrics` pydantic model per spec §5.4 (11 fields). `extra="forbid"`. **Check:** schema unit tests.
- [x] **T2.2** — `surface/crawler.py`: depth-2 crawl from `/`, full enumeration of `/collections/*`, sampled `/products/*` up to N=20 per spec §5.4. Computes structural template fingerprint, interactables (median + p95), forms/fields, catalog counts, `filter × sort` state-space, gzipped DOM size, a11y-node counts. **Check:** unit tests against localhost fixture validate each metric independently.
- [x] **T2.3** — Wire axis B into `cli.py`: `--axes A,B` populates `report.surface`. **Check:** combined report validates; `surface.distinct_templates ≥ 3` on the localhost SandboxShop.
- [x] **T2.4** — `cohort.yaml` per spec §8.2: 3 sandbox/source pairs (hardware, hexclad, aloyoga) + 3 `real_unpaired` slots (TBD per spec §8.5 open question 1). Loadable via `targets.Cohort`. **Check:** loader validates; each `pair_id` ties exactly one `sandbox` and one `source`.

**M2 acceptance:** spec §7 M2 gate — surface metrics emitted for all 3 sandbox targets; values manually sanity-checked.

### M3 · Pilot pair + per-pair fidelity (spec §7 M3)

- [x] **T3.1** — `fidelity.py`: `PairFidelity`, `CohortFidelity` pydantic models per spec §5.7. Compute `coverage_gap` (per-category + weighted), `surface_ratio` (per-metric + geomean), `sandbox_in_real_envelope` per metric. Judge fields default to `None` until M4. **Check:** unit tests on synthetic A+B reports.
- [x] **T3.2** — Pilot run: full axis A + B against `pair_1` (`source/1` + `sandbox/1`). Commit reports under `outputs/web_probe/pair_1/`. **Check:** spec §7 M3 gate — one full pair report committed; rubric gaps logged as v1.1 candidates.
- [x] **T3.3** — Bump `rubric/v1.yaml` toward 60 probes by adding remaining `core` + `modern` probes across `homepage`, `search`, `i18n`, `floating`, `dynamics`, `a11y`, `media` per spec §5.3 category targets (drop `level: advanced` per §5.3). **Check:** rubric hash bumped; pilot report regenerated; flake spot-check.

**M3 acceptance:** spec §7 M3 gate — pair-1 report committed; gaps logged.

### M4 · Axis C v1 — blinded pairwise judge (spec §7 M4)

- [x] **T4.1** — `judge/trajectory.py`: closed `Trajectory` pydantic schema per spec §5.5 — ordered `(action, observation, reasoning)` tuples, screenshots, accessibility-tree snapshots. `extra="forbid"`. **Check:** schema round-trip tests.
- [x] **T4.2** — `judge/agent.py`: wrap `packages/harness` plan/exec loop with a Playwright runtime against the target URL; persist `Trajectory` per spec §5.5 step 2. **Check:** runs end-to-end against localhost SandboxShop; saved trajectory validates.
- [x] **T4.3** — `judge/tasks/v1.yaml`: ~10 judge-diagnostic tasks per spec §5.5 step 1 (visually rich, multi-page, interaction-heavy). Independent from the 108-task ShopGuru benchmark per spec §5.5.1. **Check:** loader validates; tasks reviewed for diagnosticity.
- [x] **T4.4** — Trajectory anonymization per spec §5.5 step 3: strip URL, brand strings, theme identifiers, OG metadata, favicon, distinctive product names; replace catalog identifiers with stable hashes. **Check:** unit test asserts no source-domain / brand / first-N-product-title leakage post-anonymization.
- [x] **T4.5** — `judge/pairwise.py`: pair construction per spec §5.5 step 4 — experimental `(sandbox_i, source_i)` and control `(real_a, real_b)` (sampled without replacement from 6 real shops). **Check:** unit test asserts experimental + control populations are disjoint where required and that the 6-real-shop pool is honored.
- [x] **T4.6** — Pinned single-judge wiring per spec §5.5 step 5 + §5.5 guardrails: one OpenAI flagship model (e.g. `gpt-5`); temperature 0; pin model + version in `BrowserMeta`/report metadata; save full prompt + full response per call; force evidence citation; discard calls without evidence. **Check:** golden-prompt unit test using a stub LLM; pin assertions in report header.
- [x] **T4.7** — `judge/prompts/v1/system.md` + `judge/prompts/v1/pairwise.md` per spec §8.3. Identical prompt for experimental and control pairs; judge unaware of condition (spec §5.5 step 5). **Check:** lint-only; prompt content hash embedded in `JudgeCall.prompt_hash`.
- [x] **T4.8** — Position-bias check per spec §5.5 step 6: re-run with A/B swapped; drop pairs where the judge flips on swap; report drop rate. **Check:** swap-consistency unit test on a stub-judge fixture.
- [x] **T4.9** — Run pairwise judge on `pair_1` per spec §7 M4 gate. **Check:** spec §7 M4 gate — swap-inconsistency rate ≤ 5%; HAR captures + screenshots saved; control-pair construction validated against the 6-real-shop list.

**M4 acceptance:** spec §7 M4 gate.

### M5 · Full cohort run (spec §7 M5)

- [x] **T5.1** — Resolve spec §8.5 open questions before the cohort run: (a) the 3 unpaired real shops (selection per §8.5 Q1); (b) bot-detection mitigation for the two non-Shopify-operated paired sources (§8.5 Q2); (c) sandbox URLs for `pair_2` and `pair_3` (§8.5 Q3); (d) anonymization-sufficiency ablation for axis C (§8.5 Q4). **Check:** decisions documented in `cohort.yaml` + a v0.1 README; ablation report committed.
- [x] **T5.2** — N=3 reruns of axes A and B over all 9 targets per spec §5.8. Compute `flake_rate_per_probe` per `ProbeReport` field. Save HAR captures + all screenshots + a11y snapshots per spec §5.8. **Check:** every report has `flake_rate < 1%`; HAR + evidence trail present.
- [x] **T5.3** — Full pairwise judge across experimental + control pairs (spec §7 M5 gate). **Check:** `judge_accuracy_experimental` per pair + `judge_accuracy_control` cohort-level reported.

**M5 acceptance:** spec §7 M5 gate — all targets in `cohort.yaml` produce reports with `flake_rate < 1%`; control accuracy reported as the noise floor for axis C.

### M6 · Aggregation + paper figures (spec §7 M6)

- [x] **T6.1** — `report_writer/tables.py`: per-pair fidelity table per spec §8.4 row 1 — one row per pair, three numbers per row + cohort-level intra-real control row. **Check:** rendered from versioned reports without manual editing.
- [x] **T6.2** — `report_writer/figures.py`: radar chart per spec §8.4 row 2 — per-category coverage with the 6-real-shop envelope shaded; sandboxes overlaid as polygons. **Check:** SVG/PNG output reproducible from `cohort/` reports.
- [x] **T6.3** — Surface bar chart per spec §8.4 row 3 — per-metric sandbox value, source value, and `[min, max]` range over the 6 real shops as a range bar. **Check:** rendered from versioned reports.
- [x] **T6.4** — Turing chart per spec §8.4 row 4 — experimental judge accuracy per pair AND intra-real control accuracy with bootstrap 95% CIs; plots `|experimental − control|` against ε. **Check:** rendered from versioned reports.
- [x] **T6.5** — `cli.py`: `shop-probe report --cohort cohort.yaml --out figures/` per spec §4 wires T6.1–T6.4. **Check:** spec §7 M6 gate — figures 1–4 of the paper rendered from `cohort/` reports without manual editing.

**M6 acceptance:** spec §7 M6 gate.

### M7 · v1.1 stretch (spec §7 M7, §5.9)

- [x] **T7.1** — Second judge family (Claude or Gemini) for cross-judge agreement per spec §5.9 + §7 M7. **Check:** cross-judge κ reported.
- [x] **T7.2** — Likert quality dimensions (visual coherence, copy realism, error plausibility) per spec §5.9. **Check:** per-dimension Likert distributions in the report.
- [x] **T7.3** — ~50-trace human-judge calibration per spec §5.9 + §7 M7. **Check:** Spearman ρ between human and LLM judge reported per dimension.
- [x] **T7.4** — `authenticated: true` + transactional probes (login, signup, account, checkout) per spec §5.9. **Check:** rubric version bumped; probes gated behind `--include-auth`.
- [x] **T7.5** — Prior-work environment baselines (Mock Shop, WebShop, WebArena-Shopping) as paper supplement per spec §5.2 + §5.9. **Check:** supplement table rendered alongside primary results without altering per-pair claims.

**M7 acceptance:** spec §7 M7 gate.

---

## 6. Milestones (summary)

| Milestone | Tasks       | Spec gate                                                                                |
| --------- | ----------- | ---------------------------------------------------------------------------------------- |
| M1        | T1.1–T1.8   | §7 M1 — `shop-probe run --axes A` against localhost SandboxShop emits valid `ProbeReport` |
| M2        | T2.1–T2.4   | §7 M2 — surface metrics emitted for all 3 sandbox targets                                |
| M3        | T3.1–T3.3   | §7 M3 — one full pair report committed; gaps logged                                       |
| M4        | T4.1–T4.9   | §7 M4 — pairwise judge on pair 1 with ≤5% swap-inconsistency rate                         |
| M5        | T5.1–T5.3   | §7 M5 — all 9 targets reported with `flake_rate < 1%`; control noise floor reported       |
| M6        | T6.1–T6.5   | §7 M6 — figures 1–4 rendered from `cohort/` reports without manual editing               |
| M7        | T7.1–T7.5   | §7 M7 — cross-judge κ + human-judge Spearman ρ reported (stretch)                         |

## 7. Appendix

### 7.1 Out-of-scope (deferred)

Per spec §5.9: auth + transactional probes, Likert quality judge, multi-judge
ensemble in v1, prior-work envs, human calibration, performance probes. All
land via M7 or paper supplement.

### 7.2 Open questions

Tracked in spec §8.5 (still open): unpaired real-shop selection, bot
detection on merchant storefronts, sandbox URLs for hexclad / aloyoga,
anonymization sufficiency for axis C. T5.1 is the gate for resolving these
before M5.
