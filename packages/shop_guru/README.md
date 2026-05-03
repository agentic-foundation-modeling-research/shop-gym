# shop_guru

Automated dataset generation pipeline that ingests a sandbox shop's catalog,
navigation structure, and store policies to synthesize diverse, grounded
evaluation tasks across 7 distinct skill categories.


## Why this exists

Evaluating LLM-based shopping agents is hard because:

1. **Every storefronts are different.** Benchmarks built against a handful
   of fixed sites miss the long tail of real e-commerce.
2. **Live sites are flaky.** Out-of-stock items, A/B tests, CAPTCHAs, and
   rate limits make evaluation on production stores irreproducible.
3. **LLM-generated task intents hallucinate.** A robot asking an agent to
   "find the Acme Widget Pro" isn't useful if Acme Widget Pro doesn't exist.

shop_guru tackles all three by deriving tasks **deterministically** from the
SandboxShop's actual product, collection, and page data. Every task is
grounded, guaranteed-solvable, and reproducible given the same inputs.

## Skill categories (v1)

| Skill                                     | Task type  | Source                                            | Target count   |
| ----------------------------------------- | ---------- | ------------------------------------------------- | -------------- |
| `exact` — exact product search            | shopping   | `products.json`                                   | 5 per shop     |
| `substitute` — similar-product search     | shopping   | `products.json`                                   | 5 per shop     |
| `browse` — collection navigation          | shopping   | `collections.json`                                | 5 per shop     |
| `filter` — collection + facet filter      | shopping   | `collections.json` + `stats.json.option_patterns` | 3 per shop     |
| `shipping` — find shipping policy         | navigation | `pages.json` (+ `/policies/shipping-policy` fallback) | 1 per shop |
| `returns` — find returns policy           | navigation | `pages.json` (+ `/policies/refund-policy` fallback)   | 1 per shop |
| `e2e` — end-to-end shopping journeys      | mixed      | LLM-authored from `products`/`collections`        | 16 per shop    |


## Task schema

shop_guru format:

```json
{
  "id": "mock_clothing-exact-1",
  "type": "shopping",
  "url": "https://example.com",
  "intent": "Find the product named Kidoki Squeeze Flashlight and select any variant to add to cart.",
  "success_criteria": {
    "url_contains": "/products/kidoki-squeeze-flashlight",
    "type": "product_search"
  }
}
```

- `id` — `{shop-slug}-{skill}-{index}`
- `type` — `"shopping"` (cart-impacting) or `"navigation"` (content lookup)
- `url` — starting URL; differs between `_real` and `_sandbox` variants
- `success_criteria.url_contains` — **soft** hint for the LLM judge, not a
  hard gate (many policy pages live at non-standard URLs)

## Install

shop_guru is a member of the `shop-gym` `uv` workspace, so a single sync
from the repo root installs it editable alongside its sibling packages:

```bash
uv sync
```

Requires Python ≥ 3.12.

### Ad-hoc run

From the repo root (uses `configs/default.yaml` by default):

```bash
uv run shop-guru build
# or
uv run python -m shop_guru build
```

## Quickstart

1. **Build a SandboxShop from one or more seed storefronts.** Use shop-arena
   Pipeline A or B (see the [top-level README](../../README.md)). You should
   end up with `outputs/shops/<slug>/data/` populated with `products.json`,
   `collections.json`, etc.

2. **Describe the shops** in a YAML config. See
   [`configs/default.yaml`](./configs/default.yaml) for the
   three-shop reference config:

   ```yaml
   shops:
     - slug: mystore
       name: My Store
       shop_url: https://my-sandbox.run.app/?token=secret
       data_dir: outputs/shops/mystore
       country: US
       currency: USD
       language: en
       image_tag: mystore-main
   ```

3. **Generate benchmarks:**

   ```bash
   # From repo root — uses configs/default.yaml by default
   uv run shop-guru build
   ```

   Outputs land in `<repo>/outputs/shop_guru/<slug>/benchmarks/` —
   one file per skill, per shop.

## CLI

`shop-guru` exposes two subcommands. `build` synthesizes benchmark
JSONs; `eval` drives an agent against those benchmarks. Each has its
own flag set — see `--help` for either subcommand.

```
shop-guru build [--config PATH]
                [--flat-out PATH] [--no-per-shop]
                [--data-sources-dir PATH] [--shop SLUG]
                [--only-auto | --only-manual]
                [--no-validate]

shop-guru eval  --shop SLUG
                [--config PATH] [--skill SKILL ...]
                [--max-steps N] [--n-jobs N] [--judge-model MODEL]
                [--headless | --headed] [--results-dir PATH]
                [--verbose]
```

### `shop-guru build` flags

| Flag                 | Description                                                                         |
| -------------------- | ----------------------------------------------------------------------------------- |
| `--config`           | Path to shops YAML (default: `configs/default.yaml`)                              |
| `--flat-out PATH`    | Optional. Additionally emit a flat mirror at `PATH` with all shops merged per skill |
| `--no-per-shop`      | Skip per-shop writes (requires `--flat-out`)                                        |
| `--data-sources-dir` | Hand-authored source JSONs (default: `data_sources/`)                               |
| `--shop SLUG`        | Only build this shop                                                                |
| `--only-auto`        | Skip hand-authored sources                                                          |
| `--only-manual`      | Skip automated generators                                                           |
| `--no-validate`      | Skip the post-generation consistency validator (default: validate, exit non-zero on errors) |

Default output layout: `<repo>/outputs/shop_guru/<slug>/benchmarks/`. Shop
data is read from `<repo>/<shop.data_dir>/data/`, where `shop_arena`
extracts storefronts (typically `outputs/shops/<domain>/`).

Alternative entry: `uv run python -m shop_guru build ...` (same arguments).

### Post-generation validator

After every generation pass the CLI runs `shop_guru.validate` over the
emitted benchmark files (per-shop and flat-out, plus any hand-authored
files in the same directories). The validator catches the failure modes
that drove manual benchmark patches in the calibration shops:

| Rule                     | Severity  | What it catches                                                                            |
| ------------------------ | --------- | ------------------------------------------------------------------------------------------ |
| `unknown-collection`     | error     | `url_contains` references a collection handle not in `data/collections.json`               |
| `unknown-product`        | error     | `url_contains` references a product handle not in `data/products.json`                     |
| `unknown-page`           | warning   | `url_contains` references a page handle not in `data/pages.json` (policies fall back here) |
| `infeasible-filter`      | error     | A `<slug>-filter-N` task names a `(dim, value)` no product in the targeted collection has  |
| `filter-dim-unknown`     | warning   | Filter dim doesn't match any known field/option/alias (e.g. localized storefront labels)   |
| `filter-intent-malformed`| warning   | Filter intent doesn't match the `use the <dim> filter (e.g. <value>)` template             |
| `intent-answer-leak`     | error     | Any string in `success_criteria.response_contains` appears verbatim in `intent`            |

Run validation programmatically:

```python
from shop_guru.io import load_shop_data
from shop_guru.validate import validate_tasks, has_errors

issues = validate_tasks(tasks, shop, load_shop_data(shop, root))
if has_errors(issues):
    raise SystemExit(1)
```

URL handle checks use prefix matching to mirror the runtime
`url_contains` substring semantics (`/products/whole-geode` validates
against a catalog containing `whole-geode-compact-curiosities`).

## Running evaluations

shop_guru ships an AgentLab + BrowserGym harness that runs a browsing agent
against the generated benchmarks, asks an LLM judge to score each
trajectory, and writes per-task + aggregate results to disk. Two CLIs:

| Command                                | Use when                                                                                |
| -------------------------------------- | --------------------------------------------------------------------------------------- |
| `python -m shop_guru.eval.run`          | You want to drive **one or a few tasks** (debugging, spot-check, demo).                 |
| `shop-guru eval` (or `shop_guru.eval.run_all`) | You want to run **every task** matching your filters and get an aggregate success rate. |

### Prerequisites

1. Storefront URLs must be live — benchmarks were emitted against the
   `shop_url` for each entry in `configs/default.yaml`.
2. API tokens for accessing OPENAI APIs

   ```bash
   export OPENAI_API_KEY="<token>"
   ```
3. Install Playwright's Chromium (runtime dependency, fetched on demand):

   ```bash
   uv run playwright install chromium
   ```

Every invocation is scoped to a single shop (`--shop` is required) so
the per-run output groups cleanly under `outputs/shop_guru/<shop>/`.
To sweep multiple shops, run the CLI once per shop.

### Run a single task

Useful for iterating on a specific benchmark or watching the agent run
headed. Filter with `--task-id` (repeatable):

```bash
uv run python -m shop_guru.eval.run --shop mock_clothing --task-id mock_clothing-e2e-1

# Watch the browser
uv run python -m shop_guru.eval.run --shop mock_clothing --task-id mock_clothing-e2e-1 --headed

# Restrict by skill (without task-id, runs everything matching)
uv run python -m shop_guru.eval.run --shop mock_clothing --skill e2e
```

### Run every task with an aggregate summary

Batch driver for one shop. Runs in parallel (default `--n-jobs` is half
the CPU count, capped at 8) and writes a tqdm progress bar to the
terminal:

```bash
uv run shop-guru eval --shop mock_clothing
# → shop_guru tasks:  42%|████▎     | 20/48 [03:14<04:22,  9.37s/task]

# Narrow scope further by skill
uv run shop-guru eval --shop mock_clothing --skill e2e

# Tune parallelism (1 = sequential, useful for debugging)
uv run shop-guru eval --shop mock_clothing --n-jobs 4

# Restore full INFO-level logs (disables the progress bar)
uv run shop-guru eval --shop mock_clothing --verbose
```

### Output layout

Each run creates a timestamped study directory nested under its shop
slug. The study name carries the `--skill` filter (if any) so sibling
runs on the same shop are self-describing. Override the top-level root
with `--results-dir`:

```
outputs/shop_guru/
└── <shop>/                                               one dir per shop
    └── <timestamp>_<agent>_on_shop_guru_[<skill>...]/
        ├── <episode_dir>/
        │   ├── summary_info.json       per-episode metrics + judge verdict
        │   ├── step_*.pkl.gz           full step trace (observation, action, screenshot)
        │   └── experiment.log
        ├── results.json                flat list of per-task success/verdict (run_all only)
        ├── aggregate.json              totals + success_rate, broken down by shop/skill (run_all only)
        ├── result_df_trial_1_of_1.csv  AgentLab's tabular dump
        └── summary_df_trial_1_of_1.csv
```

Examples:

| Invocation                                          | Study folder                                  |
| --------------------------------------------------- | --------------------------------------------- |
| `... --shop mock_clothing`                          | `..._on_shop_guru_/`                       |
| `... --shop mock_clothing --skill e2e`              | `..._on_shop_guru_e2e/`                   |
| `... --shop mock_clothing --skill e2e --skill exact`| `..._on_shop_guru_e2e_exact/` (sorted)   |
| `... --shop mock_clothing --skill all`              | `..._on_shop_guru_all/` (every skill)     |

`--skill all` is a sentinel value: it loads every skill for the shop
(same effect as omitting `--skill`) and tags the study folder `_all` so
scripted sweeps can pass a uniform `--skill` value every iteration.
`all` cannot be combined with other `--skill` values.

`aggregate.json` example shape:

```json
{
  "total": 48,
  "n_success": 19,
  "success_rate": 0.396,
  "n_forced_by_budget": 22,
  "n_impossible_task": 0,
  "n_reached_captcha": 0,
  "by_shop":  { "mock_clothing": { "total": 16, "n_success": 8, "success_rate": 0.5 } },
  "by_skill": { "e2e":           { "total": 48, "n_success": 19, "success_rate": 0.396 } }
}
```

### Common flags (both drivers)

| Flag                      | Default                       | Purpose                                                                                              |
| ------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| `--config`                | `configs/default.yaml`      | Shops YAML                                                                                           |
| `--shop`                  | *required*                    | Shop slug to evaluate (exactly one; run the CLI per shop to sweep)                                   |
| `--skill`                 | *all*                         | Restrict to one or more skill names (repeatable). Pass `--skill all` to run every skill and tag the folder `_all` |
| `--max-steps`             | `30`                          | Hard cap on agent steps per episode                                                                  |
| `--n-jobs`                | `1` / `≈cpu/2`                | Parallel workers (joblib when >1)                                                                    |
| `--judge-model`           | `gpt-5`                       | LLM used to grade trajectories                                                                       |
| `--headless` / `--headed` | headless                      | Browser visibility                                                                                   |
| `--results-dir`           | `outputs/shop_guru`           | Top-level root; a `<shop>/` subdir is always appended and `AGENTLAB_EXP_ROOT` points there           |

`run.py` additionally accepts `--task-id` (repeatable). `run_all.py`
additionally accepts `--verbose` (disables the quiet progress bar).

Full list: `uv run shop-guru eval --help`.

## Python API

```python
from shop_guru import load_shops, load_shop_data, build, per_shop_out_dir

shops = load_shops("packages/shop_guru/configs/default.yaml")
for shop in shops:
    data = load_shop_data(shop)
    out_dir = per_shop_out_dir(shop)
    build(shop, data, out_dirs=[out_dir])
```

Both `load_shop_data` and `per_shop_out_dir` resolve paths against the
repo root automatically (`outputs/shops/<domain>/data/` for input,
`outputs/shop_guru/<slug>/benchmarks/` for output).

Custom generators:

```python
from shop_guru import build, GeneratorSpec
from shop_guru.generators import exact_search

my_gens = [
    GeneratorSpec("my_custom_exact_v2", exact_search.generate, {"count": 20}),
]
build(shop, data, out_dirs=["./data"], generators=my_gens)
```

End-to-end `build_all`:

```python
from shop_guru import build_all

build_all(
    config="packages/shop_guru/configs/default.yaml",
    flat_out="outputs/benchmarks",  # optional
)
```

## Architecture

```
packages/shop_guru/
├── pyproject.toml          Installable as `shop-guru` with CLI entry point
├── README.md               This file
├── configs/
│   └── default.yaml        Default shops config (3 mock shops)
└── src/shop_guru/
    ├── __init__.py         Public API
    ├── __main__.py         python -m shop_guru
    ├── cli.py              argparse CLI (shop-guru)
    ├── config.py           Shop dataclass + YAML loader
    ├── io.py               load_shop_data (with raw_data/ stats fallback), load_json
    ├── filters.py          Generic-collection skip-list, word-boundary page matcher
    ├── emit.py             emit_tasks, make_id (single-file per-skill writer)
    ├── validate.py         Post-generation consistency rules (Issue, validate_tasks, has_errors)
    ├── pipeline.py         build, build_all, validate_all, GeneratorSpec, per_shop_out_dir
    ├── _dotenv.py          Project-root .env loader for LLM credentials
    ├── generators/
    │   ├── exact_search.py
    │   ├── substitute_search.py
    │   ├── collection_browse.py
    │   ├── collection_filter.py     Per-collection (dim, value) feasibility-aware
    │   ├── find_policy.py
    │   └── e2e.py                   LLM-authored end-to-end journeys
    ├── eval/                        AgentLab + BrowserGym evaluation harness
    │   ├── run.py                   single-task / debugging driver
    │   ├── run_all.py               batch driver with aggregate summary
    │   ├── judge.py                 LLM judge
    │   ├── score.py / aggregate.py  scoring + per-skill rollup
    │   └── ...
    └── tests/                       config, filters, emit, generators, pipeline, validate, io, eval
```

### Adding a new skill

1. Create `src/shop_guru/generators/<skill>.py` with a single public
   ``generate(shop, data, seed=0, **kwargs) -> list[dict]`` function.
2. Add it to the list in
   [`src/shop_guru/pipeline.py::default_generators`](src/shop_guru/pipeline.py)
   with a stable `filename_stem`.
3. Add a test under `src/shop_guru/tests/test_generators.py`.

## Development

```bash
# From repo root — uv sync installs the workspace + dev group
uv sync

# Run tests (all packages)
uv run pytest

# Just shop_guru
uv run pytest packages/shop_guru/src/shop_guru/tests

# Lint + format
uv run ruff check packages/shop_guru/src
uv run ruff format packages/shop_guru/src

# Type check
uv run pyright packages/shop_guru/src
```

## Reproducibility & determinism

Deterministic generators (`exact`, `substitute`, `browse`, `filter`,
`shipping`, `returns`) use seeded random samplers. Re-running
`shop-guru` against the same extracted data produces byte-for-byte
identical output for these skills (tasks are sorted by ID).

The `e2e` skill is **LLM-generated** and is therefore not byte-deterministic
across runs even with a fixed seed. Regenerate intentionally and review
the resulting `outputs/shop_guru/<slug>/benchmarks/ShopGuru_e2e_*.json`
before promoting it as the authoritative artifact for an evaluation run.

## Consent & data policy

- shop_guru is designed to release benchmarks over **opted-in** or sandbox storefronts
  only.
- All task data is derived from public-facing storefront surfaces. No PII,
  private merchant analytics, or transaction data is touched.
- LLM-authored intents must not encode secrets, internal-only product
  names, or pre-release catalog data — review e2e output before release.

## License

MIT
