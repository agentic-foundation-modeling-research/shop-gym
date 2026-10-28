Index of ShopGym specifications. Organized by category.

Status labels were last refreshed against the codebase on 2026-10-01, at the
v1.1 cutover (M11): the Python packages are gone and every Code Path below
points at the TypeScript implementation. Specs describe intent and
contracts; the code remains the source of truth for shipped behavior.

Superseded specs were removed on 2026-10-27; recover one with
`git log --diff-filter=D --name-only -- docs/specs`. Hard-to-reverse
decisions are recorded in `docs/adr/` and domain terms in `GLOSSARY.md`.

## Cross-cutting

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [v1_1_typescript_redesign.md](v1_1_typescript_redesign.md) | `packages/*` | v1.1 umbrella plan: single TypeScript monorepo, swappable `AgentRuntime` seam over the pi SDK, shared zod schemas and pipeline, stateful episode-scoped backend (customers, checkout, orders) shipped as an agent-editable template with a sandbox contract, single storefront template, programmatic benchmark grading, one `shopgym` CLI. Supersedes the orchestration redesign in `shop_arena/shop_gen.md` v0.2. **Status:** Implemented (M0-M11 on `v1_1-dev`; cutover 2026-10-01). |
| [harness/plan_exec_loop.md](harness/plan_exec_loop.md) | `packages/harness/src/loop.ts`, `workspace.ts`, `plan/`, `telemetry/` | Reusable plan + exec loop harness, runtime-agnostic. **Status:** Implemented; the TypeScript port in `packages/harness` (v1.1 M2) is the only implementation, with the shipped extensions tracked in the sibling harness specs below. Python names in the text map to the same TS module names. |
| [harness/seed_immutability.md](harness/seed_immutability.md) | `packages/harness/src/seed.ts` | Deterministic post-iteration check that aborts a run on any mutation, deletion, or extension of the seeded subtree under `run_dir/artifact/`. **Status:** Implemented; TS port in `packages/harness` (v1.1 M2). |
| [harness/resume.md](harness/resume.md) | `packages/harness/src/loop.ts` + `packages/shop-arena/src/explore` | Optional in-place resume of a partial `runPlanExecLoop` invocation: skip the planner if its trajectory is on disk, continue executor iterations against existing `[x]` markers, quarantine partial iter dirs, and expose `shopgym explore --force-resume`. **Status:** Implemented; TS port in `packages/harness` (v1.1 M2). |
| [harness/verifiers.md](harness/verifiers.md) | `packages/harness/src/verifiers` | Additive, opt-in verifier dispatch hook for the loop: caller-owned `Verifier` implementations are run after each executor iteration, gate `[x]` marks on FAIL, and feed `{{verifier_feedback}}` into the next iteration's prompt. **Status:** Implemented; TS port in `packages/harness` (v1.1 M2). |
| [harness/protocol_violation_recovery.md](harness/protocol_violation_recovery.md) | `packages/harness/src/loop.ts` + `packages/harness/src/plan/rewrite.ts` | Convert executor-phase protocol violations from terminal failures into per-task BLOCKED-and-continue: restore `plan.md`, force-block the violating task, skip it for the rest of the attempt, continue the loop. **Status:** Implemented for executor iterations; planner violations remain terminal. TS port in `packages/harness` (v1.1 M2) also fixed the two recorded drift items. |

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
| [shop_arena/shop_explore.md](shop_arena/shop_explore.md) | `packages/shop-arena/src/explore` + `packages/cli` (`shopgym explore`) | Storefront exploration: produces an anonymized Shop Manual (manual.md + capabilities.json + stats.json + evidence) per storefront. Harness-driven on `@shop-gym/harness` with `@shop-gym/browser` tools, an anonymization verifier, and `--from <step>` on the core pipeline runner. **Status:** Implemented (v1.1 M8; CLI M10). The Python `shop_arena.explore` the text names was removed at the cutover. |
| [shop_arena/shop_gen.md](shop_arena/shop_gen.md) | `packages/shop-arena/src/gen` + `packages/cli` (`shopgym gen`) | SandboxShop generation: turns one or more anonymized Shop Manuals into a hostable SandboxShop (data + storefront + backend copy), validated end-to-end by hosting with `shop_backend` and built via a verifier-gated harness loop. v0.2 of the spec also folds in the orchestration redesign, since replaced by `core/pipeline` (see the v1.1 plan). **Status:** v1.1 port implemented (M7, M7b, M10): `manual_merge`, `data_synth`, `data_validation`, `build`, `final_eval`, `publish`. The v1 Python implementation and the Hydrogen template the text still describes were removed at the cutover; v1.1 output is the single storefront template. |
| [shop_arena/storefront_template.md](shop_arena/storefront_template.md) | `packages/shop-arena/templates/storefront` + `packages/shop-arena/src/templates.ts` | v1.1 storefront template: the React Router 7 SSR app extended with `/account/*` (login, register, profile, addresses, orders, order detail, logout), a real `/checkout` against `checkoutComplete`, `x-shopgym-episode` forwarding on every SSR backend call, backend-aligned fixtures, and a gated end-to-end smoke test. Hydrogen is removed. **Status:** Implemented (v1.1 M6). |
| [shop_arena/backend_generation.md](shop_arena/backend_generation.md) | `packages/shop-arena/src/gen/build` | v1.1 build loop: both templates seeded from `git ls-files` with a `template.json` fingerprint, the shop's own `shop_backend` copy run as a restartable sidecar, a `gen_backend` task with owned-file rules, and the `owned_files`, `backend_typecheck`, `backend_test`, `sandbox_contract` and `data_in_use` verifiers. **Status:** Implemented (v1.1 M5; storefront verifiers M7, `shopgym gen --gen-backend` M10). |
| [shop_arena/visual_verifier.md](shop_arena/visual_verifier.md) | `packages/shop-arena/src/gen/build/verifiers/visual_judge.ts` + `packages/shop-arena/src/gen/final_eval` | `visual_judge` verifier (per-task playwright-driven render judging against `capabilities.json`) + per-task retry budget, configurable LLM-judge set, and `final_eval` visual sweep with page-bucket fan-out. **Status:** Implemented; v1.1 carries it as one judge (`visual_judge` verifier plus the `final_eval` visual sweep) on `BrowserSession` instead of the playwright skill. |
| [shop_arena/manual_split.md](shop_arena/manual_split.md) | `packages/shop-arena/src/gen/manual_merge/split.ts` + `packages/shop-arena/src/gen/build/prompts` | Adds `split_manual_parts` step to slice the merged manual into six per-area sub-manuals; refreshes the build planner / executor prompts to read sub-manuals; retires the `consolidate` task in favor of a renamed `visual_fix`. **Status:** Implemented; in v1.1 the split runs inside `manual_merge`. |

## ShopBackend

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [shop_backend/storefront_api.md](shop_backend/storefront_api.md) | `packages/shop_backend` | Local graphql-yoga server resolving against a SandboxShop dataset (synthesized JSON). Read-mostly Storefront-API surface (Shop, Product, Collection, Menu, Page, Blog, Search, PredictiveSearch, Localization, Metafields, Inventory) plus cart lifecycle mutations, optional file-backed cart persistence, `@inContext` validation, image serving, and `/health`. **Status:** Implemented; v0.2 additions are in code. |
| [shop_backend/stateful_commerce.md](shop_backend/stateful_commerce.md) | `packages/shop_backend/src/{state,sandbox,schema,resolvers}` | Episode-scoped mutable state over the immutable dataset (`ShopState` with carts, customers, sessions, orders, live inventory, deterministic clock and ids), selected per request by `x-shopgym-episode`; per-domain SDL with `customer` / `checkout` / `order` domains and the `@sandbox` directive; optional `customers.json` / `orders.json` / `commerce.json`; grader-facing `StateSnapshot` and `/__shopgym/episodes/<id>` control API; standalone backend template with in-package `AGENTS.md` and read-only contract suite. **Status:** Implemented (v1.1 M4). |

## ShopGuru

| Spec Path | Code Path | Description |
| --------- | --------- | ----------- |
| [shop_guru/task_generation_proposal.md](shop_guru/task_generation_proposal.md) | `packages/shop-guru`, `packages/shop_backend`, `packages/core` | Sandbox limitations and task coverage; template, product-first, and BFS + explore generation; shared validation and difficulty; a proposed 9-shop, 900-task RL and transfer-evaluation pilot across six SandboxShops and three real shops, with no new commerce features. Capability baseline: `4a6a2c5e`. **Status:** Proposed; no implementation in this document. |
| [shop_guru/benchmark_v2.md](shop_guru/benchmark_v2.md) | `packages/shop-guru` + `packages/cli` (`shopgym guru`) | TypeScript benchmark pipeline: ten seed skills plus agent-discovered tasks over the `core` task schema, `AgentUnderTest` episodes isolated by `BrowserSession` and the backend control API, graders for every check kind, and `aggregate.json`. **Status:** Implemented (v1.1 M9; CLI M10). |
