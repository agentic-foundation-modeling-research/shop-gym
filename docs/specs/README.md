Index of ShopGym specifications. Organized by category.

## Cross-cutting

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
| [harness/plan_exec_loop.md](harness/plan_exec_loop.md) | `packages/harness` | Reusable plan + exec loop harness, runtime-agnostic. | [impl](../impl/plan_exec_loop_implementation.md) |
| [harness/seed_immutability.md](harness/seed_immutability.md) | `packages/harness/src/harness/seed.py` | Deterministic post-iteration check that aborts a run on any mutation, deletion, or extension of the seeded subtree under `run_dir/artifact/`. **Status:** Implemented in `harness` 0.2.0. | — |
| [harness/resume.md](harness/resume.md) | `packages/harness` | Optional in-place resume of a partial `run_plan_exec_loop` invocation: skip the planner if its trajectory is on disk, continue executor iterations against existing `[x]` markers, quarantine partial iter dirs. **Status:** Draft (proposed). | — |
| [harness/verifiers.md](harness/verifiers.md) | `packages/harness` | Additive, opt-in verifier dispatch hook for `run_plan_exec_loop`: caller-owned `Verifier` implementations are run after each executor iteration, gate `[x]` marks on FAIL, and feed `{{verifier_feedback}}` into the next iteration's prompt. **Status:** Draft (proposed). Required by `shop_gen`. | [impl](../impl/verifiers_implementation.md) |

## ShopArena

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
| [shop_arena/shop_explore.md](shop_arena/shop_explore.md) | `packages/shop_arena/src/shop_explore` | Storefront exploration: produces an anonymized Shop Manual (manual.md + capabilities.json + stats.json + evidence) per storefront. Harness-driven; uses the playwright skill. **Status:** v0.1 in progress (M1–M3 + M5 docs landed; M4 live-runtime smoke pending). | [impl](../impl/shop_explore_implementation.md) |
| [shop_arena/shop_gen.md](shop_arena/shop_gen.md) | `packages/shop_arena/src/shop_gen` | SandboxShop generation: turns one or more anonymized Shop Manuals into a hostable SandboxShop (data + Hydrogen app), validated end-to-end by hosting with `shop_backend` and built via a verifier-gated harness loop. **Status:** Draft (design in progress). | [impl](../impl/shop_gen_implementation.md) |

## ShopBackend

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
|           |           |             |           |


## ShopGuru

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
|           |           |             |           |
