# ShopGen — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/shop_arena/shop_gen.md`](../specs/shop_arena/shop_gen.md)
Target package: `packages/shop_arena/src/shop_gen`
Depends on: [`docs/impl/verifiers_implementation.md`](verifiers_implementation.md) (M0)

> Pure task checklist. Behavior comes from the spec; this doc only
> says what to do and in what order.

---

## Tasks

### M0 · Harness verifier extension (external)

- [ ] **T0.1** — Land [`verifiers_implementation.md`](verifiers_implementation.md) M1–M3. **Check:** `harness-v0.3.0` tag; `from harness import Verifier, VerifierContext, VerifierResult` works. **Required before M5.**

### M1 · Step DAG runner + CLI

- [x] **T1.1** — `src/shop_gen/config.py`: pydantic `ShopGenConfig` (seeds, out_dir, name, runtime, model, catalog, max_iters, image_backend), `CatalogConfig`, `ShopGenResult`. Spec §4.1. **Check:** invalid configs (zero seeds, non-positive `max_iters`, unknown `image_backend`) raise `ValidationError`.
- [x] **T1.2** — `src/shop_gen/steps/base.py`: `Step` Protocol (`id`, `phase`, `inputs`, `outputs`, `depends_on`, `version`, `run(ctx)`), `StepContext`, `StepStatus` enum, `InputRef` union (file path | step id). Spec §5.7.1. **Check:** type-check clean; example concrete step compiles.
- [x] **T1.3** — `src/shop_gen/steps/state.py`: `state.json` reader/writer; per-step fingerprint = sha256 over (input file hashes ⊕ upstream fingerprints ⊕ step `version`). Atomic writes (tmp + rename). Spec §5.7. **Check:** unit test for fingerprint stability + atomic-write under simulated crash.
- [x] **T1.4** — `src/shop_gen/steps/runner.py`: register steps, resolve DAG (cycle detection), compute staleness (output missing OR input changed OR upstream stale), topologically run stale steps. Spec §5.7. **Check:** unit tests for stale cascade, missing-output detection, cycle rejection, idempotent re-run (no-op when up-to-date).
- [x] **T1.5** — `src/shop_gen/cli.py`: argparse with positional `seeds...`, `--out-dir`, `--name`, `--from <step>`, `--only <step>`, `--status`, `--list-steps`, plus scale/runtime knobs. Dispatches to `pipeline.run` / `pipeline.status` / `pipeline.list_steps`. Spec §5.8. **Check:** `shop-gen --list-steps` prints the registered (initially empty) phase tables; `--status` on an empty out-dir prints "no run yet"; argument-parser unit tests cover all flags.
- [x] **T1.6** — `src/shop_gen/pipeline.py`: `run(config)`, `status(out_dir)`, `list_steps()`. Phase-aware step registration (multi-seed conditionally adds Phase 1). Spec §5.7.2. **Check:** unit test asserts the DAG shape for both single-seed and multi-seed configs.
- [x] **T1.7** — `src/shop_gen/_version.py` = `"0.0.0"`; `src/shop_gen/__init__.py` re-exports `ShopGenConfig`, `ShopGenResult`, `run`. **Check:** `from shop_gen import run, ShopGenConfig, ShopGenResult` works.

**M1 acceptance:** runner + CLI work against zero registered steps (empty DAG resolves to no-op); `pyright --strict` and `ruff` clean; SC7 satisfied modulo registered steps.

### M2 · Phase 1 — Manual Merge

- [x] **T2.1** — `src/shop_gen/manual_merge/capabilities.py`: per-area merge rules from spec §9.2 (booleans union, lists union+dedup, enums majority + descriptor-tiebreak via LLM). Validates against the closed `Capabilities` schema imported from `shop_explore`. Returns `(Capabilities, list[Conflict])`. Step id `merge_capabilities`. **Check:** unit tests for each rule type + tie-breaking path with stub LLM.
- [x] **T2.2** — `src/shop_gen/manual_merge/prose.py`: section-by-section LLM merge of the seed `manual.md`s, conditioned on the merged capabilities. Step id `merge_manual_prose`. **Check:** unit test with fixture seeds + stub LLM asserts section count + that the prose mentions only allowlist brands.
- [x] **T2.3** — `src/shop_gen/manual_merge/stats.py`: deterministic recompute from merged caps + seed prefetch summaries (no LLM). Step id `compute_merge_stats`. **Check:** unit test against fixture seeds.
- [x] **T2.4** — `src/shop_gen/manual_merge/manifest.py`: write `manual/manifest.json` with seed list, per-area merge conflicts, write history. Step id `write_merge_manifest`. **Check:** schema validation.
- [x] **T2.5** — `src/shop_gen/manual_merge/prompts/`: `merge_capabilities_tiebreak.md`, `merge_manual_prose.md`. **Check:** lint-only.
- [x] **T2.6** — Single-seed shortcut: when `len(seeds) == 1`, register a single `copy_seed_manual` step that copies the seed verbatim into `manual/`. Spec §5.2. **Check:** unit test asserts no LLM calls and identical bytes.
- [x] **T2.7** — Tests: end-to-end Phase 1 against 2-seed and 3-seed fixtures; assert `manual/` populated and capabilities pass schema.

**M2 acceptance:** SC5 partially satisfied (manual merge layer); LLM calls go through stub in CI.

### M3 · Phase 2 — Data Synthesis

- [x] **T3.1** — `src/shop_gen/brands/allowlist.py`: load `fake_brands.json`; expose `is_allowed(token: str) -> bool` and `scan(text: str) -> list[Hit]`. Tokenizer = regex over capitalized multi-character runs + TitleCase tokens, excluding sentence-initial words and the safe-noun list. Spec §5.6. **Check:** unit tests for clean text, single hit, multi-hit, sentence-initial false-positive avoidance, TitleCase composite handling.
- [x] **T3.2** — `src/shop_gen/data_synth/schema.py`: pydantic mirrors of `shop_backend` §8.1 (`Store`, `Product`, `ProductVariant`, `ProductOption`, `ProductImage`, `Collection`, `Page`, `Policy`, `Navigation`, `NavigationItem`). Closed schemas. **Check:** round-trip a `shop_backend` fixture dataset through the models without loss.
- [x] **T3.3** — `src/shop_gen/data_synth/identity.py`: `synth_identity` step. One LLM call producing `{descriptor, tone, currency, country}`; orchestrator picks `name` deterministically from the 8-token allowlist via `sha256(seeds + descriptor) mod 8`. Writes `<out_dir>/identity.json`. **Check:** unit test asserts deterministic name selection across re-runs with same inputs.
- [ ] **T3.4** — `src/shop_gen/data_synth/store.py`, `pages.py`, `policies.py`: `synth_store`, `synth_pages`, `synth_policies` steps. Each is one LLM call producing the corresponding schema-shaped JSON. Cached under `.shop_gen/stage_cache/`. **Check:** unit tests with fixture LLM; pydantic-validated outputs.
- [ ] **T3.5** — `src/shop_gen/data_synth/collections.py`: `synth_collections` step. One LLM call producing N collection records (default 10) with plain-descriptive titles and target product counts. **Check:** unit test asserts count, descriptive-title rule (no allowlist tokens in titles), schema validity.
- [ ] **T3.6** — `src/shop_gen/data_synth/skeletons.py`: `synth_product_skeletons` step. At v0.1 scale (200 products), one bulk LLM call returning all titles + handles + price hints + collection assignments. Per-collection dedup; cross-collection conflicts resolved at assembly time (§5.3). **Check:** unit tests for dedup, schema, and the 5-word naming rule via prompt-asserting test.
- [ ] **T3.7** — `src/shop_gen/data_synth/details.py`: `synth_product_details` step. One LLM call per collection (parallelized; ≤ 5 concurrent). Returns variants, options, description_html, vendor (from allowlist), tags. Pydantic-validated; one re-prompt on rejection; >5% rejection rate fails the step. Spec §5.3. **Check:** unit tests for happy path, retry path, oversize-rejection failure path.
- [ ] **T3.8** — `src/shop_gen/data_synth/navigation.py`: `synth_navigation` step. One LLM call producing `main-menu` + `footer` derived from collections + pages. **Check:** unit test asserts every collection handle is reachable from `main-menu`.
- [ ] **T3.9** — `src/shop_gen/data_synth/alt_text.py`: `synth_alt_text` step. One LLM call per collection (parallel). Returns `images_per_product` alt-text strings per product. **Check:** unit test asserts coverage and length bounds.
- [ ] **T3.10** — `src/shop_gen/data_synth/images.py`: `ImageBackend` Protocol + `PlaceholderBackend` (deterministic SVG: category icon + product title text). `gen_images` step writes `data/images/<handle>-<n>.svg`. The `ai` backend is stubbed to raise `NotImplementedError` (lands in M8). **Check:** unit tests for placeholder generation; deterministic output bytes for the same inputs.
- [ ] **T3.11** — `src/shop_gen/data_synth/assemble.py`: `assemble_data` step. Combines all stage outputs; assigns deterministic numeric ids (sha256-prefix of handle); runs the allowlist scanner over every string field in `data/*.json`; on any hit, marks the upstream synthesis step stale and raises `BrandLeakError`. Writes the final `data/*.json`. Spec §5.3 + §5.6. **Check:** unit tests for happy path + brand-leak failure path; integration test against a fully populated stage cache.
- [ ] **T3.12** — `src/shop_gen/data_synth/prompts/`: one prompt per step (identity, store, collections, skeletons, details, alt_text, pages, policies, navigation). Each embeds the allowlist + safe-noun rules. **Check:** lint-only; allowlist-membership grep over each prompt.
- [ ] **T3.13** — End-to-end Phase 2 test: stub LLM produces fixture stage outputs, `assemble_data` emits a complete `data/`. **Check:** SC1 satisfied; pydantic models accept the output.

**M3 acceptance:** SC1 + SC4 satisfied; brand-leak verifier proven against synthetic adversarial fixture.

### M4 · Phase 3 — Data Validation

- [ ] **T4.1** — `src/shop_gen/data_validation/schema_check.py`: `validate_schema` step. Re-validate `data/*.json` with the pydantic models from T3.2. Spec §5.4. **Check:** unit test on valid + corrupted fixtures.
- [ ] **T4.2** — `src/shop_gen/data_validation/hosting_check.py`: `validate_hosting` step. Spawn `shop-backend <data> <port>` (free port), run the spec §5.4 query suite (shop, products, collections, collection-by-handle, product-by-handle, cart lifecycle, search, image GET). Tear down the process on completion or failure. Writes `data_validation.json`. **Check:** integration test against a known-good fixture dataset; failure test against a dataset with empty `collections.json`.
- [ ] **T4.3** — Tests against a real `shop_backend` build under `pnpm --filter @shop-gym/shop-backend build` (CI step). **Check:** SC2 satisfied.

**M4 acceptance:** SC2 satisfied; hosting check is green on the M3 fixture.

### M5 · Phase 4 — Build Harness Loop

Depends on M0 (harness verifier extension).

- [ ] **T5.1** — `src/shop_gen/build/env.py`: `clone_template` step (cp -R from `templates/hydrogen/`); `write_env_file` step (`.env` with `PUBLIC_STORE_DOMAIN=localhost:<port>` and the resolved sidecar URL). Spec §5.5.1. **Check:** unit test asserts copied tree byte-equivalent to template (modulo `.env`); `.env` contains expected keys.
- [ ] **T5.2** — `src/shop_gen/build/sidecar.py`: `start_sidecar` step + lifecycle helper. Picks a free port, spawns `shop-backend`, polls `/health` until ready, returns a context manager that kills the process on exit (incl. signal handlers). One sidecar per loop. Spec §7-resolved. **Check:** unit test asserts cleanup on normal exit, on test-induced crash, and on SIGTERM.
- [ ] **T5.3** — `src/shop_gen/build/prompts/`: `agents.md`, `planner.md`, `execute.md` (with `{{verifier_feedback}}` slot), `consolidate_execute.md` (purpose-built for the consolidate task). Spec §5.5.2 + §5.5.4. **Check:** lint-only; presence of `{{verifier_feedback}}` placeholder asserted by test.
- [ ] **T5.4** — `src/shop_gen/build/verifiers/tsc.py`, `build.py`, `routes_200.py`, `data_in_use.py`, `nav_coverage.py`, `no_brand_leak.py`. Spec §5.5.3. **Check:** unit tests per verifier with synthetic hydrogen trees (passing + failing).
- [ ] **T5.5** — `src/shop_gen/build/verifiers/quality_judge.py` and `cross_task_consistency.py` (LLM-based). Use `ctx.runtime.complete` for the judge call. Spec §5.5.3 + §5.5.4. **Check:** unit tests with stub `LLMCompleter` for verdict parsing + feedback shape.
- [ ] **T5.6** — `src/shop_gen/build/loop.py`: `run_build_harness_loop` step. Wires `PlanExecLoopConfig` with the verifier set, the manual as `artifact_seed_dir`, the hydrogen tree at `<run_dir>/artifact/hydrogen/`. Invokes `harness.run_plan_exec_loop`. Spec §5.5. **Check:** integration test under `replay` runtime asserts harness gets the expected config.
- [ ] **T5.7** — Append-redo logic for `--only gen_<task>`: when the user invokes `--only` against a build-loop task that already has `[x]` in `runs/build/plan.md`, append a `<task>_redo_<N>` PENDING task and re-invoke the loop with `force_resume=True`. Spec §5.7.3. **Check:** unit test asserts (a) original `[x]` untouched, (b) `<task>_redo_1` appended, (c) follow-up `--only` increments the suffix.
- [ ] **T5.8** — `consolidate` task contract: planner prompt requires it as the lowest-priority task; if the planner omits it the orchestrator appends it deterministically before the harness runs. Spec §5.5.4. **Check:** unit test on a planner output missing `consolidate` asserts orchestrator appends it.
- [ ] **T5.9** — Replay cassette: a complete build-loop fixture covering `gen_theme`, `gen_navigation`, `gen_homepage`, `consolidate`. Hand-crafted under `tests/shop_gen/cassettes/fixture_build_loop/`. **Check:** `tests/shop_gen/test_build_loop_replay.py` runs the full Phase 4 deterministically without API keys.
- [ ] **T5.10** — End-to-end test from `data/` (M4 fixture) → working `hydrogen/`. **Check:** SC3 + SC6 satisfied under replay.

**M5 acceptance:** SC3 + SC6 satisfied; replay cassette green in CI.

### M6 · Phase 5 — Final Eval

- [ ] **T6.1** — `src/shop_gen/final_eval/playwright_smoke.py`: spawn dev server, run smoke flow (home → collection → product → add-to-cart → checkout-redirect), capture screenshots. Spec §5.5.5. **Check:** unit test against the M5 fixture artifact.
- [ ] **T6.2** — `src/shop_gen/final_eval/prompts/`: `quality_judge.md` for the post-build LLM judge. **Check:** lint-only.
- [ ] **T6.3** — `final_eval` step writes `final_eval.json` with screenshot paths + LLM verdict. **Advisory** — never blocks the run. **Check:** unit test asserts non-blocking on FAIL verdict.

**M6 acceptance:** advisory `final_eval.json` produced for every build run.

### M7 · v0.1.0

- [ ] **T7.1** — `src/shop_gen/__init__.py` re-exports public surface only (`run`, `ShopGenConfig`, `ShopGenResult`). Bump `_version.py` to `0.1.0`. **Check:** `from shop_gen import __version__` returns `"0.1.0"`.
- [ ] **T7.2** — `packages/shop_arena/src/shop_gen/README.md`: usage example, runtime selection, step DAG quick-reference, output layout, record-cassette workflow. **Check:** README snippet runs end-to-end against the M5 cassette.
- [ ] **T7.3** — Update `docs/specs/README.md` ShopArena row to point at the spec + impl. Update repo `README.md` `shop_gen` bullet to describe v0.1 status. Update `packages/shop_arena/README.md` to drop the "Scaffolded; not yet implemented" line. **Check:** links resolve.
- [ ] **T7.4** — Tag `shop-gen-v0.1.0`. Bump `packages/shop_arena/pyproject.toml` `version` if shop_arena is independently versioned. **Check:** tag pushed.

**M7 acceptance:** v0.1.0 tagged; SC1–SC7 all satisfied on fixtures.


---

## Milestones (summary)

| Milestone | Tasks       | Gate                                                                                  |
| --------- | ----------- | ------------------------------------------------------------------------------------- |
| M0        | T0.1        | `harness-v0.3.0` — verifier extension landed (separate plan)                          |
| M1        | T1.1–T1.7   | step DAG runner + CLI; SC7 modulo registered steps                                    |
| M2        | T2.1–T2.7   | Phase 1 manual merge; SC5 (manual layer)                                              |
| M3        | T3.1–T3.13  | Phase 2 data synthesis; SC1 + SC4                                                     |
| M4        | T4.1–T4.3   | Phase 3 data validation; SC2                                                          |
| M5        | T5.1–T5.10  | Phase 4 build harness loop; SC3 + SC6 (depends on M0)                                 |
| M6        | T6.1–T6.3   | Phase 5 final eval (advisory)                                                         |
| M7        | T7.1–T7.4   | docs + README + tag; SC1–SC7 on fixtures                                              |
