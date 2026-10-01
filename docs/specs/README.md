Index of ShopGym specifications. Organized by category.

Status labels were last refreshed against the codebase on 2026-05-29.
Specs describe intent and contracts; the code remains the source of truth
for shipped behavior.

## Cross-cutting

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [v1_1_typescript_redesign.md](v1_1_typescript_redesign.md) | `packages/*` (target layout) | v1.1 umbrella plan: single TypeScript monorepo, swappable `AgentRuntime` seam over the pi SDK, shared zod schemas and pipeline, stateful episode-scoped backend (customers, checkout, orders) shipped as an agent-editable template with a sandbox contract, single storefront template, programmatic benchmark grading. Supersedes the orchestration redesign in `shop_arena/shop_gen.md` v0.2. **Status:** Proposed; implementation on `v1_1-dev`. |
| [harness/plan_exec_loop.md](harness/plan_exec_loop.md) | `packages/harness/src` | Reusable plan + exec loop harness, runtime-agnostic. **Status:** Implemented (Python); ported to TypeScript as `@shop-gym/harness` in v1.1 M2. Shipped extensions are tracked in the sibling harness specs below. |
| [harness/seed_immutability.md](harness/seed_immutability.md) | `packages/harness/src/seed.ts` | Deterministic post-iteration check that aborts a run on any mutation, deletion, or extension of the seeded subtree under `run_dir/artifact/`. **Status:** Implemented; ported to TypeScript in v1.1 M2. |
| [harness/resume.md](harness/resume.md) | `packages/harness/src/loop.ts` + `packages/shop_arena/src/shop_arena/explore` | Optional in-place resume of a partial `run_plan_exec_loop` invocation: skip the planner if its trajectory is on disk, continue executor iterations against existing `[x]` markers, quarantine partial iter dirs, and expose `shop-explore --force-resume`. **Status:** Implemented; harness side ported to TypeScript in v1.1 M2. |
| [harness/verifiers.md](harness/verifiers.md) | `packages/harness/src/verifiers` | Additive, opt-in verifier dispatch hook for `run_plan_exec_loop`: caller-owned `Verifier` implementations are run after each executor iteration, gate `[x]` marks on FAIL, and feed `{{verifier_feedback}}` into the next iteration's prompt. **Status:** Implemented; ported to TypeScript in v1.1 M2. |
| [harness/protocol_violation_recovery.md](harness/protocol_violation_recovery.md) | `packages/harness/src/loop.ts` | Convert executor-phase protocol violations from terminal failures into per-task BLOCKED-and-continue: restore `plan.md`, force-block the violating task, skip it for the rest of the attempt, continue the loop. **Status:** Implemented for executor iterations; planner violations remain terminal. The TypeScript port (v1.1 M2) also fixes the two recorded drift items. |

## Agent

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [agent/runtime.md](agent/runtime.md) | `packages/agent` | The agent seam: `AgentRuntime`, `LlmClient`, `Tool`, and `Trajectory` contracts, the pi SDK adapter with per-run routing and isolation, `FakeRuntime`, and the conformance suite every adapter runs. **Status:** Implemented (v1.1 M1). |

## Browser

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [browser/tools.md](browser/tools.md) | `packages/browser` | Per-episode Playwright `BrowserSession` sending `x-shopgym-episode`, agent `browserTools` built on native aria-snapshot refs (`navigate` ... `screenshot`, gated `evaluate`, `finish`), and the `probe` helper for graders. **Status:** Implemented (v1.1 M3). |

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
