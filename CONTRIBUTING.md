# Contributing to ShopGym

Thanks for your interest in ShopGym. This guide covers the practical bits
of getting a change landed: how to set up the repo, what the bar for code
quality is, and how PRs flow.

For project structure and the daily commands you'll actually type, the
[README](./README.md) is the source of truth — start there. For the
deeper "how we think about code" rules, see [AGENTS.md](./AGENTS.md); the
guidelines apply to humans and agents alike.

## Getting set up

Follow [README → Setup](./README.md#setup). After `pnpm install`, verify
the toolchain:

```bash
pnpm -r build
pnpm -r typecheck
pnpm -r test
pnpm lint
node packages/cli/dist/main.js doctor
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
- Versions: `pnpm --version`, `node --version`.
- The relevant log lines or stack trace, not a screenshot of them.

## Workflow

1. **Open a discussion first for non-trivial work.** A short issue
   describing the problem and your proposed approach is cheaper than a
   rejected PR. For new features, link the relevant spec in
   `docs/specs/` (or propose one — see *Specs* below).
2. **Branch from `main`.** Use a short, descriptive name (e.g.
   `dev/explore-resume-bug`).
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
- **Issues and pull requests** — the implementation plan: milestones,
  task breakdown, status, and review context. Mutable.

If you're adding a feature that doesn't fit cleanly into existing specs,
please draft the spec and link it from your PR. Use the structure
documented in [AGENTS.md → Use Specifications](./AGENTS.md#use-specifications).

Two smaller records sit next to the specs:

- **[`GLOSSARY.md`](./GLOSSARY.md)** - the project's domain terms. Use
  them in code, issues, and PRs, and add a term when your change
  introduces one.
- **[`docs/adr/`](./docs/adr/)** - one short file per hard-to-reverse
  decision (`NNNN-slug.md`). Add one when your PR makes such a decision.

## Coding standards

[AGENTS.md](./AGENTS.md) is the binding reference. The short version:

- **TypeScript.** Google style, ESM only (`.js` extensions in relative
  imports), `strict` + `noUncheckedIndexedAccess` +
  `exactOptionalPropertyTypes`. `biome` clean. Named exports. No
  `any`, no non-null assertions without a justifying comment.
- **Always.** No silent fallbacks, no hand-rolled retry loops where one
  exists in a library, no speculative configurability.

Run the formatter before pushing:

```bash
pnpm format
```

## Tests

Every change that adjusts behaviour needs a test. Tests are `vitest`
suites co-located as `*.test.ts` next to the unit under test; slow suites
(template installs, hosting a fixture shop) are gated behind
`SHOPGYM_SLOW_TESTS=1` and model-calling suites behind `SHOPGYM_LIVE=1`.

- One behaviour per test, named for the unit and the behaviour.
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

## Contributor License Agreement

External contributors must sign Shopify's Contributor License Agreement
before their pull requests can be merged. The CLA check is automated by
[`.github/workflows/cla.yml`](./.github/workflows/cla.yml).

Comment `signed` on the pull request if the CLA action asks you to do so
after signing.

## Code of Conduct

All project spaces follow the [Code of Conduct](./CODE_OF_CONDUCT.md).
Report concerns to `opensource@shopify.com`.

## Required checks

The following must pass before a PR can land:

- `pnpm -r build` (build)
- `pnpm -r typecheck` (`tsc --noEmit`)
- `pnpm -r test` (tests; CI installs Playwright Chromium first)
- `pnpm lint` (biome)
- `pnpm codegen:check` (`shop_backend` GraphQL codegen drift)

See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) for the exact
job.

## Maintainers

Code ownership is tracked in [`.github/CODEOWNERS`](./.github/CODEOWNERS).
Maintainers triage issues, review pull requests, keep CI healthy, and update
the public docs when workflows change.

Repository admins should protect the default branch with code-owner review,
the CI jobs, and the CLA check as required status checks. The CLA workflow also
requires the repository secret `CLA_TOKEN`.

## License

By contributing you agree that your contributions are licensed under
the project's [MIT License](./LICENSE).
