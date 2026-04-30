# ShopGuru Dataset Generation and Evaluation (`packages/shop_guru`)

Status: **Implemented** - Version: **0.1**
Owners: ShopGuru

## Overview

`shop_guru` builds grounded shopping-agent benchmark tasks from a
SandboxShop dataset and can evaluate browser agents against those tasks.
It consumes the JSON data emitted by `shop_arena.gen` and served by
`shop_backend`; it does not explore live stores or generate SandboxShop
data.

The implemented package has two public workflows:

- `shop-guru build` reads one or more shop configs and writes benchmark
  JSON files under `outputs/shop_guru/<shop>/benchmarks/`.
- `shop-guru eval` runs AgentLab / BrowserGym episodes for a selected
  shop and writes per-task results plus aggregate scoring under
  `outputs/shop_guru/<shop>/`.

## Terminology

- **Shop config**: YAML entry with `slug`, `name`, `shop_url`,
  `data_dir`, locale, currency, and image tag fields.
- **SandboxShop data**: The dataset directory containing
  `products.json`, `collections.json`, `navigation.json`, `pages.json`,
  `policies.json`, and optional supporting files.
- **Skill**: A benchmark-task category. The implemented set is
  `exact`, `substitute`, `browse`, `filter`, `shipping`, `returns`,
  and `e2e`.
- **Generator**: Python module under `shop_guru.generators` that emits
  tasks for one skill from one shop's data.
- **Task**: JSON object with an id, starting URL, intent, task type, and
  success criteria consumed by the evaluation runner and LLM judge.
- **Validator**: Post-generation consistency checker that rejects or
  warns on impossible handles, infeasible filters, malformed filter
  intents, and answer leaks.
- **Evaluation run**: AgentLab / BrowserGym study over one shop and an
  optional skill/task filter, scored by an LLM judge and summarized in
  `aggregate.json`.

## Current Status

- `packages/shop_guru` is implemented as a Python package with the
  `shop-guru` console script and `python -m shop_guru` entrypoint.
- `shop-guru build` supports per-shop output, optional flat merged
  output, shop filtering, manual-vs-auto source selection, and
  post-generation validation.
- Deterministic generators cover exact search, substitute search,
  collection browse, collection filter, shipping policy lookup, and
  returns policy lookup. The `e2e` generator uses an LLM to author
  end-to-end shopping journeys from the same grounded data.
- `shop-guru eval` supports one shop at a time, skill/task filtering,
  headed/headless browser runs, parallel workers, judge-model
  selection, and aggregate scoring.
- Tests live under `packages/shop_guru/src/shop_guru/tests` and cover
  config loading, IO, generators, emit, validation, pipeline, filters,
  and eval helpers.

## Desired Status

The existing contract remains the desired v0.1 behavior:

- Generated tasks are grounded in the shop's actual data and are
  reproducible for deterministic skills given the same inputs.
- Every generated task is validated before promotion unless the caller
  explicitly passes `--no-validate`.
- Evaluation output is grouped by shop and study, with a stable
  aggregate summary that can be compared across agents and skill
  filters.
- Adding a new skill means adding one generator module, registering it
  in `pipeline.default_generators`, and extending tests.

## Proposal

No implementation change is proposed by this housekeeping spec. This
document captures the already-shipped package contract so the spec
index has a ShopGuru entry and future generator/evaluation changes have
a stable place to update.

The detailed operator guide remains
`packages/shop_guru/README.md`; this spec owns the architectural
contract and status.

## Alternative

**Keep ShopGuru documented only in its package README.** Rejected
because the repository spec index should cover every top-level package.
The README is still the right place for user-facing examples and flag
tables, but the long-term contract belongs in `docs/specs/`.

## Execution Table

| Task | Status | Notes |
| ---- | ------ | ----- |
| Capture implemented ShopGuru contract in `docs/specs/` | Done | This document. |
| Link ShopGuru from the spec index | Done | `docs/specs/README.md` now has a ShopGuru row. |
| Define new runtime or generator behavior | Not planned | This is housekeeping only. |

## Appendix

Public entrypoints:

- CLI: `shop-guru build`, `shop-guru eval`.
- Python module: `python -m shop_guru`.
- Package API: `load_shops`, `load_shop_data`, `build`,
  `build_all`, `per_shop_out_dir`, and `GeneratorSpec`.

Output roots:

- Benchmarks: `outputs/shop_guru/<shop>/benchmarks/`.
- Evaluation runs: `outputs/shop_guru/<shop>/<timestamp>_<agent>_on_shop_guru.../`.
