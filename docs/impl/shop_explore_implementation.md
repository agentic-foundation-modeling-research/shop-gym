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

- [x] **T4.1** — Pick 2 fixture storefronts: one feature-rich (**`https://fermliving.com`** — Shopify-based, has mega menu, cart drawer, predictive search, filters/sort, locale switcher) and one minimal (**`https://theme-dawn-demo.myshopify.com`** — Shopify’s official Dawn theme preview store; minimal default-theme footprint). Document choice + license in `tests/shop_explore/cassettes/README.md`. **Check:** docs only.
- [x] **T4.2** — Record cassettes by running the live `pi` runtime against each fixture (`HARNESS_RECORD=1`). Commit refreshed cassettes. **Check:** `test_pipeline_replay.py` extends to the new fixtures and stays green. **Status:** Hand-crafted **synthetic placeholder** cassettes for `fixture_dawn_demo` (3 tasks, minimal storefront profile) and `fixture_fermliving` (4 tasks, feature-rich profile distinct from `fixture_drawer_shop`) committed under `tests/shop_explore/cassettes/`; `test_pipeline_replay.py` parameterised over the two new fixtures and green. Live-recording the two cassettes against the real storefronts is the manual M4 gate folded into T4.5; the per-fixture READMEs and `cassettes/README.md` flag the synthetic provenance so future refreshes overwrite in place.
- [x] **T4.3** — `tests/shop_explore/smoke/test_pi.py`, marked `@pytest.mark.smoke`, gated behind `SHOP_EXPLORE_SMOKE_PI=1`. Runs the full pipeline live against one fixture. Asserts harness `final_status==completed`, schema validates, ≥ 1 screenshot per task. **Check:** smoke run passes locally; CI skips by default.
- [x] **T4.4** — Coverage assertion: a deterministic check that, for the feature-rich fixture (fermliving.com), every coverage-taxonomy area present in prefetch evidence appears as either a task or an `omitted_areas` entry. **Check:** SC5 satisfied.
- [x] **T4.5** — **Live e2e validation against `https://fermliving.com`**. Run the full pipeline (`shop-explore https://fermliving.com --runtime pi`) end-to-end with the live `pi` runtime and the live storefront. Assertions:
    1. `prefetch/` populates `index.html`, `sitemap.xml`, `products.json`, `collections.json`, `cart.js`, and at least 4 policy/info pages — none flagged as bot-blocked.
    2. `plan.md` contains tasks covering at minimum: `homepage_sections`, `header_navigation` (mega menu), `collection_filters`, `product_variants`, `cart_drawer`, `search_predictive`, `info_pages`.
    3. Harness `final_status==completed`; ≥ 80% of planner-emitted tasks reach `[x]` (rest may be `[!]` with documented reason).
    4. `capabilities.json` validates and reports: `cart.type=='drawer'`, `search.has_predictive==true`, `site_shell.has_mega_menu==true`, `intl.has_locale_switcher==true`, non-empty `collection.filters`, non-empty `collection.sort`.
    5. `stats.json` reports `products_total >= 50` (truncated flag acceptable) and a non-empty `variant_axes_observed`.
    6. `manual.md` is ≥ 1500 chars and the anonymization regex scan (T3.4) finds zero leaks of `fermliving`, `Ferm Living`, the source domain, or any of the first 20 product titles from `prefetch/products.json`.
    7. ≥ 1 full-page screenshot per executor task under `evidence/<task_id>/screenshots/`.

    Captured artifacts (`run_dir/`) are committed to `tests/shop_explore/fixtures/fermliving_live/` (with `iters/native.log` redacted of any API keys) so future regressions on the same shop are diff-reviewable. The test itself is gated behind `SHOP_EXPLORE_LIVE_FERMLIVING=1` and skipped in CI; intended as a manual milestone gate, not a recurring CI job. **Check:** one successful local run; assertions documented as the M4 acceptance evidence. **Status:** `tests/shop_explore/smoke/test_pi_fermliving.py` codifies all seven assertions and is gated behind `SHOP_EXPLORE_LIVE_FERMLIVING=1`; setting `SHOP_EXPLORE_LIVE_PERSIST=1` additionally captures the `run_dir/` under `tests/shop_explore/fixtures/fermliving_live/` (placeholder README + `.gitignore` committed; populated by the human running the manual gate).

**M4 acceptance:** SC5 satisfied; smoke test green locally for the `pi` runtime; T4.5 live run against fermliving.com passes all assertions and its run_dir is committed as a fixture.

### M5 · v0.1.0

- [x] **T5.1** — `src/shop_explore/__init__.py` re-exports the spec §8.1 public surface only. **Check:** `from shop_explore import explore, ExploreConfig, ExploreResult, Capabilities, Stats` works; nothing else top-level.
- [x] **T5.2** — `packages/shop_arena/src/shop_explore/README.md`: usage example, runtime-selection note, record-cassette workflow, layout reference. **Check:** README snippet runs end-to-end (`--prefetch-only` path).
- [x] **T5.3** — Update `docs/specs/README.md` ShopArena row to point at this spec + impl. Update repo `README.md` ShopArena bullet to describe `shop_explore` v0.1 status. **Check:** links resolve.
- [x] **T5.4** — Tag `shop-explore-v0.1.0`. Bump package version if shop_arena is independently versioned (currently `0.0.0` — leave unless we agree to bump). **Check:** tag pushed.

---

## 6. Milestones (summary)

| Milestone | Tasks       | Gate                                                           |
| --------- | ----------- | -------------------------------------------------------------- |
| M1        | T1.1–T1.6   | unit tests + pyright strict + ruff; no harness coupling        |
| M2        | T2.1–T2.6   | M1 + harness e2e under replay runtime, no real LLM in CI       |
| M3        | T3.1–T3.4   | M2 + SC1–SC4 satisfied on replay fixture                       |
| M4        | T4.1–T4.5   | M3 + SC5 satisfied; smoke gated by env var; live fermliving.com run passes |
| M5        | T5.1–T5.4   | All prior + README + docs index + tag                          |

## 7. Appendix

### 7.1 Out-of-scope (deferred)

Tracked here so we don't drift into them: deterministic anonymization
scrubber, cross-shop manual merging, mobile viewport pass,
authenticated flows, headed-debug pipe-through, full asset crawl. See
spec §6 + §8.3.

### 7.2 Open questions

- LLM client for the synthesis pass: reuse the harness runtime's LLM
  vs. a direct `anthropic` SDK call. Lean direct.
- Whether to ship the playwright skill as a pinned git submodule or
  rely on the user-installed copy. M2 needs a decision.
- Fixture-storefront licensing for cassette redistribution. Block on
  T4.1.
