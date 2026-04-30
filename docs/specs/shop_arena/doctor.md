# ShopGym Doctor

## Overview

`shop-doctor` is a local diagnostic command for validating developer
tooling that ShopGym depends on before running live browser workflows.

## Terminology

- **Doctor check**: A single diagnostic that returns pass/fail status,
  a human-readable detail, and an optional fix command.
- **Python Playwright**: The `playwright` Python package and its managed
  browser binaries, used by BrowserGym-backed evaluation.
- **Playwright skill**: The workspace-pinned `pi-playwright` skill at
  `node_modules/pi-playwright/skills/playwright-browser`, used by
  ShopArena agent runtimes.

## Current Status

Implemented in `packages/shop_arena/src/shop_arena/doctor`. The root
README points developers at `uv run shop-doctor`.

## Desired Status

Developers can run one command from the repository root:

```bash
uv run shop-doctor
```

The command reports each Playwright-related prerequisite independently
and exits nonzero when any required check fails.

## Proposal

Ship `shop-doctor` as a `shop-arena` console script because ShopArena
owns the live browser exploration and visual-check workflows. The first
version runs only Playwright-related checks:

- Python Playwright CLI is importable via `python -m playwright --version`.
- Playwright Chromium can launch headlessly.
- The `pi-playwright` skill directory resolves through the same resolver
  used by ShopArena.
- The skill entrypoint `scripts/pw.js` exists and can print help through
  Node.

The command prints stable `[OK]` / `[FAIL]` lines for humans and returns:

- `0` when all checks pass.
- `1` when one or more checks fail.
- `2` for CLI usage errors.

## Alternative

A shell script under `scripts/` would be smaller, but it would duplicate
the Python skill resolver and be harder to unit-test without invoking
real browsers.

## Execution Table

| Task | Status | Notes |
| ---- | ------ | ----- |
| Add `shop_arena.doctor` check helpers | Done | No new dependencies. |
| Add `shop-doctor` console script | Done | Exposed by `packages/shop_arena/pyproject.toml`. |
| Add focused CLI/check tests | Done | Browser and Node calls are monkey-patched in tests. |
| Update README setup verification | Done | Replaces manual probes with `uv run shop-doctor`. |

## Appendix

The command is intentionally narrow. Future doctor sections can add
runtime CLI checks, API-key checks, or generated-shop hosting checks
without changing the Playwright checks.
