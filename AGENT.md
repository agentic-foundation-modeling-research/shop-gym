# AGENT.md

**ShopGym** is a mono-repo for building and evaluating shopping LLM agents. It contains three packages:

- `packages/shop_arena` (Python) — **ShopArena**: Environment Factory that generates deterministic, self-contained sandbox shops (**SandboxShops**) from live storefronts. Ships two top-level modules: `shop_arena.gen` (generation pipeline) and `shop_arena.explore` (storefront exploration).
- `packages/shop_guru` (Python) — **ShopGuru**: automated dataset generation pipeline that ingests a sandbox shop's catalog, navigation, and policies to synthesize grounded evaluation tasks across 7 skill categories.
- `packages/shop_backend` (TypeScript) — **ShopBackend**: local GraphQL API server hosting SandboxShop data; used for benchmarking and as an RL environment.

IMPORTANT: Always refer to `README.md` for project context, setup and common commands. Always keep `README.md` up-to-date.

Python packages are managed with `uv` (workspace at repo root). TypeScript packages are managed with `pnpm` workspaces.

## Behavior Guideline

### Use Specifications

IMPORTANT: Before implementing any feature, consult the specifications in `docs/specs/README.md`.

- Assume NOT implemented. Many specs describe planned features that may not yet exist in the codebase.
- Check the codebase first. Before concluding something is or isn't implemented, search the actual code. Specs describe intent; code describes reality.
- Use specs as guidance. When implementing a feature, follow the design patterns, types, and architecture defined in the relevant spec.
- Spec index: `docs/specs/README.md` lists all specifications organized by category (core, LLM, security, etc.).
- For designing new features, create the pure specifications in `docs/specs/<feature>.md`, and split it up with implementation plan `docs/internal/impl/<feature>_impl.md`

Each specification / design doc need to follow the structure:

```
 Overview
 Terminology
 Current Status
 Desired Status
 Proposal
 Alternative (optional, if any)
 Milestones
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

### Python Coding Style

- **Style guide**: Google Python Style Guide. `ruff` is the source of truth for lint + format (config in root `pyproject.toml`).
- **Version**: Python ≥ 3.12. Use modern syntax (`list[int]`, `str | None`, `match`).
- **Typing**: fully typed. `from __future__ import annotations` in every module. `pyright` in `strict` mode must pass. No `Any` unless justified in a comment.
- **Layout**: `src/<package>/` layout. Each package exposes `py.typed`.
- **Docstrings**: Google style (`Args:`, `Returns:`, `Raises:`). Every public module, class, and function has one. Skip trivial one-liners only when the name fully describes behavior.
- **Imports**: stdlib → third-party → local, separated by blank lines. **Absolute imports within a package at top of the files, not local imports**. No wildcard imports.
- **Data models**: use `pydantic` v2 for external/IO boundaries; use `dataclasses` (frozen where possible) for internal value types.
- **Errors**: raise specific exceptions; never bare `except`. No silent fallbacks.
- **Side effects**: keep modules import-safe — no I/O, network, or env reads at import time.
- **Tests**: `pytest` under `packages/<pkg>/tests/`. One behavior per test. Name tests `test_<unit>_<behavior>`. No `unittest.TestCase`.
- **CLI**: expose as `project.scripts` entrypoint; keep `cli.py` thin — argument parsing + dispatch only.

### TypeScript Coding Style

- **Style guide**: Google TypeScript Style Guide. `biome` is the source of truth for lint + format (config in root `biome.json`).
- **Version**: Node ≥ 20, TypeScript ≥ 5.6, ESM only (`"type": "module"`). Use `.js` extensions in relative imports (required by Node ESM).
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
