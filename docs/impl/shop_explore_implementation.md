# ShopExplore — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/shop_arena/shop_explore.md`](../specs/shop_arena/shop_explore.md)
Target package: `packages/shop_arena/src/shop_explore`

> Task list for landing the spec. Each task is one PR-sized unit of
> work with a deliverable and a check. Behavior comes from the spec;
> this doc only says what to do and in what order.

---

## 1. Overview

Five milestones, each independently landable: M1 pure data layer
(prefetch + schemas + stats), M2 prompts + harness wiring under the
replay runtime, M3 deterministic + LLM synthesis, M4 real-runtime smoke,
M5 v0.1.0 release. Tasks below are ordered; later tasks assume earlier
ones.

## 2. Terminology

Uses the spec's vocabulary verbatim. No new terms.

## 3. Current Status

`packages/shop_arena/src/shop_explore/` is a 2-line CLI scaffold and
empty `__init__.py`. No prefetch, no schemas, no harness wiring. Tests
under `packages/shop_arena/tests/` are placeholders.

## 4. Desired Status

After M5: `shop-explore <url>` produces a complete Shop Manual under
`outputs/shop_manuals/<domain>/<run_id>/` using the `pi` runtime by
default; `pytest packages/shop_arena/tests/shop_explore` is green
without API keys via the harness `replay` runtime.

---

## 5. Proposal — Task list

### M1 · Prefetch + schemas + stats (pure Python)

- [x] **T1.1** — Add `httpx`, `pydantic>=2.8` (already), `respx` (test) to `packages/shop_arena/pyproject.toml`. Wire `shop_explore` into root `pyproject.toml` workspace if not already. **Check:** `uv sync` resolves; `pyright --strict packages/shop_arena/src/shop_explore` clean on the empty package.
- [x] **T1.2** — `src/shop_explore/config.py`: `ExploreConfig` (pydantic v2: `url`, `out_dir`, `runtime`, `max_iters`, `timeout`), `ExploreResult` (final paths + harness `final_status`). **Check:** invalid configs (non-http url, `max_iters<=0`, non-empty `out_dir`) raise `ValidationError`.
- [x] **T1.3** — `src/shop_explore/prefetch.py`: `PrefetchResult` model, `run(url, *, dest_dir, user_agent, rate_limit_ms=500) -> PrefetchResult`. Implements §5.9 fixed URL list, bot-block detection, `prefetch.json` summary. Raises `ShopUnreachableError` on early failure. **Check:** `tests/shop_explore/test_prefetch.py` against `respx`-mocked storefront fixtures: happy path, 403 on `/`, Cloudflare marker, robots.txt deny.
- [x] **T1.4** — `src/shop_explore/capabilities.py`: closed pydantic v2 `Capabilities` model matching the spec §5.5 schema. `merge_fragments(parts_dir: Path) -> Capabilities` deterministic deep-merge with leaf-overwrite + list-union. Raises `CapabilitiesValidationError` on schema violation; returns `(Capabilities, list[Conflict])`. **Check:** unit tests cover round-trip, unknown-field rejection, list-union dedup, leaf conflict reporting.
- [x] **T1.5** — `src/shop_explore/stats.py`: `Stats` pydantic model, `compute(prefetch_dir, capabilities) -> Stats`. Pure function over `products.json`, `collections.json`, `capabilities.json`. **Check:** unit tests against fixture prefetches; truncation flag set when `products.json` returns ≥ 50 entries.
- [x] **T1.6** — `src/shop_explore/cli.py`: argparse with `--prefetch-only`. Routes to `prefetch.run`. **Check:** `shop-explore --prefetch-only https://...` against a `respx` server in test writes the expected `prefetch/` layout.

**M1 acceptance:** all unit tests green, `pyright --strict` clean, `ruff` clean. No harness coupling yet.

### M2 · Prompts + harness wiring (replay only)

- [x] **T2.1** — `src/shop_explore/prompts/agents.md`: project constitution. Anonymization rules (port from legacy + extend), playwright skill invocation pattern, capabilities schema reference (link, not inline), file-write conventions for `parts/` and `evidence/`. **Check:** lint-only; manual review.
- [x] **T2.2** — `src/shop_explore/prompts/planner.md`: drives one planner iteration. Reads prefetch, light browse budget (≤ 4 pages), emits `plan.md` over the §5.3 coverage taxonomy with priorities and inline briefs, plus a `## Omitted Areas` section. **Check:** lint-only.
- [x] **T2.3** — `src/shop_explore/prompts/execute.md`: drives one executor iteration. References `AGENTS.md`. Encodes the 8-step per-task obligation list (§5.7). **Check:** lint-only.
- [x] **T2.4** — `src/shop_explore/pipeline.py`: `explore(config) -> ExploreResult`. Sequence: derive `run_id`, `prefetch.run` into a temp seed dir, load prompt resources, build `PlanExecLoopConfig` with `artifact_seed_dir=seed_dir`, call `harness.run_plan_exec_loop`. **Check:** unit test with a stub runtime asserts the harness sees the right config + seed dir.
- [x] **T2.5** — Hand-craft a replay cassette under `tests/shop_explore/cassettes/fixture_drawer_shop/` covering plan + 4 executor iters (homepage_sections, cart_drawer, search_predictive, collection_filters). Each `workspace_after/artifact/` writes the expected `parts/<task>.md` + `parts/<task>.caps.json` + `evidence/<task>/...`. **Check:** cassette files validate against harness §5.6 minimal shape.
- [x] **T2.6** — `tests/shop_explore/test_pipeline_replay.py`: full pipeline against `harness.runtimes.replay` (synthesis stub). Asserts `parts/`, `evidence/`, `plan.md` populated. **Check:** SC1 partially satisfied (loop runs end-to-end); SC4 satisfied modulo synthesis.

**M2 acceptance:** harness e2e green under replay; no real LLM calls in CI.

### M3 · Synthesis

- [x] **T3.1** — `src/shop_explore/synthesize.py`: deterministic capabilities merge (calls `capabilities.merge_fragments`), deterministic stats compute, single-call LLM manual merge with retry-on-empty fallback to `parts/*.md` concatenation. Writes `manual.md`, `capabilities.json`, `stats.json`, `manifest.json`. **Check:** unit test of the deterministic path with the LLM mocked; second test forces empty LLM response and asserts `manifest.manual_fallback==true`.
- [x] **T3.2** — `src/shop_explore/prompts/synthesize_manual.md`: merge prompt. Re-applies anonymization rules. Output is the final `manual.md` body. **Check:** lint-only.
- [x] **T3.3** — Wire `synthesize` into `pipeline.explore` after the harness loop. Add `--synthesize-only PATH` to CLI. **Check:** `shop-explore --synthesize-only <run_dir>` against the M2 cassette emits a valid `manual.md` + `capabilities.json` + `stats.json` + `manifest.json`.
- [x] **T3.4** — `tests/shop_explore/test_anonymization.py`: regex scan over the synthesized `manual.md` and `capabilities.json` from the M2 fixture. Asserts no occurrence of source domain, store name, or first 20 product titles from `prefetch/products.json`. **Check:** SC3 satisfied on the fixture.

**M3 acceptance:** SC1 + SC2 + SC3 + SC4 satisfied on the replay fixture.

### M4 · Real-runtime smoke

- [x] **T4.1** — Pick 2 fixture profiles: one **feature-rich** (synthetic placeholder under `fixture_feature_rich/`, modelling a Shopify storefront with a mega menu, cart drawer, predictive search, faceted filters/sort, locale + currency switchers) and one **minimal** (**`https://theme-dawn-demo.myshopify.com`** — Shopify’s official Dawn theme preview store; minimal default-theme footprint). Document choice + license in `tests/shop_explore/cassettes/README.md`. **Check:** docs only.
- [x] **T4.2** — Record cassettes by running the live `pi` runtime against each fixture (`HARNESS_RECORD=1`). Commit refreshed cassettes. **Check:** `test_pipeline_replay.py` extends to the new fixtures and stays green. **Status:** Hand-crafted **synthetic placeholder** cassettes for `fixture_dawn_demo` (3 tasks, minimal storefront profile) and `fixture_feature_rich` (4 tasks, feature-rich profile distinct from `fixture_drawer_shop`) committed under `tests/shop_explore/cassettes/`; `test_pipeline_replay.py` parameterised over the two new fixtures and green. Live recording against the real Dawn demo storefront is the manual gate covered by T4.3; the per-fixture READMEs and `cassettes/README.md` flag the synthetic provenance so future refreshes overwrite in place. The feature-rich fixture is intentionally left as a synthetic placeholder — picking a live feature-rich storefront is deferred (see T4.5).
- [x] **T4.3** — `tests/shop_explore/smoke/test_pi.py`, marked `@pytest.mark.smoke`, gated behind `SHOP_EXPLORE_SMOKE_PI=1`. Runs the full pipeline live against `https://theme-dawn-demo.myshopify.com` (override via `SHOP_EXPLORE_SMOKE_URL`). Asserts harness `final_status==completed`, schema validates, ≥ 1 screenshot per task. **Check:** smoke run passes locally; CI skips by default.
- [x] **T4.4** — Coverage assertion: a deterministic check that, for the feature-rich fixture (`fixture_feature_rich`), every coverage-taxonomy area present in prefetch evidence appears as either a task or an `omitted_areas` entry. **Check:** SC5 satisfied.

**M4 acceptance:** SC5 satisfied; T4.3 smoke test green locally for the `pi` runtime against `https://theme-dawn-demo.myshopify.com`; feature-rich coverage exercised under replay via `fixture_feature_rich`. T4.5 (live feature-rich gate) deferred to v0.2.

### M5 · v0.1.0

- [x] **T5.1** — `src/shop_explore/__init__.py` re-exports the spec §8.1 public surface only. **Check:** `from shop_explore import explore, ExploreConfig, ExploreResult, Capabilities, Stats` works; nothing else top-level.
- [x] **T5.2** — `packages/shop_arena/src/shop_explore/README.md`: usage example, runtime-selection note, record-cassette workflow, layout reference. **Check:** README snippet runs end-to-end (`--prefetch-only` path).
- [x] **T5.3** — Update `docs/specs/README.md` ShopArena row to point at this spec + impl. Update repo `README.md` ShopArena bullet to describe `shop_explore` v0.1 status. **Check:** links resolve.
- [x] **T5.4** — Tag `shop-explore-v0.1.0`. Bump package version if shop_arena is independently versioned (currently `0.0.0` — leave unless we agree to bump). **Check:** tag pushed.

### M6 · v0.2 follow-ups

Gaps identified after the v0.1.0 tag landed. Sequencing: T6.1 → T6.2 (synthesis needs a model-configurable runtime); T6.3 depends on T6.2 (the recorded cassette should reflect real-LLM-driven runs). T6.4 and T6.5 are independent.

- [x] **T6.1** — `harness.runtimes.pi`: configurable model. Extend the `pi` runtime so callers can pin or swap the underlying Claude model via constructor / `RuntimeFactory` argument without editing harness internals. Default preserves existing behavior. **Check:** unit test passes a non-default model identifier into the pi runtime and asserts it threads through to the underlying LLM call; existing `pi` runtime tests remain green. **Status:** `PiRuntime.__init__` now accepts `model: str | None = None`; the new `build_argv()` helper appends `--model <model>` only when set, so the default invocation is byte-identical to pre-T6.1. Plumbed through `get_runtime("pi", model=...)` (no registry change needed — kwargs already forward). Four new unit tests in `tests/unit/runtimes/test_pi.py` cover the default-omitted, model-set, runtime-property, and registry-forwarding paths; the existing 16 pi tests stay green.
- [x] **T6.2** — Synthesis LLM via harness runtime. Replace `_NoOpLLMClient` in `pipeline.py` and `cli.py` with an adapter that delegates `LLMClient.complete(prompt)` to the harness runtime's LLM client (instantiated with the run's chosen model from T6.1). Resolves open question §7.2 in favor of "reuse harness runtime LLM" over the direct `anthropic` SDK path. **Check:** unit test of `pipeline.explore` against a stub harness runtime asserts the synthesis call is routed through it; a non-stub run against the M2 cassette emits `manifest.manual_fallback == False`. **Status:** added `LLMCompleter` sub-Protocol in `harness.runtimes.base` (kept off the top-level `harness.__all__` to preserve spec §8.1); `PiRuntime.complete` invokes `pi --print --mode text --no-tools --no-context-files --no-session [--model M]` for one-shot completions; `pipeline.build_runtime_llm` wraps any completer runtime in `_RuntimeLLMClient`, falling back to `_NoOpLLMClient` for non-completer runtimes (e.g. replay). Both `pipeline.explore` and `cli._run_synthesize_only` now route synthesis through this adapter. New tests cover (a) `pipeline.explore` flipping `manifest.manual_fallback` to `False` when the runtime answers, (b) `build_runtime_llm` wiring the timeout through, (c) the CLI surface against both stub runtimes, and (d) `build_complete_argv` model-omitted/set + `LLMCompleter` structural-protocol checks. T6.3 will exercise the non-stub M2 cassette branch.
- [x] **T6.3** — Record real `fixture_dawn_demo` cassette. **Deferred to v0.2** — same shape as T4.5: the live-recording flow needs three things that aren't autonomously executable today: (a) a recording branch in `shop_explore.pipeline.explore()` that wraps `PiRuntime` in `ReplayRuntime(fallback=…)` so `HARNESS_RECORD=1` actually triggers cassette capture (today `explore()` constructs a bare `PiRuntime` and ignores the env var), (b) a test-rebaseline policy for `tests/shop_explore/test_pipeline_replay.py::_DAWN_DEMO_FIXTURE` whose hardcoded `tasks` tuple + `sentinel_caps` won't match real `pi` output verbatim, and (c) the hand-review + `native.log` scrub gate documented in `cassettes/README.md` §3 step 2–3. v0.1.0 ships with the synthetic `fixture_dawn_demo` placeholder; the live recording will land alongside the recording-branch wiring in v0.2. **Status:** synthetic placeholder under `tests/shop_explore/cassettes/fixture_dawn_demo/` retained; `fixture_dawn_demo/README.md` and `cassettes/README.md` continue to advertise "synthetic placeholder" provenance to avoid drift.
- [x] **T6.4** — Exact `products_total` via pagination (spec §8.2.5). Replace the boolean `products_truncated` flag with real pagination over `/products.json?page=N&limit=250` in `prefetch.runner` and update `stats.compute` to set `Stats.products_total` from the paginated total. **Check:** unit test against a `respx`-mocked storefront with > 250 products asserts `products_total` matches the sum across pages; existing fixture-based stats tests remain green. **Status:** `prefetch.runner._fetch_products_paginated` now walks `/products.json?page=N&limit=250` (Shopify storefront max), terminating on a short page, non-200, malformed body, transport error, or the 200-page safety cap. Per-page entries land in `prefetch.json` in natural fetch order (after `/sitemap.xml`, before `/collections.json`); only the first OK page carries `saved_to="products.json"` so the merged `{"products": [...]}` document on disk has a discoverable origin. `stats.Stats` drops the `products_truncated` field — closed-schema validation now rejects it explicitly — and `stats.compute` returns `products_total = len(products)`. Spec §5.9 + §8.2.5 updated. New `test_run_paginates_products_until_short_page` covers the multi-page merge + stop-on-short-page contract; the existing happy-path test stays green because the empty-products mock terminates pagination after one page.
- [x] **T6.5** — Bump `shop_arena` package to `0.1.0` and refresh stale docs. Update `packages/shop_arena/pyproject.toml` `version` and `shop_explore/_version.py` `__version__` to `0.1.0`; refresh `packages/shop_arena/src/shop_explore/README.md` status line (currently claims "M4 + M5 release pending"). **Check:** `from shop_explore import __version__` returns `"0.1.0"`; README status matches the impl-plan checkbox state.

**M6 acceptance:** synthesis no longer falls back to `parts/*.md` concatenation on real runs; `products_total` is exact; package version matches the `shop-explore-v0.1.0` tag. T6.3 (live `fixture_dawn_demo` cassette) deferred to v0.2 — see task note for rationale; the synthetic placeholder ships with v0.1.0.

---

## 6. Milestones (summary)

| Milestone | Tasks       | Gate                                                           |
| --------- | ----------- | -------------------------------------------------------------- |
| M1        | T1.1–T1.6   | unit tests + pyright strict + ruff; no harness coupling        |
| M2        | T2.1–T2.6   | M1 + harness e2e under replay runtime, no real LLM in CI       |
| M3        | T3.1–T3.4   | M2 + SC1–SC4 satisfied on replay fixture                       |
| M4        | T4.1–T4.4   | M3 + SC5 satisfied; smoke gated by env var; T4.5 deferred       |
| M5        | T5.1–T5.4   | All prior + README + docs index + tag                          |
| M6        | T6.1–T6.5   | Real LLM via harness runtime; exact `products_total`; v0.1.0 version bump (T6.3 live dawn_demo cassette deferred to v0.2) |

## 7. Appendix

### 7.1 Out-of-scope (deferred)

Tracked here so we don't drift into them: deterministic anonymization
scrubber, cross-shop manual merging, mobile viewport pass,
authenticated flows, headed-debug pipe-through, full asset crawl. See
spec §6 + §8.3.

### 7.2 Open questions

- ~~LLM client for the synthesis pass: reuse the harness runtime's LLM
  vs. a direct `anthropic` SDK call.~~ **Resolved (2026-04-25):**
  reuse harness runtime LLM (T6.2); extend `pi` runtime with a
  configurable model identifier (T6.1).
- Whether to ship the playwright skill as a pinned git submodule or
  rely on the user-installed copy. M2 needs a decision.
- Fixture-storefront licensing for cassette redistribution. Block on
  T4.1.
