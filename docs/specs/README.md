Index of ShopGym specifications. Organized by category.

## Cross-cutting

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
| [harness/plan_exec_loop.md](harness/plan_exec_loop.md) | `packages/harness` | Reusable plan + exec loop harness, runtime-agnostic. | [impl](../impl/plan_exec_loop_implementation.md) |
| [harness/seed_immutability.md](harness/seed_immutability.md) | `packages/harness/src/harness/seed.py` | Deterministic post-iteration check that aborts a run on any mutation, deletion, or extension of the seeded subtree under `run_dir/artifact/`. **Status:** Implemented in `harness` 0.2.0. | — |
| [harness/resume.md](harness/resume.md) | `packages/harness` | Optional in-place resume of a partial `run_plan_exec_loop` invocation: skip the planner if its trajectory is on disk, continue executor iterations against existing `[x]` markers, quarantine partial iter dirs. **Status:** Draft (proposed). | — |

## ShopArena

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
| [shop_arena/shop_explore.md](shop_arena/shop_explore.md) | `packages/shop_arena/src/shop_explore` | Storefront exploration: produces an anonymized Shop Manual (manual.md + capabilities.json + stats.json + evidence) per storefront. Harness-driven; uses the playwright skill. **Status:** v0.1 in progress (M1–M3 + M5 docs landed; M4 live-runtime smoke pending). | [impl](../impl/shop_explore_implementation.md) |

## ShopBackend

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
|           |           |             |           |


## ShopGuru

| Spec Path | Code Path | Description | Impl Plan |
| --------- | --------- | ----------- | --------- |
|           |           |             |           |
