# ShopGen (`packages/shop_arena/src/shop_gen`)

Status: **Spec (draft)** · Version: **0.1**
Owners: ShopArena

> A configurable pipeline that turns one or more anonymized **Shop
> Manuals** (from `shop_explore`) into a complete, hostable
> **SandboxShop**: a synthesized dataset *and* a generated Hydrogen
> storefront, validated end-to-end by hosting the data with
> `shop_backend`.

---

## 1. Overview

`shop_gen` is the second half of ShopArena. Given the published Shop
Manual bundle for one or more seed storefronts, it produces:

1. A **SandboxShop dataset** (`data/`) — JSON files matching the
   `shop_backend` v0.1 contract (see
   [shop_backend/storefront_api.md §8.1](../shop_backend/storefront_api.md)).
2. A **SandboxShop site** (`hydrogen/`) — a generated Hydrogen app
   that talks to a `shop_backend` instance hosting the dataset.

Four design choices shape the module:

- **Manual-driven, not extraction-driven.** All synthesis reads from
  the public `manual.md` + `capabilities.json` + `stats.json` triple
  produced by `shop_explore`. No live storefront access, no BigQuery,
  no scraping.
- **Brand-safe by allowlist.** Generated catalogs draw all
  brand-shaped tokens (store name, vendors) from a small curated
  list of made-up fake brands. Product / collection titles are plain
  descriptive English ("white sport t-shirt", not "Comfrt Cloud
  Tee"). A deterministic post-pass scanner enforces the allowlist
  rather than blocking a (necessarily incomplete) blocklist of real
  brands. See §5.6.
- **Step DAG with smart resume.** The pipeline is a small DAG of
  named steps (`merge_capabilities`, `synth_collections`,
  `gen_homepage`, …) with explicit dependencies. The CLI exposes
  *one* run command + `--from <step>` / `--only <step>` /
  `--status`; the orchestrator computes which steps are stale and
  re-runs them in topological order. See §5.7.
- **Harness-driven build, with caller-owned verifiers.** The
  website-build phase is one `harness.run_plan_exec_loop` invocation
  that gates each task on a caller-owned **verifier set** (rule +
  LLM). The harness extension that powers this lives in a separate
  spec — [`harness/verifiers.md`](../harness/verifiers.md) — and
  must land before `shop_gen` ships. `shop_gen` owns every
  verifier *implementation*; the harness only dispatches them.

`shop_gen` is the first caller of both `shop_backend` (as a hosting
sidecar) and the harness verifier extension.

---

## 2. Terminology

- **Seed Shop Manual** — the published bundle ShopExplore writes
  under `outputs/shop_manuals/<domain>/<run_id>/artifact/`
  (manual.md, capabilities.json, stats.json, manifest.json,
  prefetch/). One or more are inputs to `shop_gen`.
- **Composite Manual** — the merged manual produced by Phase 1 when
  `len(seeds) > 1`. Same shape as a single Shop Manual.
- **SandboxShop dataset** — JSON files under `<out_dir>/data/`.
  Authoritative shape: shop_backend §8.1.
- **SandboxShop site** — Hydrogen app under `<out_dir>/hydrogen/`,
  cloned from the vendored template at
  `packages/shop_arena/src/shop_gen/templates/hydrogen/`.
- **Fake-brand allowlist** — a small static list of 8 invented
  brand tokens (Vendarena, AisleArena, Shopliseum, CartColiseum,
  StockyardArena, AgoraDome, AgoraCage, AgoraPit), shipped at
  `packages/shop_arena/src/shop_gen/brands/fake_brands.json`. Every
  brand-shaped string in `data/*.json` must be drawn from this list.
- **Step** — a named, dependency-aware unit of work in the pipeline.
  Each step has a stable id, declared inputs/outputs, declared
  dependencies, and an idempotent runner.
- **Hosting sidecar** — a `shop-backend` process started by `shop_gen`
  before the build loop, serving the synthesized dataset on a local
  port for the agent to query and render against.
- **Verifier** — a caller-owned check (rule-based or LLM-as-judge)
  the harness dispatches after each executor iteration. PASS / FAIL /
  ADVISORY. See [harness/verifiers.md](../harness/verifiers.md).

---

## 3. Current Status

- `packages/shop_arena/src/shop_gen/` is a 4-file scaffold (`cli.py`
  prints "not implemented yet"). No spec, no module structure, no
  pipeline logic.
- An out-of-tree reference uses
  `browser_use` agents and a hand-rolled step-runner state machine
  with ~14 ordered steps. It pre-dates `packages/harness` and
  `shop_backend`.
- `packages/harness` ships `run_plan_exec_loop` (v0.1) but exposes
  no independent verifier API. The verifier extension required for
  Phase 4 of this pipeline is specified separately at
  [`harness/verifiers.md`](../harness/verifiers.md).
- `packages/shop_backend` is implemented and consumes the dataset
  schema this pipeline must produce.
- The Hydrogen template has been vendored under
  `packages/shop_arena/src/shop_gen/templates/hydrogen/` for
  pipeline-internal use.

---

## 4. Desired Status

A self-contained module under `packages/shop_arena/src/shop_gen/`
that, given one or more `shop_manual` directories, produces a
complete, hostable SandboxShop with a passing data validation and a
passing build verifier suite.

### 4.1 I/O contract

**Inputs** (CLI or library):

| Input             | Notes                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------ |
| `seeds`           | One or more paths to `shop_manuals/<domain>/<run_id>/`. ≥ 1 required.                                  |
| `out_dir`         | Defaults to `outputs/shops/<name>/`. Must be empty, non-existent, or a prior `shop_gen` run dir.       |
| `name`            | Slug for the SandboxShop. Inferred from seed domain when single, or auto-derived when multi-seed.      |
| `runtime`         | Agent runtime for the build loop. `pi` (default) or `claude_code`.                                     |
| `model`           | Model id forwarded to the runtime.                                                                     |
| `catalog`         | `{"collections": 10, "products_per_collection": 20, "images_per_product": 2}` — defaults; configurable. v0.1 ships small (200 products / 400 images); scaling is a v0.2 concern. |
| `max_iters`       | Executor budget for the build loop. Default 30.                                                        |
| `image_backend`   | `placeholder` (default v0.1) or `ai` (later). Alt-text is generated regardless.                        |

**Outputs** under `<out_dir>/`:

```
<out_dir>/
├── manual/                   # PUBLISHED — manual fed into the build (composite or single seed)
│   ├── manual.md
│   ├── capabilities.json
│   ├── stats.json
│   └── manifest.json         # records seed list + per-area merge conflicts
├── identity.json             # PUBLISHED — synthesized fake-brand identity (name, descriptor, tone, currency, country)
├── data/                     # PUBLISHED — SandboxShop dataset (shop_backend §8.1)
│   ├── store.json
│   ├── products.json
│   ├── collections.json
│   ├── navigation.json
│   ├── pages.json
│   ├── policies.json
│   ├── blogs.json            # optional
│   ├── metafields.json       # optional
│   └── images/               # placeholder SVGs (v0.1) or generated images (v0.2)
├── hydrogen/                 # PUBLISHED — generated Hydrogen app (cloned from template, then mutated)
├── data_validation.json      # PUBLISHED — schema + hosting check verdict
├── final_eval.json           # PUBLISHED — advisory quality verdict
├── runs/                     # debugging — harness run_dir for the build phase
│   └── build/
└── .shop_gen/                # internal — step state + cached intermediates
    ├── state.json            # per-step status, fingerprints, timestamps
    └── stage_cache/          # cached stage outputs for data_synth
```

### 4.2 Success criteria

| ID  | Criterion                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------- |
| SC1 | Given ≥ 1 valid Shop Manual seed, the pipeline emits a `data/` directory that `shop_backend.loadShopData` accepts.    |
| SC2 | Hosting `data/` with `shop_backend` and running the sanity-query suite passes (shop, products, collection, cart life-cycle, search). |
| SC3 | The generated `hydrogen/` app builds (`tsc + react-router build`) and renders home, a product, and a collection against the hosted dataset. |
| SC4 | Every brand-shaped token in `data/*.json` and `hydrogen/app/**/*.{tsx,ts,css}` is a member of the fake-brand allowlist. |
| SC5 | A multi-seed run (≥ 2 seeds) merges manuals into one composite identity that passes the same downstream checks as a single seed. |
| SC6 | All build-loop verifiers (rule + LLM) report PASS or ADVISORY at run completion; no BLOCKING failures.                 |
| SC7 | A re-invocation with no flags is a no-op (exit 0, "all steps up-to-date"). `--from <step>` re-runs the requested step + downstream stale steps. |

---

## 5. Proposal

### 5.1 Architecture

```
seeds[1..N] ──► [1] Manual Merge ──► composite_manual ──┐
                  (LLM, skip if N=1)                    │
                                                        ▼
                                   [2] Data Synthesis ──► data/  ◄── fake-brand allowlist
                                       (multi-stage LLM, pydantic-validated)
                                                        │
                                                        ▼
                                   [3] Data Validation
                                       ┌────────────────┴────────────────┐
                                       │  schema check (pydantic)        │
                                       │  hosting check (boot backend +  │
                                       │  fixed query suite)             │
                                       └────────────────┬────────────────┘
                                                        │ pass
                                                        ▼
                       template/ ──► [4] Build Harness Loop
                                       ┌────────────────┴────────────────┐
                                       │  4.1 env setup                  │
                                       │      • clone vendored template  │
                                       │      • write .env (sidecar URL) │
                                       │      • start sidecar            │
                                       │  4.2 plan (planner agent)       │
                                       │  4.3 exec + verify loop         │
                                       │      ▲    │                     │
                                       │      └─ retry on FAIL ─┐        │
                                       │           ▼            │        │
                                       │       caller verifiers │        │
                                       │       (rule + LLM)     │        │
                                       └────────────────┬────────────────┘
                                                        │
                                                        ▼
                                   [5] Final Eval (advisory)
                                                        │
                                                        ▼
                                                  SandboxShop
                                                  (data/ + hydrogen/)
```

Phases run in order. Internally, each phase decomposes into named
**steps** (§5.7); the orchestrator drives the step DAG and is the
single source of truth for what re-runs when.

### 5.2 Phase 1 — Manual Merge

**When:** `len(seeds) > 1`. With a single seed, the manual files are
copied verbatim into `<out_dir>/manual/` and Phase 1 is a no-op.

**Steps:**

| Step                   | Inputs                                | Output                                |
| ---------------------- | ------------------------------------- | ------------------------------------- |
| `merge_capabilities`   | seed `capabilities.json`s             | `manual/capabilities.json`            |
| `merge_manual_prose`   | seed `manual.md`s + merged caps       | `manual/manual.md`                    |
| `compute_merge_stats`  | seed `stats.json`s + merged caps      | `manual/stats.json`                   |
| `write_merge_manifest` | seed list + merge conflicts           | `manual/manifest.json`                |

**Approach:**

1. **`merge_capabilities`** — per-area merge with explicit rules
   (see §9.2). Booleans union (any-true → true); enum / scalar
   fields use majority + descriptor-consistency tiebreak; lists
   union with dedup. The output is validated against the same closed
   pydantic schema `shop_explore` writes.
2. **`merge_manual_prose`** — section-by-section LLM merge, treating
   the merged capabilities as ground truth (the prose must not
   contradict it).
3. **`compute_merge_stats`** — deterministic recomputation from the
   merged caps + seed prefetch summaries. No LLM.
4. **`write_merge_manifest`** — record seed paths, merge conflicts,
   and per-area write history.

**Core challenges:**

- **Coherence vs. inclusion.** Naïve union → Frankenshop;
  intersection → loss of distinguishing features. Per-key rules in
  §9.2 codify the trade-off; ties fall through to an LLM call with
  the `descriptor` as context. The merge is **deterministic per
  rule** and **LLM-driven only on tie**.
- **No brand context yet.** The merge happens before identity
  synthesis. Capability merge is brand-free by construction; prose
  merge is brand-free by prompt rule and is post-pass-checked once
  `identity.json` exists (Phase 2 step `synth_identity` runs the
  scrubber across `manual/manual.md` too — see §5.6).

### 5.3 Phase 2 — Data Synthesis

**Input:** `manual/`. **Output:** `data/*.json` matching shop_backend
§8.1 + `identity.json` + `data/images/`.

**Catalog scale (configurable):** v0.1 default targets

```
collections             = 10
products_per_collection = 20
images_per_product      = 2
                ⇒ 200 products, 400 images
```

Small enough that a single LLM call can list all 200 product
titles in one shot, but the per-collection structure is preserved
in the steps so we can scale `products_per_collection` upward
later without restructuring the DAG. Scalability beyond 200
products (parallel-batched naming, paginated assembly, sharded
image generation) is deliberately deferred to a v0.2 follow-up.

**Steps:**

| Step                         | Depends on                           | Output                              |
| ---------------------------- | ------------------------------------ | ----------------------------------- |
| `synth_identity`             | `manual/`                            | `identity.json`                     |
| `synth_store`                | `synth_identity`                     | `.shop_gen/stage_cache/store.json`  |
| `synth_collections`          | `synth_identity`, merged caps, stats | `.shop_gen/stage_cache/collections.json` |
| `synth_navigation`           | `synth_collections`, merged caps     | `.shop_gen/stage_cache/navigation.json` |
| `synth_pages`                | `synth_identity`, merged caps        | `.shop_gen/stage_cache/pages.json`  |
| `synth_policies`             | `synth_identity`                     | `.shop_gen/stage_cache/policies.json` |
| `synth_product_skeletons`    | `synth_collections`                  | `.shop_gen/stage_cache/skeletons.json` (200 titles, handles, prices; one bulk call at v0.1 scale) |
| `synth_product_details`      | `synth_product_skeletons`            | `.shop_gen/stage_cache/details/<collection>.json` (collections in parallel; within a collection, ≤ 10 skeletons per LLM call) |
| `synth_alt_text`             | `synth_product_details`              | `.shop_gen/stage_cache/alt_text.json` |
| `gen_images`                 | `synth_product_details`              | `data/images/*.svg` (placeholder) or `*.png` (AI; later) |
| `assemble_data`              | all of the above                     | `data/*.json` (final, allowlist-scrubbed) |

**Step details:**

- **`synth_identity`** — one small LLM call. Reads merged caps +
  prose. Emits `{name, descriptor, tone[], currency, country}` where
  `name` is selected from the **fake-brand allowlist** (not invented
  by the LLM). For multi-seed merges, this is where the "single
  identity from N seeds" question (user feedback) is answered:
  the prompt receives all seed descriptors and tones; the LLM
  produces a single coherent descriptor / tone vector that fits the
  merged capabilities, and the orchestrator deterministically picks
  `name` from the allowlist using a hash of `seeds + descriptor` so
  the choice is reproducible.

- **`synth_collections`** — one LLM call producing N collection
  records (default 10): title (plain descriptive — "outerwear",
  "kitchen tools"), handle, description, sort_order, target product
  count.

- **`synth_product_skeletons`** — at v0.1 scale (200 products),
  one bulk LLM call returns all titles + handles + price hints +
  collection assignments in a single pass. Bulk naming makes
  duplicates impossible by construction. Naming rule shipped in
  the prompt:

  > Use plain English noun phrases. Never invent brand names. Two to
  > five words. Examples: "white sport t-shirt", "ceramic coffee
  > mug, 12oz", "leather card wallet".

  At higher scales (v0.2) this fans out to per-collection parallel
  calls; the step interface stays the same.

- **`synth_product_details`** — collections run in parallel (≤ 5
  concurrent workers). Within a collection the skeleton list is
  partitioned into chunks of ≤ 10 skeletons; each chunk drives one
  LLM call (chunks within a collection run sequentially). Each call
  receives the chunk's skeletons + the identity + caps product
  profile, and returns variants, options, description_html, vendor
  (allowlist-drawn), tags. Pydantic-validated at the boundary;
  rejected rows are re-prompted once before being dropped. Chunking
  bounds per-call output size below the model's effective output-token
  ceiling so a large collection cannot truncate a single response and
  fail the whole step — the per-collection cache file shape
  (`<collection>.json` containing all surviving details) is unchanged.

- **`synth_alt_text`** — one LLM call per collection (parallel).
  Receives skeletons + details. Returns 2 alt-text strings per
  product, used by `gen_images` and embedded in
  `products[].images[].alt`.

- **`gen_images`** — pluggable backend. v0.1 ships a deterministic
  **placeholder** generator: an SVG per image with the category
  icon + the product title rendered as text, sized to honor
  capabilities.json's gallery hints. The image generator is a
  swap-in module landing in a follow-up milestone (see §8); the
  Protocol is shaped to accept either.

- **`assemble_data`** — combines stage outputs into the final
  `data/*.json`, runs the **allowlist scrubber** (§5.6) over every
  string field, assigns deterministic numeric ids, and emits the
  files. **This is the only step that writes under `data/`.**

**Core challenges:**

- **Dedup safety at scale.** Per-collection bulk naming makes
  intra-collection dedup trivial. Cross-collection conflicts are
  resolved at assembly time by handle suffixing.
- **Schema strictness vs. LLM drift.** Strict pydantic at the
  boundary. Both per-row validation rejects (pydantic / allowlist)
  and whole-response parse failures (e.g. truncated JSON) consume the
  same one re-prompt budget; the raw response of every parse failure
  is persisted under
  `.shop_gen/stage_cache/details/_failed_<collection>_chunk_<i>_attempt_<n>.txt`
  for inspection. Surviving per-row drops contribute to the global
  rejection counter; > 5% rejection rate fails the step (the catalog
  cap is structural). An unrecovered whole-response parse failure
  also fails the step — there is no usable payload to silently drop
  the chunk's skeletons against.
- **Stats faithfulness.** The seed's `stats.json` priors (median
  price, variant axes) are *priors*, not targets. The catalog must
  be plausible, not statistically identical.
- **Scrubbing without losing meaning.** Allowlist enforcement (§5.6)
  is run as the final substep of `assemble_data`, **not** as a
  separate step, because a scrub that fires must trigger a one-shot
  retry of the offending stage rather than silent redaction.

### 5.4 Phase 3 — Data Validation

**Input:** `<out_dir>/data/`. **Output:** `data_validation.json`.

**Steps:**

| Step                | Depends on        | Output                           |
| ------------------- | ----------------- | -------------------------------- |
| `validate_schema`   | `assemble_data`   | (in-memory verdict)              |
| `validate_hosting`  | `validate_schema` | `data_validation.json`           |

**Approach:**

1. **`validate_schema`** — run the same pydantic validators the
   synthesizer uses on output. Fast, deterministic, in-process.
2. **`validate_hosting`** — boot `shop-backend <data>` on a free
   localhost port. Run a fixed Storefront-API query suite:
   - `Query.shop` returns name, currency, primaryDomain.
   - `Query.products(first: 50)` returns ≥ 0.8 × target.
   - `Query.collections(first: 50)` returns the configured count.
   - `Query.collection(handle)` resolves with non-empty products.
   - `Query.product(handle)` resolves with variants + images.
   - Cart lifecycle: `cartCreate` → `cartLinesAdd` → `cartLinesUpdate` → `cartLinesRemove`.
   - `Query.search(query: <random title token>)` returns ≥ 1 hit.
   - `GET /images/<sample>` returns 200 + correct MIME.

A failure is a hard stop in v0.1; the orchestrator marks
`assemble_data` stale and instructs the user to re-run with
`--from assemble_data`. (Auto-retry on hosting failure is a v0.2
follow-up — see §8.)

### 5.5 Phase 4 — Build Harness Loop

**Input:** `data/`, `manual/`, `identity.json`, vendored
template. **Output:** `hydrogen/`.

This phase is one `harness.run_plan_exec_loop` invocation. The
harness owns iteration lifecycle, plan parsing, and telemetry;
`shop_gen` owns prompts, the verifier set, and the sidecar. It also
relies on the additive harness verifier extension —
[`harness/verifiers.md`](../harness/verifiers.md) — which **must
land first**.

#### 5.5.1 4.1 Env setup (pre-loop)

Steps run by the orchestrator before invoking the harness:

| Step              | Action                                                                        |
| ----------------- | ----------------------------------------------------------------------------- |
| `clone_template`  | `cp -R packages/shop_arena/src/shop_gen/templates/hydrogen <out_dir>/hydrogen` |
| `write_env_file`  | Write `<out_dir>/hydrogen/.env` with `PUBLIC_STORE_DOMAIN=localhost:<port>` etc. |
| `start_sidecar`   | Spawn `shop-backend <out_dir>/data <port>`; hold pid; install signal cleanup.  |

The harness `artifact_seed_dir` is `<out_dir>/manual/` — the seeded
subtree is the *manual*, not the *hydrogen tree*. The hydrogen tree
lives at `<run_dir>/artifact/hydrogen/` (mutable). This split is
deliberate: seed-immutability protects the immutable inputs (the
manual the agent reads); the hydrogen tree is the work surface and
must stay mutable.

#### 5.5.2 4.2 Plan (planner agent)

The planner reads `AGENTS.md` + the manual + a dataset summary
(top-level counts, sample handles) + the cloned hydrogen tree, and
emits `plan.md` with build tasks at roughly the granularity of the
reference pipeline:

```
- [ ] gen_theme           [priority: 9]  — tokens, palette, typography
- [ ] gen_navigation      [priority: 8]  — Header, Footer, MegaMenu, Mobile, announcement bar
- [ ] gen_homepage        [priority: 7]  — hero, featured collections, promo banner
- [ ] gen_collections     [priority: 6]  — collection list/detail, ProductItem, filters/sort
- [ ] gen_product         [priority: 5]  — product detail, variant pickers, gallery
- [ ] gen_cart_search     [priority: 4]  — cart drawer, predictive search, popups
- [ ] gen_info_pages      [priority: 3]  — about, contact, policies, FAQ
- [ ] visual_polish       [priority: 2]  — final layout/spacing pass (advisory verifiers only)
- [ ] consolidate         [priority: 1]  — REQUIRED final task; cross-task cleanup (§5.5.4)
```

Tasks are PENDING + priority-ordered. The planner is *prompted* to
honour the dependency order (theme → navigation → homepage), but the
state machine cannot enforce it; verifier dispatch (§5.5.3) catches
the cases where this matters.

#### 5.5.3 4.3 Exec + verify loop

The harness verifier extension (separate spec) provides the
mechanism: after each executor iteration, applicable verifiers run
sequentially; any `FAIL` rewrites `[x]` → `[~]` and feeds
`{{verifier_feedback}}` to the next iteration's prompt.

**`shop_gen` owns every verifier implementation.** They live under
`packages/shop_arena/src/shop_gen/build/verifiers/` and are passed to
the harness via `PlanExecLoopConfig.verifiers`.

**v0.1 verifier set:**

| Name                  | Type | Applies to                              | Behavior                                                                |
| --------------------- | ---- | --------------------------------------- | ----------------------------------------------------------------------- |
| `tsc`                 | rule | every `gen_*` task                      | `pnpm tsc --noEmit` clean.                                              |
| `build`               | rule | every `gen_*` task                      | `pnpm --filter hydrogen build` succeeds.                                |
| `data_in_use`         | rule | every `gen_*` task                      | The agent's GraphQL queries match shop_backend's schema (introspection diff). |
| `nav_coverage`        | rule | post `gen_navigation`                   | Every collection in `data/collections.json` is reachable from the nav.  |
| `quality_judge`       | LLM  | post `gen_homepage`, `gen_product`, `gen_cart_search`, `visual_polish`, `consolidate` | Render the page; LLM judges quality against `capabilities.json` keys. **Quality-only**, not a cross-compare with seeds. |
| `visual_judge`        | LLM  | post `gen_homepage`, `gen_product`, `gen_cart_search`, `visual_polish`, `consolidate` | Boots a transient dev server and drives the playwright skill against the task's routes; LLM judges the **rendered** storefront against the bucket-filtered `capabilities.json` slice. Per-task retry budget; page-bucket fan-out for `consolidate`. See [`visual_verifier.md`](visual_verifier.md). |
| `cross_task_consistency` | LLM | post `consolidate`             | Whole-app sweep: are all generated components mutually consistent (shared design tokens, shared types, no orphan imports, navigation matches collections)? |

The set is pluggable via the library API: callers can append custom
verifiers, or swap the default list entirely. The CLI surface for
custom verifiers is deferred (config-file only in v0.1).

#### 5.5.4 4.4 The `consolidate` task (cross-ownership cleanup)

Each `gen_*` task is owned by one executor iteration; verifiers
in v0.1 cannot re-open *other* tasks (verifiers spec §7 Q1). Real
cross-task issues — a nav link pointing to a route the homepage
later renamed, two pages importing slightly different versions of
a shared component, design tokens drifting between theme + cart —
fall through that gap.

`shop_gen` closes the gap with a **mandatory final task** the
planner is *required* to emit at the lowest priority of `plan.md`.
Its execute prompt is purpose-built:

> You are the consolidation pass. Every other gen task has
> completed. Read the entire `hydrogen/app/` tree. Look for:
> shared-component drift, conflicting design tokens, orphaned
> imports, broken links between pages, navigation paths that no
> longer match collection handles, and any `{{verifier_feedback}}`
> from prior iterations that was deferred. Fix them in place. Do
> not introduce new features.

Verifiers gate `consolidate` like any other task — `tsc`, `build`,
`quality_judge`, plus the consolidate-only `cross_task_consistency`
LLM judge. A `FAIL` rewrites
`consolidate`'s marker back to `[~]` per the standard verifier
contract; the next iteration retries with feedback. If the
consolidate-task budget exhausts without converging, the run
exits with a non-zero status and a clear pointer to which
verifier kept failing.

#### 5.5.5 4.5 Final evaluation (post-loop, advisory)
#### 5.5.4 4.4 Final evaluation (post-loop, advisory)

Step `final_eval` runs after the harness loop exits and writes
`final_eval.json`. **Quality-only**, no cross-comparison with seed
storefronts:

1. Boot the dev server.
2. Playwright smoke flow: home → collection → product → add-to-cart →
   checkout-redirect.
3. Capture screenshots at fixed viewports.
4. LLM-judge the screenshots against `capabilities.json` ("does the
   homepage actually surface the section types listed?"). No seed
   reference, no visual fidelity score.

`final_eval` is **advisory**: a passing build harness loop is the
gating signal; final eval surfaces issues for human review.

### 5.6 Brand safety: fake-brand allowlist

We use an **allowlist** approach because a blocklist of real
brands is never comprehensive enough.

**The allowlist** is shipped at
`packages/shop_arena/src/shop_gen/brands/fake_brands.json` as a
static list of 8 invented brand tokens (each a TitleCase compound
of a marketplace word + a venue word, deliberately distinctive
and distinguishable from real brands):

| Token            | Composition                                       |
| ---------------- | ------------------------------------------------- |
| `Vendarena`      | vendor + arena                                    |
| `AisleArena`     | aisle + arena                                     |
| `Shopliseum`     | shop + coliseum                                   |
| `CartColiseum`   | cart + coliseum                                   |
| `StockyardArena` | stockyard + arena                                 |
| `AgoraDome`      | Greek marketplace (agora) + dome                  |
| `AgoraCage`      | Greek marketplace (agora) + cage                  |
| `AgoraPit`       | Greek marketplace (agora) + pit                   |

The list is checked into the repo and considered API: changes
are versioned. Programmatic per-shop allowlist generation is a
v0.2 follow-up; v0.1 keeps it static.

Alongside the brand tokens the file ships a small **safe-noun**
list (color names, common materials, units, country names) that
the scanner treats as non-brand-shaped capitalized tokens.

**At synthesis time:**

- `synth_identity` chooses `identity.name` deterministically from
  the 8-element allowlist (hash of seeds + descriptor → index).
- All vendor-shaped fields (`product.vendor`, `store.name`,
  collection titles when capability schema requires a brand-ish
  feel) draw from the same allowlist.
- Plain-description fields (product titles, collection titles,
  descriptions, alt-text) follow the prompt rule "no proper nouns
  at all unless from the allowlist".

**At assembly time (final substep of `assemble_data`):**

The orchestrator runs an **allowlist scanner** over every string
field in `data/*.json`:

```
1. Tokenize each string into proper-noun candidates (a deterministic
   regex over capitalized multi-character runs and TitleCase tokens,
   excluding sentence-initial words and the safe-noun list).
2. For each candidate, assert membership in the allowlist OR the
   safe-noun list.
3. Any unmatched candidate ⇒ step failure with the offending field
   path. The orchestrator marks the upstream synthesis step stale
   (e.g. `synth_product_details`) and the user re-runs with
   `--from synth_product_details`.
```

There is **no silent redaction**. A leak is a loud failure that
forces a re-synth.

**At build-loop time:**

The `no_brand_leak` verifier (§5.5.3) runs the same scanner over
`hydrogen/app/**`. A leak fails the iteration; the agent retries
with `{{verifier_feedback}}` instructing it to use only allowlist
brands (with the 8-element allowlist embedded in the feedback).

**Why allowlist over blocklist (recap):**

- A blocklist is by construction incomplete (millions of real
  brands; the seed domains capture only the few we explored).
- An allowlist is exhaustive *for our scope*: we control every
  brand-shaped token by construction.
- False positives (e.g. an English word that happens to look
  brand-shaped) are absorbed by the safe-noun list; we accept
  that the safe-noun list will grow.

**Current status (v0.1.x):**

The **assemble-time scanner is currently disabled** in
`AssembleDataStep` — the safe-noun absorption strategy did not scale.
The tokenizer is intentionally simple (`[A-Z][A-Za-z]+`), and
Title-Cased English plurals dominate legitimate storefront
navigation: collection menus produce strings like "Card Readers",
"Pin Pads", "Receipt Printers", "Barcode Scanners", "Cash
Drawers", "Tablet Stands", "Power Supplies", "Cleaning Supplies".
Each non-sentence-initial plural is brand-shaped under the regex,
and growing `safe_nouns` to cover every common English noun is an
unbounded whack-a-mole that defeats the purpose of an allowlist
("exhaustive for our scope").

The **build-loop `no_brand_leak` verifier is also currently
disabled** in `default_verifiers_factory` — the same allowlist
tokenizer (`[A-Z][A-Za-z]+`) flags React / Hydrogen / TS identifiers
that the template legitimately imports (`Route`, `LoaderArgs`,
`Money`, `CartForm`, …), generating thousands of false positives the
agent cannot fix without breaking the build. The synthesis prompts and
AGENTS.md continue to instruct the LLM not to mention real brands, but
neither `data/*.json` nor `hydrogen/app/**` is post-validated.

The helpers (`scan_for_brand_leaks`, `BrandLeakError`,
`_walk_strings`, `_step_for_field_path`) remain in
`shop_gen.data_synth.assemble` and are unit-tested, so a v0.2
tokenizer (e.g. dictionary-aware: skip tokens whose lowercase form
is in a common-English dictionary; flag only TitleCase compounds
and ALL-CAPS abbreviations) can re-enable the scrub by restoring
the call site in `AssembleDataStep.run` without re-deriving the
field-path → upstream-step mapping or the rewind contract.

### 5.7 Step DAG + resume model

The pipeline is a small DAG of steps. The orchestrator does three
things, in order:

1. **Build the DAG** for the current run (config-aware: e.g. multi-
   seed adds Phase 1 steps; single-seed skips them).
2. **Compute step staleness.** A step is *stale* if (a) its declared
   outputs are missing, (b) any declared input changed (content
   hash), or (c) any upstream step is stale or about to re-run.
3. **Run stale steps in topological order**, persisting state to
   `<out_dir>/.shop_gen/state.json` after each step.

#### 5.7.1 Step contract

Every step has:

```python
class Step(Protocol):
    id: str                     # "synth_collections"
    phase: str                  # "data_synth"
    inputs: list[InputRef]      # files or upstream step ids
    outputs: list[Path]         # files this step writes
    depends_on: list[str]       # step ids
    def run(ctx: StepContext) -> None: ...
```

Steps are idempotent (running twice with the same inputs produces
identical outputs); the runner enforces this by hashing inputs +
the step's `version` int into a fingerprint stored in `state.json`.

#### 5.7.2 The full DAG (v0.1)

```
                                     [phase 1: manual_merge — only when N>1]
                                     ┌───────────────────────────────────┐
seeds[]  ──►  prefetch_summaries     │ merge_capabilities                │
                                     │   ▼                               │
                                     │ merge_manual_prose                │
                                     │   ▼                               │
                                     │ compute_merge_stats               │
                                     │   ▼                               │
                                     │ write_merge_manifest              │
                                     └─────────────┬─────────────────────┘
                                                   │
                                                   ▼
                                     [phase 2: data_synth]
                                     ┌───────────────────────────────────┐
                                     │ synth_identity                    │
                                     │   ├──► synth_store                │
                                     │   ├──► synth_collections          │
                                     │   │       ├──► synth_navigation   │
                                     │   │       └──► synth_product_skeletons │
                                     │   │              ├──► synth_product_details (per-collection) │
                                     │   │              │       ├──► synth_alt_text  │
                                     │   │              │       └──► gen_images       │
                                     │   ├──► synth_pages                │
                                     │   └──► synth_policies             │
                                     │                                   │
                                     │                          assemble_data         │
                                     │                          (depends: ALL above)  │
                                     └─────────────┬─────────────────────┘
                                                   │
                                                   ▼
                                     [phase 3: data_validation]
                                     ┌───────────────────────────────────┐
                                     │ validate_schema                   │
                                     │   ▼                               │
                                     │ validate_hosting                  │
                                     └─────────────┬─────────────────────┘
                                                   │
                                                   ▼
                                     [phase 4: build]
                                     ┌───────────────────────────────────┐
                                     │ clone_template                    │
                                     │   ▼                               │
                                     │ write_env_file                    │
                                     │   ▼                               │
                                     │ start_sidecar (lifecycle for loop)│
                                     │   ▼                               │
                                     │ run_build_harness_loop            │
                                     │   (executes plan tasks            │
                                     │    gen_theme … visual_polish      │
                                     │    via run_plan_exec_loop;        │
                                     │    selective re-run of these      │
                                     │    is handled by harness resume)  │
                                     └─────────────┬─────────────────────┘
                                                   │
                                                   ▼
                                     [phase 5: final_eval]
                                     ┌───────────────────────────────────┐
                                     │ final_eval                        │
                                     └───────────────────────────────────┘
```

#### 5.7.3 Build-loop sub-step granularity

The user wants flexibility to "regenerate just the homepage"
without re-running everything else. Two layers exist:

- **Above the harness:** `run_build_harness_loop` is one step in
  the DAG. Re-running it with the same inputs is a no-op (the
  harness resume protocol —
  [harness/resume.md](../harness/resume.md) — resumes the prior
  run dir).
- **Inside the harness:** the planner produces tasks like
  `gen_homepage`. To re-run *just* `gen_homepage`, the orchestrator
  **appends a new redo task** to `plan.md` rather than rewriting
  the original `[x]`. Concretely, `shop-gen --only gen_homepage`
  on a completed build dir:

  1. Reads `<out_dir>/runs/build/plan.md`.
  2. Computes a fresh task id `gen_homepage_redo_<N>` (where
     `<N>` is the count of existing redo siblings + 1).
  3. Appends the new task as PENDING with priority 1 (after the
     mandatory `consolidate`) and a brief that points back to
     `gen_homepage` plus an optional human-supplied reason.
  4. Re-invokes the harness loop with `force_resume=True`. The
     harness picks the new PENDING task and runs.

  Original `[x]` markers are never touched. This:

  - preserves attribution (every iteration's work is captured in
    its own `iters/exec-NNNN/` directory);
  - obeys the existing harness state-machine invariant
    (`[x]` is terminal; ids never resurrect);
  - composes naturally with verifier dispatch (a redo task fails
    its verifiers ⇒ `[x]` → `[~]` and the next iteration retries,
    just like any other task);
  - chains with `consolidate`: the redo's verifier failures can
    be picked up by a subsequent `consolidate_redo_<N>` if the
    fix bleeds into other tasks.

This means the user's mental model is uniform: every step name
(`synth_identity`, `synth_collections`, `gen_homepage`, …) is
addressable from one CLI; the orchestrator hides whether the
step lives in Python or in `plan.md`.

#### 5.7.4 Dependency-aware re-run

Two flags govern re-runs:

- **`--from <step>`** — set `<step>` and all its downstream
  descendants to STALE. Run all stale steps in topological order.
  This is the "I changed my mind about identity, redo everything
  downstream" flag.
- **`--only <step>`** — run *just* `<step>` (whether stale or
  not). Downstream descendants are marked STALE on disk but **not
  run automatically** — the next plain `shop-gen` invocation
  picks them up. This is the "I want to iterate on this one step
  in isolation" flag, plus an implicit "but warn me about
  downstream consequences."

Plus passive controls:

- **`--status`** — print a step status table (id, phase, status,
  fingerprint, ts). Read-only.
- **`--list-steps`** — print every step id grouped by phase.
- **(default, no flag)** — run every stale step. Idempotent.

Dependency-aware staleness is computed by:

1. Hash each input (file content for files, fingerprint for
   upstream-step refs).
2. Compare against the recorded fingerprint in `state.json`.
3. Mismatch ⇒ STALE; cascade to all downstream descendants.

Output staleness has the same effect: deleting `data/products.json`
makes `assemble_data` STALE; deleting `<out_dir>/hydrogen/` makes
`run_build_harness_loop` STALE.

### 5.8 CLI surface

```bash
# default: run every stale step. idempotent.
shop-gen <seed_dir>... --out-dir outputs/shops/<name>

# step-targeted re-runs
shop-gen --from <step>            # re-run <step> + downstream stale
shop-gen --only <step>            # re-run <step> alone; mark downstream stale
shop-gen --status                 # print step status table
shop-gen --list-steps             # print all step ids

# scale + behavior knobs
shop-gen ... --collections 10 --products-per-collection 200 --images-per-product 2
shop-gen ... --image-backend placeholder|ai|none
shop-gen ... --runtime pi|claude_code --model <id>
shop-gen ... --max-iters 30
```

That's the entire surface. No `--merge-only`, no `--synth-only`,
no `--build-only`, no `--force-<phase>`. Every "skip / re-run /
redo" workflow is `--from` or `--only` against a step id.

### 5.9 Module layout (informative)

```
packages/shop_arena/src/shop_gen/
├── __init__.py
├── _version.py
├── cli.py                       # argparse + dispatch
├── pipeline.py                  # Step registry + orchestrator
├── config.py                    # ShopGenConfig + ShopGenResult (pydantic)
├── steps/
│   ├── __init__.py
│   ├── base.py                  # Step protocol + StepContext + state.json
│   └── runner.py                # DAG resolve, stale detection, topo run
├── manual_merge/                # Phase 1 steps
│   ├── __init__.py
│   ├── capabilities.py
│   ├── prose.py
│   ├── stats.py
│   ├── manifest.py
│   └── prompts/
├── data_synth/                  # Phase 2 steps
│   ├── __init__.py
│   ├── identity.py
│   ├── store.py
│   ├── collections.py
│   ├── navigation.py
│   ├── pages.py
│   ├── policies.py
│   ├── skeletons.py
│   ├── details.py
│   ├── alt_text.py
│   ├── images.py                # ImageBackend protocol + placeholder/ai/none
│   ├── assemble.py              # final write + allowlist scrub
│   ├── schema.py                # pydantic mirrors of shop_backend §8.1
│   └── prompts/
├── brands/
│   ├── __init__.py
│   ├── fake_brands.json
│   └── allowlist.py             # scanner used by assemble + no_brand_leak verifier
├── data_validation/             # Phase 3 steps
│   ├── __init__.py
│   ├── schema_check.py
│   └── hosting_check.py
├── build/                       # Phase 4 steps
│   ├── __init__.py
│   ├── env.py                   # template clone + .env writer
│   ├── sidecar.py               # shop-backend lifecycle
│   ├── loop.py                  # invokes run_plan_exec_loop
│   ├── verifiers/               # caller-owned verifier implementations
│   │   ├── __init__.py
│   │   ├── tsc.py
│   │   ├── build.py
│   │   ├── data_in_use.py
│   │   ├── nav_coverage.py
│   │   ├── no_brand_leak.py
│   │   └── quality_judge.py
│   └── prompts/
│       ├── agents.md
│       ├── planner.md
│       └── execute.md           # contains {{verifier_feedback}} slot
├── final_eval/                  # Phase 5 step
│   ├── __init__.py
│   ├── playwright_smoke.py
│   └── prompts/
└── templates/
    └── hydrogen/                # vendored Hydrogen template
```

---

## 6. Alternatives

1. **Blocklist instead of allowlist for brand safety.** Simpler to
   author. Rejected: incomplete by construction (any real brand not
   in the seed domains slips through), and the user explicitly chose
   allowlist.

2. **One mega-loop for data + build.** One harness loop spans data
   synth + build, with verifiers across both. Rejected for v0.1: data
   synth is fixed-stage and not naturally task-list shaped; forcing
   it into plan/exec adds prompts and non-determinism for no win.

3. **Single CLI flag per phase (`--force-phase-X`).** Rejected: too
   coarse — "regenerate just the homepage" requires sub-phase
   targeting. Step-name addressing handles all coarseness levels with
   one flag (`--from gen_homepage` re-runs from `gen_homepage`
   onward; `--from data_synth_phase` would just be `--from
   synth_identity`).

4. **Fully implement verifiers inside `shop_gen` without the harness
   extension.** Wrap `run_plan_exec_loop` and inject verifier dispatch
   externally. Rejected: duplicates plan-parsing and state-machine
   logic in `shop_gen`. The user's instruction is explicit:
   harness applies, caller owns implementations.

5. **Embed visual fidelity comparisons against the seed storefront.**
   Rejected per user feedback: `final_eval` and the build-time
   `quality_judge` verifier are quality-only, no cross-compare.

6. **Use open sourced Hydrogen Skeleton template instead of the
   playground template.** Cleaner, officially maintained. Deferred:
   user instruction in this round is to vendor the playground
   template; we can swap by replacing the contents of
   `src/shop_gen/templates/hydrogen/`.

---

## 7. Open Questions / Tensions Worth Flagging

1. **Allowlist size and curation.** 8 fake brands is enough for
   v0.1 (a single shop only uses 1–3 vendors typically), but as
   we generate more shops the allowlist starts looking like a
   fixed brand universe. Programmatic per-shop allowlist
   generation (deterministically from `seeds + identity.descriptor`)
   is on the v0.2 roadmap. Confirmed for v0.1: keep static.

2. **Verifier-injected re-plans.** When `quality_judge` fails on
   `gen_homepage`, the harness re-opens *only* that task. The
   real fix is sometimes "redo navigation, then redo homepage".
   v0.1 of the verifier extension does not let verifiers re-open
   other tasks. **Resolved:** acceptable for v0.1; the mandatory
   `consolidate` task (§5.5.4) and the user-driven
   `--only gen_<task>` redo append are the v0.1 escape hatches.

3. **Catalog scalability.** v0.1 ships at 200 products / 400
   images; the steps and CLI knobs accept higher numbers but
   v0.1 has not validated at scale (per-collection parallel
   naming, paginated assembly, sharded image generation are all
   v0.2 work). Going above ~500 products in v0.1 will likely
   blow LLM context limits in `synth_product_skeletons`.

---

## 8. Milestones (informative)

- **M0 — Harness verifier extension.** Land
  [`harness/verifiers.md`](../harness/verifiers.md) v0.1.
  Required before M5. No `harness.resume` amendment needed —
  the build-loop redo flow uses task-append (§5.7.3) and stays
  inside existing harness invariants.
- **M1 — Step DAG runner.** Generic step registry, staleness model,
  state.json, CLI dispatch.
- **M2 — Phase 1 (manual merge).** Per-area capability merge + prose
  merge. Deterministic-and-LLM-tiebreak. Tests with fixtures.
- **M3 — Phase 2 (data synthesis).** All steps including
  `synth_identity` from allowlist, parallel per-collection product
  details, alt-text, placeholder image backend. Pydantic-validated.
- **M4 — Phase 3 (data validation).** schema_check + hosting_check
  against a real `shop_backend` instance.
- **M5 — Phase 4 (build harness loop).** Env setup, sidecar, prompts,
  caller-owned verifier set. Replay-runtime cassette e2e in CI.
- **M6 — Phase 5 (final eval).** Playwright smoke + LLM quality
  judge. Advisory.
- **M7 — v0.1.0.** Docs, CLI surface stable, multi-seed e2e against
  recorded fixtures.
- **M8 (post-v0.1) — Image generation.** Pluggable replacement for
  the placeholder generator. See [`image_generation.md`](image_generation.md).

---

## 9. Appendix

### 9.1 Assumptions (carried forward)

- Each seed Shop Manual conforms to the v0.1 published contract from
  `shop_explore.md` §5.4.
- `packages/shop_backend` has a stable CLI (`shop-backend <data-dir>
  [port]`) and library API. This spec depends on the v0.1 dataset
  contract.
- `packages/harness` accepts the additive verifier extension
  (separate spec) before `shop_gen` ships.
- The vendored Hydrogen template at
  `packages/shop_arena/src/shop_gen/templates/hydrogen/` works
  against `shop_backend`'s GraphQL surface as-is, modulo `.env`
  rewriting and minor binding tweaks the build loop performs.
- Brand-safety via fake-brand allowlist is sufficient for v0.1;
  truly adversarial seeds are out of scope.
- Placeholder SVG images are good enough for the build loop to
  succeed and for downstream `shop_guru` to author dataset tasks.

### 9.2 Per-area capability merge rules (M2 detail)

| Area / Field                | Merge rule                                                              |
| --------------------------- | ----------------------------------------------------------------------- |
| `shop.currency`             | Majority; ties → first seed.                                            |
| `shop.country`              | Majority; ties → first seed.                                            |
| `shop.descriptor`           | LLM merge; brand-free; consistent with merged tone.                     |
| `shop.tone[]`               | Union, dedup, capped at 3.                                              |
| `*.has_*` booleans          | Union (any true → true).                                                |
| `*.<list>` (filters, sort)  | Union, dedup, preserve any seed's relative order for the prefix.        |
| `*.layout` / `*.style` enums | Majority; ties → LLM picks the most consistent with `descriptor`.       |
| `homepage.section_types`    | Union, capped at `max(seed.section_count)` to avoid sprawl.             |
| `nav_depth`                 | Max.                                                                    |

### 9.3 Reference materials

- `packages/shop_arena/src/shop_gen/templates/hydrogen/` — vendored
  Hydrogen template (this round).
- [`shop_backend/storefront_api.md`](../shop_backend/storefront_api.md)
  §8.1 — dataset contract.
- [`shop_arena/shop_explore.md`](shop_explore.md) §5.4–5.6 — input
  bundle shape.
- [`harness/plan_exec_loop.md`](../harness/plan_exec_loop.md) — plan
  + exec loop.
- [`harness/verifiers.md`](../harness/verifiers.md) — additive
  verifier extension this pipeline depends on.
- [`harness/seed_immutability.md`](../harness/seed_immutability.md)
  — why the manual is seeded immutably and the hydrogen tree is not.
- [`harness/resume.md`](../harness/resume.md) — build-loop resume
  semantics (no amendment required: the redo flow appends new tasks).
