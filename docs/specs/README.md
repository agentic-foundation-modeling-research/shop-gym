Index of ShopGym specifications. Organized by category.

## Cross-cutting

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [harness/plan_exec_loop.md](harness/plan_exec_loop.md) | `packages/harness` | Reusable plan + exec loop harness, runtime-agnostic. |
| [harness/seed_immutability.md](harness/seed_immutability.md) | `packages/harness/src/harness/seed.py` | Deterministic post-iteration check that aborts a run on any mutation, deletion, or extension of the seeded subtree under `run_dir/artifact/`. **Status:** Implemented in `harness` 0.2.0. |
| [harness/resume.md](harness/resume.md) | `packages/harness` | Optional in-place resume of a partial `run_plan_exec_loop` invocation: skip the planner if its trajectory is on disk, continue executor iterations against existing `[x]` markers, quarantine partial iter dirs. **Status:** Draft (proposed). |
| [harness/verifiers.md](harness/verifiers.md) | `packages/harness` | Additive, opt-in verifier dispatch hook for `run_plan_exec_loop`: caller-owned `Verifier` implementations are run after each executor iteration, gate `[x]` marks on FAIL, and feed `{{verifier_feedback}}` into the next iteration's prompt. **Status:** Implemented in `harness` 0.3.0. |
| [harness/protocol_violation_recovery.md](harness/protocol_violation_recovery.md) | `packages/harness/src/harness/loop.py` | Convert executor-phase protocol violations from terminal failures into per-task BLOCKED-and-continue: restore `plan.md`, force-block the violating task, skip it for the rest of the attempt, continue the loop. **Status:** Proposed. |

## ShopArena

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [shop_arena/shop_explore.md](shop_arena/shop_explore.md) | `packages/shop_arena/src/shop_explore` | Storefront exploration: produces an anonymized Shop Manual (manual.md + capabilities.json + stats.json + evidence) per storefront. Harness-driven; uses the playwright skill. **Status:** v0.1 in progress (M1–M3 + M5 docs landed; M4 live-runtime smoke pending). |
| [shop_arena/shop_gen.md](shop_arena/shop_gen.md) | `packages/shop_arena/src/shop_gen` + `packages/harness/src/harness/plan` | SandboxShop generation: turns one or more anonymized Shop Manuals into a hostable SandboxShop (data + Hydrogen app), validated end-to-end by hosting with `shop_backend` and built via a verifier-gated harness loop. v0.2 of the spec also folds in the orchestration redesign (uniform `Node` DAG, filesystem-derived completion, per-item output granularity, `plan.json` as harness source of truth, force-rerun via `clean() + downstream walk`). **Status:** v0.1.0 — M0–M6 landed on the legacy `Step` design; v2 redesign (M9–M13) pending. |
| [shop_arena/style_library.md](shop_arena/style_library.md) | `packages/shop_arena/src/shop_gen/style_library` | Curated catalog of style guides — markdown design-system documents with YAML frontmatter, compiled once per Shopify theme from source + live demo, and consumed by `shop_gen` as optional render-phase context to steer visual treatment of generated Hydrogen storefronts. **Status:** Draft (proposed). |
| [shop_arena/visual_verifier.md](shop_arena/visual_verifier.md) | `packages/shop_arena/src/shop_gen/build/verifiers` + `packages/shop_arena/src/shop_gen/final_eval` | `visual_judge` verifier (per-task playwright-driven render judging against `capabilities.json`) + per-task retry budget, configurable LLM-judge set, and `final_eval` visual sweep with page-bucket fan-out. **Status:** v0.1 — M1–M6 landed; release tasks pending. |
| [shop_arena/shop_probe.md](shop_arena/shop_probe.md) | `packages/shop_arena/src/shop_probe` | Structural-fidelity measurement instrument framed as MDP fidelity (a website is an MDP, measure the MDP). Three families — `observation`, `action`, `transition` — keyed on canonical page types (`homepage`, `collection`, `product`, `search`, `cart`), with observation/action measured per modality (`a11y`, `screenshot`). **Status:** v1.0 — Proposed. |
| [shop_arena/manual_split.md](shop_arena/manual_split.md) | `packages/shop_arena/src/shop_gen/manual_merge` + `packages/shop_arena/src/shop_gen/build/prompts` | Adds `split_manual_parts` step to slice the merged manual into six per-area sub-manuals; refreshes the build planner / executor prompts to read sub-manuals; retires the `consolidate` task in favor of a renamed `visual_fix`. **Status:** Proposed. |

## ShopBackend

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [shop_backend/storefront_api.md](shop_backend/storefront_api.md) | `packages/shop_backend` | Local graphql-yoga server resolving against a SandboxShop dataset (synthesized JSON). Read-mostly Storefront-API surface (Shop, Product, Collection, Menu, Page, Search, PredictiveSearch, Localization) plus an in-memory cart with the standard `cartCreate` / `cartLines*` / `cartDiscountCodesUpdate` mutations; `/health` exposes the loaded store. **Status:** Proposed. |


## ShopGuru

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
|           |           |             |
