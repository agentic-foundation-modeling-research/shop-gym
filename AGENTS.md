# AGENTS.md

**ShopGym** is a TypeScript mono-repo for building and evaluating shopping LLM agents. It contains eight packages:

- `packages/core` (`@shop-gym/core`) - shared task / result schemas (zod), the file-based pipeline runner, and the `.env` credentials loader.
- `packages/agent` (`@shop-gym/agent`) - the `AgentRuntime` / `LlmClient` / `Tool` / `Trajectory` seam, the pi SDK adapter, `FakeRuntime` and the adapter conformance suite.
- `packages/harness` (`@shop-gym/harness`) - **Harness**: runtime-agnostic plan-then-loop engine over the agent seam. Owns workspace state, seed immutability, verifier dispatch, resume, and telemetry; prompts and tools come from the caller.
- `packages/browser` (`@shop-gym/browser`) - per-episode Playwright `BrowserSession`, agent `browserTools`, and `probe` for graders.
- `packages/shop_backend` (`@shop-gym/shop-backend`) - **ShopBackend**: Storefront-API-compatible GraphQL server with episode-scoped state (carts, customers, checkout, orders) over a SandboxShop dataset; also the backend template seeded into every generated shop.
- `packages/shop-arena` (`@shop-gym/shop-arena`) - **ShopArena**: Environment Factory. `src/explore` turns a live storefront into an anonymized Shop Manual; `src/gen` turns manuals into a deterministic, self-contained **SandboxShop** (data + storefront + backend); `templates/storefront` is the storefront template.
- `packages/shop-guru` (`@shop-gym/shop-guru`) - **ShopGuru**: benchmark pipeline that generates grounded tasks from a SandboxShop, discovers more with an explorer agent, runs agents in isolated browser episodes, grades, and aggregates.
- `packages/cli` (`@shop-gym/cli`) - the `shopgym` binary: `explore | gen | host | guru | trace | doctor`.

IMPORTANT: Always refer to `README.md` for project context, setup and common commands. Always keep `README.md` up-to-date.

Packages are managed with `pnpm` workspaces (root `package.json`, `pnpm-workspace.yaml`).

## Repository Structure

```
shop-gym/
├── AGENTS.md                   # this file — agent behavior + coding guidelines
├── CLAUDE.md -> AGENTS.md      # alias for Claude Code
├── README.md                   # project overview, setup, quickstart
├── packages/
│   ├── core/                   # @shop-gym/core - schemas, pipeline runner, credentials
│   ├── agent/                  # @shop-gym/agent - AgentRuntime seam + pi adapter
│   ├── harness/                # @shop-gym/harness - plan-then-loop agent engine
│   ├── browser/                # @shop-gym/browser - Playwright session + browser tools
│   ├── shop_backend/           # @shop-gym/shop-backend - GraphQL server + backend template
│   ├── shop-arena/             # @shop-gym/shop-arena - explore, gen, templates/storefront
│   ├── shop-guru/              # @shop-gym/shop-guru - benchmark build / explore / solve / eval
│   └── cli/                    # @shop-gym/cli - the `shopgym` binary
├── docs/
│   └── specs/                  # design specifications (intent — see `docs/specs/README.md`)
├── scripts/                    # thin shell helpers
├── outputs/                    # generated artifacts (gitignored): shop_manuals, shops, shop_guru
├── pnpm-workspace.yaml         # pnpm workspace root
├── package.json                # root scripts: build, test, typecheck, lint, codegen:check, shop:host
├── tsconfig.base.json          # shared TS compiler config
└── biome.json                  # TS lint/format config
```

Typical data flow: `shopgym explore` -> `shopgym gen` -> `shopgym host` -> `shopgym guru` (build tasks, then evaluate agents). Dependency direction is strictly downward: `cli -> {shop-arena, shop-guru} -> {shop_backend, harness, browser} -> agent -> core`. The `harness` package provides the runtime-agnostic engine used by the explore, build and eval loops.

## Behavior Guideline

### Use Specifications

IMPORTANT: Before implementing any feature, consult the specifications in `docs/specs/README.md`.

- Assume NOT implemented. Many specs describe planned features that may not yet exist in the codebase.
- Check the codebase first. Before concluding something is or isn't implemented, search the actual code. Specs describe intent; code describes reality.
- Use specs as guidance. When implementing a feature, follow the design patterns, types, and architecture defined in the relevant spec.
- Spec index: `docs/specs/README.md` lists all specifications organized by category (core, LLM, security, etc.).
- For designing new features, create the pure specifications in `docs/specs/<feature>.md`, and track implementation plans in issues or pull requests.
- During implementation, make docstrings self-contained and DO NOT refer to the specs.

Each specification / design doc need to follow the structure:

```
 Overview
 Terminology
 Current Status
 Desired Status
 Proposal
 Alternative (optional, if any)
 Execution Table
 Appendix
```

### Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Hierarchy Matters

When create new files:

- Think about the big picture and maintain a good codebase structure.
- Don't put every files under the same folder. Instead, build modules with high cohesion, low coupling.

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## Coding Style

Follow the Google Style Guide and keep the highest standard.
NO PATCHING OR HACKING FOR SHORT TERM SUCCESS.

### TypeScript Coding Style

- **Style guide**: Google TypeScript Style Guide. `biome` is the source of truth for lint + format (config in root `biome.json`).
- **Version**: Node ≥ 22, TypeScript ≥ 5.6, ESM only (`"type": "module"`). Use `.js` extensions in relative imports (required by Node ESM).
- **Typing**: `strict` + `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes` (see `tsconfig.base.json`). No `any`; prefer `unknown` + narrowing. No non-null assertions (`!`) without a comment justifying why.
- **Layout**: `src/` → `dist/`. Public API re-exported from `src/index.ts`. No deep imports across package boundaries.
- **Naming**: `camelCase` for variables/functions, `PascalCase` for types/classes, `SCREAMING_SNAKE_CASE` for module-level constants. File names `kebab-case.ts` (tests: `*.test.ts`).
- **Exports**: prefer named exports; avoid default exports. Keep each module focused on one concern.
- **Async**: `async`/`await` only. No floating promises. No mixing callbacks with promises.
- **Errors**: throw `Error` subclasses with meaningful messages. Never `throw` non-Error values. No `try/catch` without handling.
- **Immutability**: `const` by default, `readonly` for fields, `ReadonlyArray<T>` for parameters when the callee should not mutate.
- **Tests**: `vitest`, co-located as `*.test.ts` next to the unit under test.

## Playwright Browser Skill Guidelines

When using the `playwright-browser` skill, always follow these rules to avoid wrapper restrictions:

1. **Always save files locally**: Do not use the temporary `ARTIFACT_DIR` or `/var/folders/` paths for screenshots, PDFs, or snapshots, as the wrapper's security policy will throw a `File access denied` error. Always write output to the current working directory using relative paths (e.g., `--filename "./screenshot.png"` or `--filename "./snapshot.md"`).
2. **Use built-in commands**: Do not attempt to use `run-code` to access internal Playwright objects like `page.accessibility.snapshot()`. The wrapper does not expose the full Playwright API in this way and will throw a `TypeError`. Use the native built-in commands provided by the wrapper instead (e.g., `node "$SKILL_DIR/scripts/pw.js" snapshot --filename "./snapshot.md"`).
