# Contributing to ShopGym

Thanks for your interest in ShopGym. This guide covers the practical bits
of getting a change landed: how to set up the repo, what the bar for code
quality is, and how PRs flow.

For project structure and the daily commands you'll actually type, the
[README](./README.md) is the source of truth — start there. For the
deeper "how we think about code" rules, see [AGENT.md](./AGENT.md); the
guidelines apply to humans and agents alike.

## Getting set up

Follow [README → Setup](./README.md#setup). After `uv sync` and
`pnpm install`, verify the toolchain:

```bash
uv run pytest
uv run ruff check .
uv run pyright
pnpm -r test
```

If any of these fail on a clean checkout, please open an issue — that's
a bug in our setup docs, not user error.

## Filing issues

Before opening an issue, check whether the behaviour is described in a
spec under [`docs/specs/`](./docs/specs/) — many planned features exist
on paper before they exist in code, so "this doesn't work" might be
"this isn't built yet."

A useful issue includes:

- What you ran, what you expected, what happened.
- Versions: `uv --version`, `pnpm --version`, `node --version`,
  `python --version`.
- The relevant log lines or stack trace, not a screenshot of them.

## Workflow

1. **Open a discussion first for non-trivial work.** A short issue
   describing the problem and your proposed approach is cheaper than a
   rejected PR. For new features, link the relevant spec in
   `docs/specs/` (or propose one — see *Specs* below).
2. **Branch from `main`.** Use a short, descriptive name (e.g.
   `mz/explore-resume-bug`).
3. **Keep PRs focused.** One logical change per PR. Refactors and
   feature work go in separate PRs even when you noticed the refactor
   while doing the feature.
4. **Make sure CI is green.** See *Required checks* below.
5. **Request review.** Address comments by pushing additional commits;
   maintainers will squash on merge.

## Specs

Larger features are designed in [`docs/specs/`](./docs/specs/) before
being implemented. The split is:

- **`docs/specs/<feature>.md`** — the pure specification: what the
  feature is, what it must do, and the contracts it exposes. Stable
  reference material.
- **`docs/internal/impl/<feature>_impl.md`** — the implementation plan:
  milestones, task breakdown, status. Mutable.

If you're adding a feature that doesn't fit cleanly into existing specs,
please draft the spec and link it from your PR. Use the structure
documented in [AGENT.md → Use Specifications](./AGENT.md#use-specifications).

## Coding standards

[AGENT.md](./AGENT.md) is the binding reference. The short version:

- **Python.** Google style, fully typed, `pyright --strict` clean,
  `ruff` clean, Python ≥ 3.12 syntax. Google-style docstrings on every
  public symbol. `pydantic` v2 at IO boundaries; `dataclass(frozen=True)`
  for internal value types.
- **TypeScript.** Google style, ESM only (`.js` extensions in relative
  imports), `strict` + `noUncheckedIndexedAccess` +
  `exactOptionalPropertyTypes`. `biome` clean. Named exports. No
  `any`, no non-null assertions without a justifying comment.
- **Both.** No silent fallbacks, no hand-rolled retry loops where one
  exists in a library, no speculative configurability.

Run formatters before pushing:

```bash
uv run ruff format .
pnpm format
```

## Tests

Every change that adjusts behaviour needs a test. Tests live under
`packages/<pkg>/tests/` (Python, `pytest`) or co-located as
`*.test.ts` (TypeScript, `vitest`).

- One behaviour per test. Name them `test_<unit>_<behaviour>`.
- Don't mock what you can run cheaply — prefer real filesystem,
  real subprocess, real GraphQL server fixtures over mocks.
- For UI / browser changes, exercise the feature in a browser before
  declaring done. CI can catch type errors but not "the button is in
  the wrong place."

If a test is flaky, fix the flake or quarantine the test in the same
PR — don't leave it for someone else.

## Commits and PRs

- **Commit messages.** Convention used in this repo:
  `<scope>: <imperative summary>` where `<scope>` names the package or
  area touched (e.g. `shop_gen(cart): fix drawer summary overlap`,
  `chore: refactored package structure`). The body explains *why* —
  the diff explains *what*.
- **PR descriptions.** Lead with the problem and the chosen approach.
  Link the spec or issue. Call out anything reviewers should look at
  carefully (perf, migration, security).
- **Don't squash before review.** Maintainers squash on merge so
  individual commits aid review.

## Required checks

The following must pass before a PR can land:

- `uv run pytest` (Python tests)
- `uv run ruff check .` (Python lint)
- `uv run pyright` (Python typecheck, strict)
- `pnpm -r test` (TypeScript tests)
- `pnpm -r build` (TypeScript build)
- `pnpm lint` (TypeScript lint)

CI runs the hosting-validation integration tests against a real
`shop_backend` build (see [`.github/workflows/ci.yml`](./.github/workflows/ci.yml)).

## License

By contributing you agree that your contributions are licensed under
the project's [MIT License](./LICENSE).
