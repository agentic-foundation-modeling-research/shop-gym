Index of ShopGym specifications. Organized by category.

Status labels were last refreshed against the codebase on 2026-05-29.
Specs describe intent and contracts; the code remains the source of truth
for shipped behavior.

## Cross-cutting

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [harness/plan_exec_loop.md](harness/plan_exec_loop.md) | `packages/harness` | Reusable plan + exec loop harness, runtime-agnostic. **Status:** Implemented base spec; shipped extensions are tracked in the sibling harness specs below. |
| [harness/seed_immutability.md](harness/seed_immutability.md) | `packages/harness/src/harness/seed.py` | Deterministic post-iteration check that aborts a run on any mutation, deletion, or extension of the seeded subtree under `run_dir/artifact/`. **Status:** Implemented in `harness` 0.2.0. |
| [harness/resume.md](harness/resume.md) | `packages/harness` + `packages/shop_arena/src/shop_arena/explore` | Optional in-place resume of a partial `run_plan_exec_loop` invocation: skip the planner if its trajectory is on disk, continue executor iterations against existing `[x]` markers, quarantine partial iter dirs, and expose `shop-explore --force-resume`. **Status:** Implemented. |
| [harness/verifiers.md](harness/verifiers.md) | `packages/harness` | Additive, opt-in verifier dispatch hook for `run_plan_exec_loop`: caller-owned `Verifier` implementations are run after each executor iteration, gate `[x]` marks on FAIL, and feed `{{verifier_feedback}}` into the next iteration's prompt. **Status:** Implemented in `harness` 0.3.0. |
| [harness/protocol_violation_recovery.md](harness/protocol_violation_recovery.md) | `packages/harness/src/harness/loop.py` | Convert executor-phase protocol violations from terminal failures into per-task BLOCKED-and-continue: restore `plan.md`, force-block the violating task, skip it for the rest of the attempt, continue the loop. **Status:** Implemented for executor iterations; planner violations remain terminal. |

## ShopArena

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [shop_arena/shop_explore.md](shop_arena/shop_explore.md) | `packages/shop_arena/src/shop_arena/explore` | Storefront exploration: produces an anonymized Shop Manual (manual.md + capabilities.json + stats.json + evidence) per storefront. Harness-driven; uses the playwright skill. **Status:** v0.1.0 released; real-LLM synthesis and additional live-runtime cassettes remain follow-ups. |
| [shop_arena/shop_gen.md](shop_arena/shop_gen.md) | `packages/shop_arena/src/shop_arena/gen` + `packages/harness/src/harness/plan` | SandboxShop generation: turns one or more anonymized Shop Manuals into a hostable SandboxShop (data + Hydrogen app), validated end-to-end by hosting with `shop_backend` and built via a verifier-gated harness loop. v0.2 of the spec also folds in the orchestration redesign (uniform `Node` DAG, filesystem-derived completion, per-item output granularity, `plan.json` as harness source of truth, force-rerun via `clean() + downstream walk`). **Status:** v0.1.0 shipping on the legacy `Step` design; manual split and visual verifier code landed; v2 redesign (M9–M13) pending. |
| [shop_arena/react_vite_ssr_template.md](shop_arena/react_vite_ssr_template.md) | `packages/shop_arena/src/shop_arena/gen/templates/react-vite` + `packages/shop_arena/src/shop_arena/gen` | Verified, minimal React + Vite + React Router SSR storefront template with a dummy SandboxShop fixture, direct `shop_backend` wiring, Hydrogen-like serving, and scoped `shop_gen` template selection / hosting changes so generation starts from a working baseline without inheriting a finished theme. **Status:** Implemented; reusable baseline smoke command remains a follow-up. |
| [shop_arena/style_library.md](shop_arena/style_library.md) | `packages/shop_arena/src/shop_arena/gen/style_library` | Curated catalog of style guides — markdown design-system documents with YAML frontmatter, compiled once per theme from source + live demo, and consumed by `shop_arena.gen` as optional render-phase context to steer visual treatment of generated Hydrogen storefronts. **Status:** Draft (proposed). |
| [shop_arena/visual_verifier.md](shop_arena/visual_verifier.md) | `packages/shop_arena/src/shop_arena/gen/build/verifiers` + `packages/shop_arena/src/shop_arena/gen/final_eval` | `visual_judge` verifier (per-task playwright-driven render judging against `capabilities.json`) + per-task retry budget, configurable LLM-judge set, and `final_eval` visual sweep with page-bucket fan-out. **Status:** Implemented. |
| [shop_arena/manual_split.md](shop_arena/manual_split.md) | `packages/shop_arena/src/shop_arena/gen/manual_merge` + `packages/shop_arena/src/shop_arena/gen/build/prompts` | Adds `split_manual_parts` step to slice the merged manual into six per-area sub-manuals; refreshes the build planner / executor prompts to read sub-manuals; retires the `consolidate` task in favor of a renamed `visual_fix`. **Status:** Implemented. |
| [shop_arena/doctor.md](shop_arena/doctor.md) | `packages/shop_arena/src/shop_arena/doctor` | Local diagnostic CLI for validating Playwright and the workspace-pinned `pi-playwright` browser skill before live browser workflows. **Status:** Implemented. |
| [shop_arena/env_eval.md](shop_arena/env_eval.md) | `packages/shop_arena/src/shop_arena/env_eval` | EnvEval: per-shop environment-quality measurement for RL training/eval. Single URL in; samples 5 canonical pages (homepage / collection / PDP / policy / cart_and_search) via browsergym; emits raw structural metrics across observation (axtree stats + LLM screenshot rubric), action (HighLevelActionSet vocabulary + EnvEval role/action/choice target counts), and transition (hybrid href-BFS + fixed-rule stateful graph) layers; ships `shop-env-eval run` and `shop-env-eval visualize` with run-directory artifact reuse. **Status:** v0.1.2. |

## ShopBackend

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [shop_backend/storefront_api.md](shop_backend/storefront_api.md) | `packages/shop_backend` | Local graphql-yoga server resolving against a SandboxShop dataset (synthesized JSON). Read-mostly Storefront-API surface (Shop, Product, Collection, Menu, Page, Blog, Search, PredictiveSearch, Localization, Metafields, Inventory) plus cart lifecycle mutations, optional file-backed cart persistence, `@inContext` validation, image serving, and `/health`. **Status:** Implemented; v0.2 additions are in code. |


## ShopGuru

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [shop_guru/dataset_generation.md](shop_guru/dataset_generation.md) | `packages/shop_guru` | Deterministic benchmark-task generation from SandboxShop data across seven skills, post-generation validation, and AgentLab/BrowserGym evaluation drivers with aggregate scoring. **Status:** Implemented; this spec captures the existing contract. |
