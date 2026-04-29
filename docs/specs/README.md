Index of ShopGym specifications. Organized by category.

## Cross-cutting

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
| [harness/plan_exec_loop.md](harness/plan_exec_loop.md) | `packages/harness` | Reusable plan + exec loop harness, runtime-agnostic. | [impl](../impl/plan_exec_loop_implementation.md) |
| [harness/seed_immutability.md](harness/seed_immutability.md) | `packages/harness/src/harness/seed.py` | Deterministic post-iteration check that aborts a run on any mutation, deletion, or extension of the seeded subtree under `run_dir/artifact/`. **Status:** Implemented in `harness` 0.2.0. | — |
| [harness/resume.md](harness/resume.md) | `packages/harness` | Optional in-place resume of a partial `run_plan_exec_loop` invocation: skip the planner if its trajectory is on disk, continue executor iterations against existing `[x]` markers, quarantine partial iter dirs. **Status:** Draft (proposed). | — |
| [harness/verifiers.md](harness/verifiers.md) | `packages/harness` | Additive, opt-in verifier dispatch hook for `run_plan_exec_loop`: caller-owned `Verifier` implementations are run after each executor iteration, gate `[x]` marks on FAIL, and feed `{{verifier_feedback}}` into the next iteration's prompt. **Status:** Implemented in `harness` 0.3.0. | [impl](../impl/verifiers_implementation.md) |

## ShopArena

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
| [shop_arena/shop_explore.md](shop_arena/shop_explore.md) | `packages/shop_arena/src/shop_explore` | Storefront exploration: produces an anonymized Shop Manual (manual.md + capabilities.json + stats.json + evidence) per storefront. Harness-driven; uses the playwright skill. **Status:** v0.1 in progress (M1–M3 + M5 docs landed; M4 live-runtime smoke pending). | [impl](../impl/shop_explore_implementation.md) |
| [shop_arena/shop_gen.md](shop_arena/shop_gen.md) | `packages/shop_arena/src/shop_gen` | SandboxShop generation: turns one or more anonymized Shop Manuals into a hostable SandboxShop (data + Hydrogen app), validated end-to-end by hosting with `shop_backend` and built via a verifier-gated harness loop. **Status:** v0.1.0 — M0–M6 landed; release tasks pending. | [impl](../impl/shop_gen_implementation.md) |
| [shop_arena/style_library.md](shop_arena/style_library.md) | `packages/shop_arena/src/shop_gen/style_library` | Curated catalog of style guides — markdown design-system documents with YAML frontmatter, compiled once per Shopify theme from source + live demo, and consumed by `shop_gen` as optional render-phase context to steer visual treatment of generated Hydrogen storefronts. **Status:** Draft (proposed). | — |
| [shop_arena/visual_verifier.md](shop_arena/visual_verifier.md) | `packages/shop_arena/src/shop_gen/build/verifiers` + `packages/shop_arena/src/shop_gen/final_eval` | `visual_judge` verifier (per-task playwright-driven render judging against `capabilities.json`) + per-task retry budget, configurable LLM-judge set, and `final_eval` visual sweep with page-bucket fan-out. **Status:** v0.1 — M1–M6 landed; release tasks pending. | [impl](../impl/visual_verifier_implementation.md) |

## ShopBackend

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
|           |           |             |           |


## ShopGuru

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
|           |           |             |           |
