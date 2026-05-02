# ShopGen (`packages/shop_arena/src/shop_arena/gen`)

Status: **Spec** · Version: **0.2** (incorporates the v2 redesign of the orchestration layer — formerly tracked separately as `shop_gen_v2.md`, now archived under `docs/internal/archive/specs/`)
Owners: ShopArena

> A configurable pipeline that turns one or more anonymized **Shop
> Manuals** (from `shop_arena.explore`) into a complete, hostable
> **SandboxShop**: a synthesized dataset *and* a generated Hydrogen
> storefront, validated end-to-end by hosting the data with
> `shop_backend`.

---

## 1. Overview

`shop_arena.gen` is the second half of ShopArena. Given the published Shop
Manual bundle for one or more seed storefronts, it produces:

1. A **SandboxShop dataset** (`data/`) — JSON files matching the
   `shop_backend` v0.1 contract (see
   [shop_backend/storefront_api.md §8.1](../shop_backend/storefront_api.md)).
2. A **SandboxShop site** (`hydrogen/`) — a generated Hydrogen app
   that talks to a `shop_backend` instance hosting the dataset.

Four design choices shape the module:

- **Manual-driven, not extraction-driven.** All synthesis reads from
  the public `manual.md` + `capabilities.json` + `stats.json` triple
  produced by `shop_arena.explore`. No live storefront access, no BigQuery,
  no scraping.
- **Brand-safe by allowlist.** Generated catalogs draw all
  brand-shaped tokens (store name, vendors) from a small curated
  list of made-up fake brands. Product / collection titles are plain
  descriptive English ("white sport t-shirt", not "Comfrt Cloud
  Tee"). A deterministic post-pass scanner enforces the allowlist
  rather than blocking a (necessarily incomplete) blocklist of real
  brands. See §5.6.
- **Filesystem-derived DAG with force-only re-runs.** The pipeline is
  a uniform DAG of named **nodes** (`merge_capabilities`,
  `synth_collections`, `gen_homepage`, …) with explicit dependencies.
  A node is *done* iff every path in `node.output_paths()` exists on
  disk — the filesystem is the single source of truth, no
  `state.json`, no fingerprint cascade. The CLI exposes one `run`
  command plus `--force <node-id>...`; force cleans the named nodes
  and their transitive downstream, then lets missing outputs drive
  re-execution. See §5.7.
- **Harness-driven build, with caller-owned verifiers.** The
  website-build phase is one `harness.run_plan_exec_loop` invocation
  that gates each task on a caller-owned **verifier set** (rule +
  LLM). The harness extension that powers this lives in a separate
  spec — [`harness/verifiers.md`](../harness/verifiers.md) — and
  must land before `shop_arena.gen` ships. `shop_arena.gen` owns every
  verifier *implementation*; the harness only dispatches them.

`shop_arena.gen` is the first caller of both `shop_backend` (as a hosting
sidecar) and the harness verifier extension.

---

## 2. Terminology

- **Seed Shop Manual** — the published bundle ShopExplore writes
  under `outputs/shop_manuals/<domain>/<run_id>/artifact/`
  (manual.md, capabilities.json, stats.json, manifest.json,
  prefetch/). One or more are inputs to `shop_arena.gen`.
- **Composite Manual** — the merged manual produced by Phase 1 when
  `len(seeds) > 1`. Same shape as a single Shop Manual.
- **SandboxShop dataset** — JSON files under `<out_dir>/data/`.
  Authoritative shape: shop_backend §8.1.
- **SandboxShop site** — Hydrogen app under `<out_dir>/hydrogen/`,
  cloned from the vendored template at
  `packages/shop_arena/src/shop_arena/gen/templates/hydrogen/`.
- **Fake-brand allowlist** — a small static list of 8 invented
  brand tokens (Vendarena, AisleArena, Shopliseum, CartColiseum,
  StockyardArena, AgoraDome, AgoraCage, AgoraPit), shipped at
  `packages/shop_arena/src/shop_arena/gen/brands/fake_brands.json`. Every
  brand-shaped string in `data/*.json` must be drawn from this list.
- **Node** — a named, dependency-aware unit of work in the pipeline
  DAG. Has a stable id, a `depends_on` set, an `output_paths` list,
  and an idempotent `run(ctx)`. Replaces the legacy `Step` protocol +
  `InputRef` union.
- **Done** — every path in `node.output_paths()` exists on disk. No
  `state.json`, no `_meta.version` field, no fingerprint. The
  filesystem is the single source of truth.
- **Force** — a CLI flag that names one or more node ids. The runner
  calls `node.clean(ctx)` on each named node and on every transitive
  downstream node, then runs the DAG normally; missing outputs drive
  re-execution.
- **PlanState** — pydantic-validated JSON document at
  `runs/build/plan.json` carrying the harness's task list. Replaces
  the legacy `plan.md` regex parser.
- **Reconciliation** — the resume-time check that compares
  `plan.json` against iter-dir filesystem state; advisory by default,
  escalable via `--force-align`.
- **Hosting sidecar** — a `shop-backend` process started by `shop_arena.gen`
  before the build loop, serving the synthesized dataset on a local
  port for the agent to query and render against.
- **Verifier** — a caller-owned check (rule-based or LLM-as-judge)
  the harness dispatches after each executor iteration. PASS / FAIL /
  ADVISORY. See [harness/verifiers.md](../harness/verifiers.md).

---

## 3. Current Status

**Pipeline (legacy `Step` design — currently shipping in
`packages/shop_arena/src/shop_arena/gen/`):**

- 16 step files across `data_synth/`, `manual_merge/`, `build/`,
  `final_eval/`, plus `steps/{base,runner,state}.py` (~890 LOC)
  defining the `Step` protocol, `StepStateRecord`,
  `compute_fingerprint`, `compute_staleness` (6 staleness triggers),
  the 5-value `StepStatus` enum, and `InputRef = FileInput |
  StepInput`. State persists at `<out_dir>/.shop_gen/state.json`;
  cached intermediates at `<out_dir>/.shop_gen/stage_cache/`.
- `cli.py` (~570 LOC) carries `--from / --only / --to`, `--status`,
  `--list-steps`, plus `_maybe_apply_redo` which imports
  `harness.plan` + `shop_arena.gen.build.redo` to mutate `plan.md` directly
  via the `<base>_redo_<N>` task-append hack.
- `build/loop.py:RunBuildHarnessLoopStep` hardcodes
  `self._force = True`, fully overriding the harness's refusal policy
  for `shop_arena.gen` callers.

**Harness state (legacy):** `plan.md` (regex-parsed `[ ][~][x][!]`
markers), `iters/<id>/trajectory.json` (immutable), `run.json`
(rewritten every iteration), `.harness/seed_manifest.json`.
`recovery.reconstruct(run_dir)` rebuilds `PlanExecLoopResult` from
the filesystem and avoids `run.json`. `_select_next_skipping` uses
an in-memory skip set that does not persist across resumes.
Force-rerunning a single harness task today goes through
`cli.py:_maybe_apply_redo`, which appends `<base>_redo_<N>` to
`plan.md` to bypass the parser's `[x]→[ ]` resurrection rejection.

**Capabilities shipped:** M0–M6 (see §8) landed against the legacy
design. Full e2e (single + multi-seed) generates a hostable
SandboxShop; data validation, build-harness loop with caller-owned
verifiers, and final eval all run.

**Redesign pending (this spec, §5.7+):** collapse the dual state
machines (pipeline `state.json` fingerprint cascade + harness
`plan.md` / `run.json` trio) into one filesystem-derived rule
applied uniformly across the data DAG and the harness loop. See
[`harness/plan_exec_loop.md`](../harness/plan_exec_loop.md) and
[`harness/verifiers.md`](../harness/verifiers.md) for the underlying
contracts.

---

## 4. Desired Status

A self-contained module under `packages/shop_arena/src/shop_arena/gen/`
that, given one or more `shop_manual` directories, produces a
complete, hostable SandboxShop with a passing data validation and a
passing build verifier suite.

### 4.1 I/O contract

**Inputs** (CLI or library):

| Input             | Notes                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------ |
| `seeds`           | One or more paths to `shop_manuals/<domain>/<run_id>/`. ≥ 1 required.                                  |
| `out_dir`         | Defaults to `outputs/shops/<name>/`. Must be empty, non-existent, or a prior `shop_arena.gen` run dir.       |
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
│   ├── images/               # placeholder SVGs (v0.1) or generated images (v0.2)
│   └── cache/                # per-node intermediates; existence == "node done"
│       ├── identity.json
│       ├── store.json
│       ├── collections.json
│       ├── skeletons.json
│       ├── navigation.json
│       ├── pages.json
│       ├── policies.json
│       ├── alt_text.json
│       └── details/<sku>.json     # one file per product (per-item granular resume)
├── hydrogen/                 # PUBLISHED — generated Hydrogen app (cloned from template, then mutated)
├── data_validation.json      # PUBLISHED — schema + hosting check verdict
├── final_eval.json           # PUBLISHED — advisory quality verdict
└── runs/                      # debugging — harness run_dir for the build phase
    └── build/
        ├── plan.json          # PlanState — single source of truth for harness task state
        ├── run.json           # summary-only; not consulted for control flow
        └── iters/<id>/...
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
| SC7 | A re-invocation with no flags is a no-op (every node is `is_complete()` — every output path exists). `--force <node-id>...` cleans the named nodes plus their transitive downstream and re-runs them in topological order. |

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
**nodes** (§5.7); the orchestrator drives the node DAG and is the
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
   pydantic schema `shop_arena.explore` writes.
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
| `synth_store`                | `synth_identity`                     | `data/cache/store.json`             |
| `synth_collections`          | `synth_identity`, merged caps, stats | `data/cache/collections.json`       |
| `synth_navigation`           | `synth_collections`, merged caps     | `data/cache/navigation.json`        |
| `synth_pages`                | `synth_identity`, merged caps        | `data/cache/pages.json`             |
| `synth_policies`             | `synth_identity`                     | `data/cache/policies.json`          |
| `synth_product_skeletons`    | `synth_collections`                  | `data/cache/skeletons.json` (200 titles, handles, prices; one bulk call at v0.1 scale) |
| `synth_product_details`      | `synth_product_skeletons`            | `data/cache/details/<sku>.json` — one file per product (per-item granular resume; collections in parallel, ≤ 10 skeletons per LLM call within a collection) |
| `synth_alt_text`             | `synth_product_details`              | `data/cache/alt_text.json`          |
| `gen_images`                 | `synth_product_details`              | `data/images/<product>_<variant>.svg` — one file per image (placeholder) or `.png` (AI; later) |
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
  `data/cache/details/_failed_<collection>_chunk_<i>_attempt_<n>.txt`
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
`--force assemble_data`. (Auto-retry on hosting failure is a v0.2
follow-up — see §8.)

### 5.5 Phase 4 — Build Harness Loop

**Input:** `data/`, `manual/`, `identity.json`, vendored
template. **Output:** `hydrogen/`.

This phase is one `harness.run_plan_exec_loop` invocation. The
harness owns iteration lifecycle, plan parsing, and telemetry;
`shop_arena.gen` owns prompts, the verifier set, and the sidecar. It also
relies on the additive harness verifier extension —
[`harness/verifiers.md`](../harness/verifiers.md) — which **must
land first**.

#### 5.5.1 4.1 Env setup (pre-loop)

Steps run by the orchestrator before invoking the harness:

| Step              | Action                                                                        |
| ----------------- | ----------------------------------------------------------------------------- |
| `clone_template`  | `cp -R packages/shop_arena/src/shop_arena/gen/templates/hydrogen <out_dir>/hydrogen` |
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

**`shop_arena.gen` owns every verifier implementation.** They live under
`packages/shop_arena/src/shop_arena/gen/build/verifiers/` and are passed to
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

`shop_arena.gen` closes the gap with a **mandatory final task** the
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
`packages/shop_arena/src/shop_arena/gen/brands/fake_brands.json` as a
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
   `--force synth_product_details`.
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
`shop_arena.gen.data_synth.assemble` and are unit-tested, so a v0.2
tokenizer (e.g. dictionary-aware: skip tokens whose lowercase form
is in a common-English dictionary; flag only TitleCase compounds
and ALL-CAPS abbreviations) can re-enable the scrub by restoring
the call site in `AssembleDataStep.run` without re-deriving the
field-path → upstream-step mapping or the rewind contract.

### 5.7 Pipeline state — filesystem-derived

The pipeline collapses every "should we re-run X?" question to one
rule: **a node is done iff every path in `node.output_paths()`
exists on disk**. There is no `state.json`, no fingerprint cascade,
no `_meta.version` field, no staleness enum.

#### 5.7.1 The `Node` protocol

Every unit of work — data-synth, manual-merge, build, final-eval —
implements the same protocol:

```python
class Node(Protocol):
    id: str
    depends_on: frozenset[str]

    def applies(self, cfg: PipelineConfig) -> bool: ...
    def output_paths(self, cfg: PipelineConfig) -> list[Path]: ...
    def run(self, ctx: NodeContext) -> None: ...
```

Derived helpers (defined once on a base class):

```python
def is_complete(self, cfg) -> bool:
    return all(p.exists() for p in self.output_paths(cfg))

def clean(self, cfg) -> None:
    for p in self.output_paths(cfg):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
```

The runner is ~30 lines (see Appendix 9.4). All 16 nodes use the
same protocol — there is no separate "build phase is special" path.
Build and final-eval are nodes too: their `output_paths()` returns
`runs/build/artifact/hydrogen/dist/server/index.js` +
`runs/build/plan.json` (build) and `eval/results.json` (final-eval).

The DAG is hardcoded — no dynamic registration based on seed count.
Multi-seed nodes have `applies(cfg) -> len(cfg.seeds) > 1`; they're
present in the registry always but only executed when relevant.

#### 5.7.2 Per-item granular outputs

For nodes whose work is naturally per-item (`synth_product_details`,
`gen_images`), `run()` iterates and skips items whose individual
output exists:

```python
def run(self, ctx):
    skeletons = load_skeletons(ctx.out_dir)
    details_dir = ctx.out_dir / "data/cache/details"
    details_dir.mkdir(parents=True, exist_ok=True)
    for sku in skeletons.skus:
        out = details_dir / f"{sku.id}.json"
        if out.exists():
            continue
        details = ctx.llm.synthesize_details(sku)
        atomic_write_json(out, details)
```

Granular resume drops out of the filesystem rule — no per-item state
file, no manifest. `output_paths()` for these nodes returns the
*directory*, so `clean()` rms the whole tree and full re-run is one
`--force` away.

#### 5.7.3 Schema invalidation via pydantic

Downstream nodes load upstream output through pydantic models:

```python
products = ProductCatalog.model_validate_json(
    (ctx.out_dir / "data/products.json").read_text()
)
```

If the schema has changed in a parse-incompatible way, the load
raises `ValidationError`. The runner catches it, treats the upstream
output as missing, and re-runs the upstream node (which in turn
cascades). No per-step `version` int to maintain.

For semantic-only schema changes (parse-compatible but meaning
shifted), the user runs `--force <node>` explicitly. This is rare
enough not to deserve framework support.

#### 5.7.4 Force semantics

Force is the *only* re-run lever:

1. Topologically sort the DAG.
2. Compute closure: `{named} ∪ {downstream(named)}`.
3. For each node in the closure, call `node.clean(cfg)`.
4. Run the DAG normally; the cleaned nodes are now `is_complete()
   == False` and will execute.

`--force build` rms `runs/build/`. The legacy `force=True`
hardcode in `RunBuildHarnessLoopStep` goes away — the harness's
refusal policy now governs in-place resume of partial harness state,
and pipeline-level force is expressed by deleting the run dir.

#### 5.7.5 The full DAG (v0.1)

```
                                     [phase 1: manual_merge — only when N>1]
                                     ┌─────────────────────────────────┐
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
                                     ┌─────────────────────────────────┐
                                     │ synth_identity                    │
                                     │   ├──► synth_store                │
                                     │   ├──► synth_collections          │
                                     │   │       ├──► synth_navigation   │
                                     │   │       └──► synth_product_skeletons │
                                     │   │              ├──► synth_product_details (per-sku) │
                                     │   │              │       ├──► synth_alt_text  │
                                     │   │              │       └──► gen_images (per-image) │
                                     │   ├──► synth_pages                │
                                     │   └──► synth_policies             │
                                     │                                   │
                                     │                          assemble_data         │
                                     │                          (depends: ALL above)  │
                                     └─────────────┬─────────────────────┘
                                                   │
                                                   ▼
                                     [phase 3: data_validation]
                                     ┌─────────────────────────────────┐
                                     │ validate_schema                   │
                                     │   ▼                               │
                                     │ validate_hosting                  │
                                     └─────────────┬─────────────────────┘
                                                   │
                                                   ▼
                                     [phase 4: build]
                                     ┌─────────────────────────────────┐
                                     │ clone_template                    │
                                     │   ▼                               │
                                     │ write_env_file                    │
                                     │   ▼                               │
                                     │ start_sidecar (loop lifecycle)    │
                                     │   ▼                               │
                                     │ run_build_harness_loop            │
                                     │   (executes plan.json tasks       │
                                     │    gen_theme … visual_polish      │
                                     │    via run_plan_exec_loop)        │
                                     └─────────────┬─────────────────────┘
                                                   │
                                                   ▼
                                     [phase 5: final_eval]
                                     ┌─────────────────────────────────┐
                                     │ final_eval                        │
                                     └─────────────────────────────────┘
```

### 5.8 Harness `plan.json` as single source of truth

The build phase migrates from regex-parsed `plan.md` to a
pydantic-validated `plan.json`. Schema:

```python
class TaskRecord(BaseModel, frozen=True):
    id: str                                    # [a-z0-9_]+
    priority: int                              # 0 = highest
    status: Literal["pending", "in_progress", "done", "blocked"]
    iter_id: int | None = None                 # iter that completed/attempted
    attempts: int = 0                          # persisted; replaces in-mem skip set
    last_error: str | None = None              # if blocked or recently failed
    note: str | None = None                    # planner-supplied free-text trailer

class PlanState(BaseModel, frozen=True):
    schema_version: int = 1
    created_at: str                            # ISO-8601, planner write time
    tasks: list[TaskRecord]
```

Writes are atomic (`tmp + os.replace`). The planner emits the
initial `plan.json` after its single iteration; the executor mutates
it via well-defined state transitions:

- `select_next` → highest-priority `pending|in_progress` task whose
  `attempts < max_attempts` (persistent backoff).
- `mark_in_progress(task_id, iter_id)` → flip to `in_progress`,
  bump `attempts`, set `iter_id`.
- `mark_done(task_id, iter_id)` → flip to `done`.
- `mark_blocked(task_id, reason)` → flip to `blocked`, set
  `last_error`.
- `redo(task_id)` → flip `done|blocked → pending`, reset `iter_id`
  and `attempts`. Used by the `harness redo` CLI.

The legacy `plan.md` regex parser, the `[x]→[ ]` resurrection
rejection, the diff()-driven mutation flow in
`harness.plan.parser`, and the `<base>_redo_<N>` task-append hack
all delete.

`run.json` reverts to summary-only — emitted at the end of every
executor iteration and at end-of-loop, purely for human/CI summary
consumption. `_read_prior_final_status` is replaced by
`PlanState.summarize()`; `recovery.reconstruct(run_dir)` becomes a
thin wrapper around `PlanState.load(run_dir/"plan.json")`.

#### 5.8.1 Force a single harness task

For debugging the build phase, the harness CLI exposes:

```
uv run harness redo --plan runs/build/plan.json gen_theme
```

This mutates `plan.json` to flip `gen_theme` from `done` to
`pending`; the next `run_plan_exec_loop` invocation picks it up via
`select_next`. `--force-align` (CLI flag) escalates: any `done`
whose iter dir is missing flips back to `pending` (the explicit
recovery path for "I deleted iter dirs by hand").

#### 5.8.2 Reconciliation policy

On resume, before the executor loop runs, the harness validates
`plan.json` against the iter dirs. Reconciliation is advisory by
default; mismatches log a warning but the loop proceeds with
`plan.json` as truth:

| `plan.json` says            | Filesystem shows                            | Default action                                 |
| --------------------------- | ------------------------------------------- | ---------------------------------------------- |
| `done`, `iter_id=K`         | `iters/exec-K/trajectory.json` present      | OK                                             |
| `done`, `iter_id=K`         | `iters/exec-K/` missing or no trajectory    | Warn; trust plan.json (treat as done)          |
| `in_progress`, `iter_id=K`  | `iters/exec-K/` missing or no trajectory    | Quarantine partial dir; reset task to pending  |
| `pending`                   | `iters/exec-N/` exists for this task        | Quarantine orphan iter; proceed                |

### 5.9 CLI surface

```bash
# default: run every node whose outputs are missing. idempotent.
uv run shop-gen run <seed>... --out-dir outputs/shops/<name>

# partial rerun: clean named nodes + downstream, then run.
uv run shop-gen run <seed>... --out-dir <dir> --force <node-id>...

# read-only status table.
uv run shop-gen status --out-dir <dir>

# scale + behavior knobs
uv run shop-gen run ... --collections 10 --products-per-collection 20 --images-per-product 2
uv run shop-gen run ... --image-backend placeholder|ai|none
uv run shop-gen run ... --runtime pi|claude_code --model <id>
uv run shop-gen run ... --max-iters 30

# debugging the build phase — force a single harness task
uv run harness redo --plan <out>/runs/build/plan.json <task_id>
```

That's the entire surface. There is no `--from / --only / --to`
slicing, no `--merge-only / --synth-only / --build-only`, no
`_redo_<N>` task-append hack. Every "skip / re-run / redo" workflow
is `--force <node-id>` (pipeline) or `harness redo <task_id>`
(in-loop). Examples:

- `--force synth_collections` — regenerate collections + every
  downstream data-synth + the build + eval.
- `--force gen_images` — regenerate all images + assemble + build + eval.
- `--force build` — wipe `runs/build/` + final eval; run those.

"Redo only this and stop" is `--force X` + `Ctrl+C` after X
completes; the output state is identical.

### 5.10 Module layout (informative)

```
packages/shop_arena/src/shop_arena/gen/
├── __init__.py
├── _version.py
├── cli.py                       # argparse + dispatch (~120 LOC; no _redo_, no --from/--only/--to)
├── pipeline.py                  # Node registry + topo sort
├── config.py                    # ShopGenConfig + ShopGenResult (pydantic)
├── dag/
│   ├── __init__.py
│   ├── node.py                  # Node protocol + NodeContext + base class
│   └── runner.py                # topo sort + force-closure walk
├── manual_merge/                # Phase 1 nodes
│   ├── __init__.py
│   ├── capabilities.py
│   ├── prose.py
│   ├── stats.py
│   ├── manifest.py
│   └── prompts/
├── data_synth/                  # Phase 2 nodes
│   ├── __init__.py
│   ├── identity.py
│   ├── store.py
│   ├── collections.py
│   ├── navigation.py
│   ├── pages.py
│   ├── policies.py
│   ├── skeletons.py
│   ├── details.py               # per-sku iteration; output dir = data/cache/details/
│   ├── alt_text.py
│   ├── images.py                # per-image iteration; ImageBackend protocol
│   ├── assemble.py              # final write + allowlist scrub
│   ├── schema.py                # pydantic mirrors of shop_backend §8.1
│   └── prompts/
├── brands/
│   ├── __init__.py
│   ├── fake_brands.json
│   └── allowlist.py             # scanner used by assemble + no_brand_leak verifier
├── data_validation/             # Phase 3 nodes
│   ├── __init__.py
│   ├── schema_check.py
│   └── hosting_check.py
├── build/                       # Phase 4 nodes (no redo.py)
│   ├── __init__.py
│   ├── env.py                   # template clone + .env writer
│   ├── sidecar.py               # shop-backend lifecycle
│   ├── loop.py                  # invokes run_plan_exec_loop (no force=True hardcode)
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
├── final_eval/                  # Phase 5 node
│   ├── __init__.py
│   ├── playwright_smoke.py
│   └── prompts/
└── templates/
    └── hydrogen/                # vendored Hydrogen template
```

Legacy modules deleted by the v2 migration:
`steps/{base,runner,state}.py` (replaced by `dag/`),
`build/redo.py` (replaced by `harness redo`).

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
   targeting. Node-name addressing handles all coarseness levels with
   one flag (`--force gen_homepage` cleans `gen_homepage` + every
   downstream node and re-runs them; `--force data_synth_phase`
   would just be `--force synth_identity`).

4. **Fully implement verifiers inside `shop_arena.gen` without the harness
   extension.** Wrap `run_plan_exec_loop` and inject verifier dispatch
   externally. Rejected: duplicates plan-parsing and state-machine
   logic in `shop_arena.gen`. The user's instruction is explicit:
   harness applies, caller owns implementations.

5. **Embed visual fidelity comparisons against the seed storefront.**
   Rejected per user feedback: `final_eval` and the build-time
   `quality_judge` verifier are quality-only, no cross-compare.

6. **Use open sourced Hydrogen Skeleton template instead of the
   playground template.** Cleaner, officially maintained. Deferred:
   user instruction in this round is to vendor the playground
   template; we can swap by replacing the contents of
   `src/shop_arena/gen/templates/hydrogen/`.

**Alternatives considered for the v2 orchestration redesign (§5.7–5.9):**

7. **Keep fingerprint cascade, simplify only the harness.** Retain
   `state.json` and the version-stamped fingerprint cascade in the
   pipeline; only migrate `plan.md → plan.json`. Pro: smaller blast
   radius. Con: leaves the dual-state-machine confusion intact,
   doesn't delete the cache layer, doesn't address the `force=True`
   hardcode. Rejected: doesn't deliver the simplification this round
   targets.

8. **Embed `_meta.schema_version` in every output JSON.** Instead of
   relying on pydantic `ValidationError`, every output includes a
   `_meta.schema_version` field; the runner compares it against an
   expected version on load. Pro: explicit, catches parse-compatible
   semantic changes. Con: pollutes outputs, requires maintaining
   version constants per-step, drifts in practice (devs forget to
   bump). Rejected: pydantic-on-load handles 90% of cases and the
   remaining 10% want explicit `--force` anyway.

9. **Single phase per data category (no per-substep granularity).**
   Collapse `data_synth/`'s 11 nodes into one `data` node that runs
   all substeps end-to-end. Pro: minimal LOC. Con: rejected —
   debugging requires inspecting and re-running individual substeps
   (e.g. review collections before generating products). The
   proposal preserves substep granularity through per-substep output
   paths and a uniform `Node` shape.

10. **Keep `plan.md`, add a sidecar `plan.state.json`.** Store
    volatile state (attempts, last_error, iter_id) in a sidecar
    JSON, leave `plan.md` for human-readable task listing. Pro:
    human editability. Con: two sources of truth, sync bugs, doesn't
    kill the regex parser. Rejected: nobody hand-edits `plan.md` in
    practice; `harness status` can render `plan.json` as a table for
    readability.

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
   `consolidate` task (§5.5.4) and `harness redo <task_id>`
   (§5.8.1) are the v0.1 escape hatches.

3. **Catalog scalability.** v0.1 ships at 200 products / 400
   images; the steps and CLI knobs accept higher numbers but
   v0.1 has not validated at scale (per-collection parallel
   naming, paginated assembly, sharded image generation are all
   v0.2 work). Going above ~500 products in v0.1 will likely
   blow LLM context limits in `synth_product_skeletons`.

4. **Hand-edited `plan.md`.** Does anyone actually edit `plan.md`
   today? If no, the v2 migration to `plan.json` loses nothing in
   "human editability". Working assumption for v0.2: no.

5. **`harness redo --all-failed`.** Should `harness redo` accept a
   bulk "retry every `blocked` task" mode? Useful for "rerun after
   fixing a bug" but could be left to `--force build` instead.
   Open.

6. **Per-item outputs and SKU disambiguation.** Per-sku
   `synth_product_details` outputs (`data/cache/details/<sku>.json`)
   assume SKU is unique. If products are ever plural-keyed (variants
   share a SKU), the per-file path needs disambiguation.

7. **Seeds-as-node.** Should the data DAG carry a `seeds.json` node
   at the root capturing the seed set, so `--force seeds`
   invalidates the whole run? Currently seeds are config not output.

---

## 8. Milestones (informative)

**Shipped (against the legacy `Step` design):**

- **M0 — Harness verifier extension.** Landed
  [`harness/verifiers.md`](../harness/verifiers.md) v0.1.
- **M1 — Step DAG runner.** Generic step registry, staleness model,
  `state.json`, CLI dispatch.
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
  the placeholder generator. See
  [`image_generation.md`](image_generation.md).

**Pending (v2 orchestration redesign — §5.7–5.9):**

- **M9 — `Node` protocol + runner skeleton.** Add `shop_arena/gen/dag/
  {node,runner}.py`. Migrate `final_eval` (smallest leaf) to the new
  protocol behind a feature flag; old runner still drives the rest.
  Tests cover `is_complete` / `clean` / force-closure semantics.
- **M10 — Migrate data-synth + manual-merge nodes.** Port all 11
  `data_synth/` steps and 5 `manual_merge/` steps to `Node`. Replace
  `.shop_gen/stage_cache/<x>.json` with `data/cache/<x>.json` output
  paths. Per-product / per-image outputs land here. Delete
  `state.py`, old `runner.py`, old `base.py`, `InputRef`. Tests:
  full e2e single-seed run, partial re-run, force-rerun.
- **M11 — Harness `plan.json` migration.** Add
  `harness/plan/state.py` with `TaskRecord`, `PlanState`, atomic
  save, mutation API. Update planner contract: emit `plan.json`
  (with one release of dual `plan.md` write for migration). Update
  executor: read/write `plan.json` exclusively. Update
  `recovery.reconstruct` to consume `plan.json`. Add `harness redo`
  CLI with `--force-align`. Tests: state transitions, reconciliation
  matrix, persistent `attempts` survives resume.
- **M12 — Build node drops `force=True` hardcode.**
  `RunBuildHarnessLoopNode` reads `runs/build/plan.json` to decide
  `is_complete`; outputs include hydrogen `dist/` + `plan.json` with
  all tasks `done`. `--force build` = `shutil.rmtree(out_dir/
  "runs/build")`. Refusal policy governs ordinary resume. CLI loses
  `_maybe_apply_redo`, `--from`, `--only`, `--to` (→ ~120 LOC).
- **M13 — Cleanup.** Delete `build/redo.py` and `_redo_<N>`
  plan-mutation code. Delete `plan.md` parser/writer once one
  release of dual-write has shipped. Update README walkthroughs.

---

## 9. Appendix

### 9.1 Assumptions (carried forward)

- Each seed Shop Manual conforms to the v0.1 published contract from
  `shop_explore.md` §5.4.
- `packages/shop_backend` has a stable CLI (`shop-backend <data-dir>
  [port]`) and library API. This spec depends on the v0.1 dataset
  contract.
- `packages/harness` accepts the additive verifier extension
  (separate spec) before `shop_arena.gen` ships.
- The vendored Hydrogen template at
  `packages/shop_arena/src/shop_arena/gen/templates/hydrogen/` works
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

- `packages/shop_arena/src/shop_arena/gen/templates/hydrogen/` — vendored
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
  semantics (v2 redesign: harness mutates `plan.json` task records
  in place; §5.8.2 reconciliation governs partial-iter recovery).

### 9.4 Pipeline runner (full code)

```python
def run(cfg: PipelineConfig, force: frozenset[str] = frozenset()) -> None:
    nodes = [n for n in REGISTRY if n.applies(cfg)]
    order = topo_sort(nodes)
    closure = force_closure(force, order)

    for node in order:
        if node.id in closure:
            node.clean(cfg)
        if node.is_complete(cfg):
            log.info("skip %s (complete)", node.id)
            continue
        log.info("run %s", node.id)
        ctx = NodeContext(cfg=cfg, out_dir=cfg.out_dir, llm=cfg.llm)
        node.run(ctx)
```

### 9.5 Example node

```python
class SynthCollectionsNode(Node):
    id = "synth_collections"
    depends_on = frozenset({"synth_identity", "synth_store"})

    def applies(self, cfg): return True

    def output_paths(self, cfg):
        return [cfg.out_dir / "data/cache/collections.json"]

    def run(self, ctx):
        identity = Identity.model_validate_json(
            (ctx.out_dir / "data/cache/identity.json").read_text()
        )
        store = Store.model_validate_json(
            (ctx.out_dir / "data/cache/store.json").read_text()
        )
        collections = ctx.llm.synthesize_collections(identity, store)
        out = ctx.out_dir / "data/cache/collections.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out, collections.model_dump())
```

### 9.6 `plan.json` example

```json
{
  "schema_version": 1,
  "created_at": "2026-04-29T12:00:00Z",
  "tasks": [
    {
      "id": "gen_theme",
      "priority": 0,
      "status": "done",
      "iter_id": 1,
      "attempts": 1
    },
    {
      "id": "gen_navigation",
      "priority": 1,
      "status": "in_progress",
      "iter_id": 2,
      "attempts": 1,
      "note": "redo of gen_navigation after layout review"
    },
    {
      "id": "gen_homepage",
      "priority": 2,
      "status": "pending",
      "attempts": 0
    }
  ]
}
```

### 9.7 LOC comparison (estimate)

| Component | Today (legacy `Step`) | v2 (`Node`) | Delta |
|---|---|---|---|
| `steps/{base,runner,state}.py` | ~890 | ~150 (`dag/`) | -740 |
| `cli.py` | ~570 | ~120 | -450 |
| `pipeline.py` | ~640 | ~200 | -440 |
| 16 step files (avg) | ~95 each | ~40 each | -880 total |
| `build/redo.py` | 237 | 0 | -237 |
| `harness/plan/parser.py` | 209 | ~80 | -130 |
| `harness/plan/state.py` (new) | 0 | ~250 | +250 |
| `build/loop.py` (drift detection out) | 955 | ~700 | -255 |
| **Total** | **~16k** (incl. tests) | **~11k** | **~5k** |
  in place; §5.8.2 reconciliation governs partial-iter recovery).
