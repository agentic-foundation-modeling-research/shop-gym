# `shop_arena.env_eval`

Measurement-only module that evaluates a shopping **environment** (a live
storefront or a generated SandboxShop). Given one URL it drives BrowserGym
through a fixed pipeline and emits a closed-schema `metrics.json` plus the
raw artifacts behind it. EnvEval does **not** generate shops, manuals, or
tasks; it does **not** evaluate agents. Its consumer is anyone deciding
whether a storefront is rich enough to serve as an RL environment.

- Spec: [`docs/specs/shop_arena/env_eval.md`](../../../../../docs/specs/shop_arena/env_eval.md)
- Implementation plan: [`docs/internal/impl/env_eval_impl.md`](../../../../../docs/internal/impl/env_eval_impl.md)
- Status: **v0.1.2** — M0–M11 landed.

> Naming: `shop_arena.env_eval` evaluates *environments*. It must not be
> confused with `shop_guru.eval`, which evaluates *agents* against
> ShopGuru tasks.

---

## Install

`shop_arena.env_eval` ships as part of the `shop-arena` distribution.
From the repo root:

```bash
uv sync
uv run --frozen playwright install chromium    # one-time, for BrowserGym
```

That installs the `shop-env-eval` console script defined by
`packages/shop_arena/pyproject.toml`.

### LLM credentials (only when the rubric or stateful pass runs)

Provider is selected by model-id prefix:

| Prefix              | Provider  | Required env var    |
| ------------------- | --------- | ------------------- |
| `claude-*`          | Anthropic | `ANTHROPIC_API_KEY` |
| `gpt-*`, `o*`       | OpenAI    | `OPENAI_API_KEY`    |

`--no-rubric` skips the observation-layer LLM call and the
`/pages/<slug>` classifier (transition layer) and writes stub
`*.rubric.json` plus a stub `transition/pages_classification.json` so
`metrics.json` stays schema-valid.

---

## Quickstart

### CLI

```bash
# Single-shop measurement (writes outputs/shop_env_evals/<host>/<run_id>/)
shop-env-eval run https://example-shop.myshopify.com

# Smoke a sandbox shop without spending tokens
shop-env-eval run https://shop-arena-...run.app --no-rubric

# Visualize an existing run's transition graph
shop-env-eval visualize outputs/shop_env_evals/sandbox-a/2026-01-...
```

The `run` subcommand prints the absolute path to `metrics.json` on stdout
(spec SC1) and exits `0`; failures map to non-zero exit codes via
`shop_arena.env_eval.errors.EnvEvalError` subclasses.

### Library

```python
from shop_arena.env_eval import (
    EvalConfig,
    evaluate,
    render_graph_html,
)

result = evaluate(EvalConfig(url="https://example-shop.com"))
print(result.run_dir)        # outputs/shop_env_evals/example-shop.com/<run_id>/
print(result.metrics_path)   # .../metrics.json — ready for notebook analysis

render_graph_html(result.run_dir)  # writes <run_dir>/transition/graph.html
```

Cross-run analysis (compare / aggregate / cohort report) is intentionally
not part of the public API: `metrics.json` is a closed pydantic v2
schema and is meant to be loaded directly from a Jupyter notebook (or
any other downstream tool).

---

## Pipeline (what `evaluate` actually does)

EnvEval holds **one** BrowserGym env open for the whole run and drives
`page.goto()` between sample URLs. The pipeline runs five steps and
caches each step on the filesystem (spec §5.7):

1. **Page selection** — pick the five canonical sample pages
   (`homepage`, `collection`, `product`, `policy`, `cart_and_search`)
   from `<url>`'s navigation, with a deterministic search query inferred
   from the storefront itself. Output: `pages.json`. `--rediscover`
   re-runs this step only.
2. **Transition graph (BFS + stateful pass)** — bounded BFS from each
   measurable seed (max depth = `--max-hops`, global cap of 64 URL nodes),
   plus the closed fixed-rule stateful pass (`RULE_VERSION = "0.3"`: cart
   drawer, search overlay, predictive panel, filter/sort menus, variant
   select, mega menu, …). URLs are canonicalized so `/products/<*>`,
   `/collections/<*>`, and `/policies/<*>` collapse to one node. The
   `/pages/<slug>` family collapses lazily: every page expansion that
   surfaces fresh slugs triggers a single batched LLM call to the
   `/pages` classifier, which labels each slug (support / about /
   policy / program / locator / marketing / unknown). `marketing`
   slugs collapse to `/pages/<*>`; the other labels keep their distinct
   graph identity. The result is persisted as
   `transition/pages_classification.json` and reused on resume. Every
   graph node gets a folder under `transition/node/`; `/` is named
   `home`. URL-node folders contain `screenshot.png` and `axtree.*`;
   state-node folders contain `pre.*` and `post.*`.
3. **Observation layer** — uses the transition graph's captured nodes as its
   input. URL nodes read `transition/node/<folder>/screenshot.png` and
   `axtree.*`; state nodes read the post-action state (`post.png`,
   `post.axtree.json`, `post.axtree.txt`). It writes node-stemmed copies plus
   `*.rubric.json` under `observation/`.
4. **Action layer** — counts actionable targets for each captured transition
   node through the versioned role/action heuristic (`HEURISTIC_VERSION =
   "0.2"`). Hidden AX nodes are skipped, and `choice_target_count` captures
   radio/checkbox/select/sort/filter/variant controls separately from the raw
   BrowserGym action verbs. State-node action counts also use the `post.*`
   axtree. Outputs are node-stemmed `*.action_space.json` files under
   `action/`. Semantic action counts in `metrics.json` are derived from
   transition graph edges, not from these per-node action-space elements.

Finally `metrics.py` flattens the per-step artifacts into a closed
pydantic v2 `Metrics` document and writes `metrics.json` (the only
**published** file). `manifest.json` records run-level facts:
config snapshot, BrowserGym version, prompt/rule/heuristic versions,
browser-navigation count, LLM-call count, and which steps ran vs.
reused.

### Three layers, three independent caches

Each layer's cache key is *artifact existence in `out_dir`*, not a
content hash. Re-running against the same `--out` reuses the steps
whose required files already exist (SC4 — second invocation does **0**
browser navigations and **0** LLM calls if everything is already on
disk). `--rediscover` is the only invalidation flag in v0.1; it ignores
`pages.json` only and warns that downstream artifacts may be stale.

---

## Inputs

| Input            | Default                                                     | Notes                                                                                  |
| ---------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `url`            | required                                                    | Public storefront base URL (`http://` or `https://`).                                  |
| `--out`          | `outputs/shop_env_evals/<shop_name>/<run_id>/`              | Existing directories trigger resume mode (spec §5.7).                                  |
| `--viewport`     | `1440x900`                                                  | Single desktop viewport in v0.1.                                                       |
| `--max-hops`     | `3`                                                         | BFS depth. `0` disables the BFS pass.                                                  |
| `--rubric-model` | `claude-sonnet-4-6`                                         | Provider routed by prefix; vision required.                                            |
| `--pages-classifier-model` | `gpt-5`                                           | Model id for the `/pages/<slug>` classifier; provider routed by prefix.                |
| `--no-rubric`    | off                                                         | Skip the observation LLM and the `/pages` classifier; write stub artifacts.            |
| `--rediscover`   | off                                                         | Re-run page selection only.                                                            |
| `--shop-name`    | hostname of `<url>`                                         | Override the `<shop_name>` directory segment.                                          |

`EvalConfig` mirrors the same fields and is `frozen=True`,
`extra="forbid"`.

---

## Outputs

```
outputs/shop_env_evals/<shop_name>/<run_id>/
├── pages.json                       # discovered URLs + selection rules
├── observation/
│   ├── index.json                    # node artifact index
│   ├── home.{png,axtree.json,axtree.txt,rubric.json}
│   ├── collections__template.{png,axtree.*,rubric.json}
│   └── state__home__cart_drawer.{png,axtree.*,rubric.json}  # copied from post.*
├── action/
│   ├── index.json                    # node artifact index
│   ├── home.action_space.json
│   └── state__home__cart_drawer.action_space.json           # computed from post.*
├── transition/
│   ├── graph.json                    # nodes + edges + edge labels
│   ├── trace.jsonl                   # per-attempt visit log
│   ├── pages_classification.json     # /pages/<slug> labels (closed schema)
│   ├── node/                         # one folder per transition graph node
│   │   ├── index.json                # canonical id -> folder mapping
│   │   ├── home/{node.json,screenshot.png,axtree.json,axtree.txt}
│   │   └── state__home__cart_drawer/{node.json,pre.*,post.*}
├── metrics.json                     # PUBLISHED — closed v0.2 schema
└── manifest.json                    # run/reuse summary + config
```

`metrics.json` is the single file consumed by `compare` and `aggregate`.
The schema is closed (`extra="forbid"` on every model); unknown keys are
rejected. Unavailable sample pages serialize as explicit closed status
objects under `pages` (e.g. `{"status": "not_found", "reason": "no_product_link"}`),
not zeroed metrics.

`metrics.observation` and `metrics.action` are website-level aggregates over
captured transition graph nodes. They intentionally do not duplicate per-page
or per-node measurements: observation exposes aggregate axtree/content/rubric
counts, including raw `max_depth` and wrapper-collapsed `semantic_max_depth`,
while action exposes aggregate raw actions plus transition-edge-derived
semantic action buckets. Per-node detail remains in `observation/index.json`,
`action/index.json`, and the node-stemmed artifacts those indexes reference.

`metrics.version` is the schema version (`"0.3"`); `shop.eval_version`
is the package version (`__version__`, currently `"0.1.2"`).

---

## Commands

### `shop-env-eval run <url>`

Discover sample pages, capture observation/action/transition artifacts,
write `metrics.json`. Prints the `metrics.json` path on stdout (SC1).

### `shop-env-eval visualize <run_dir> [--out PATH]`

Reads `<run_dir>/transition/graph.json` and writes a self-contained
interactive HTML page (vis-network loaded from a CDN) showing the
combined BFS + stateful graph. Seeds are coloured separately from
discovered URL nodes and stateful state nodes; edges carry the
pipeline's `click(...)` / `fill(...)` labels as hover tooltips. Defaults
to `<run_dir>/transition/graph.html`; prints the absolute path on
stdout. Output is byte-stable for fixed inputs.

Library equivalent:

```python
from shop_arena.env_eval import render_graph_html

render_graph_html("outputs/shop_env_evals/sandbox-a/2026-05-...")
```

Both subcommands are deterministic for fixed inputs (SC5).

---

## Errors

`shop_arena.env_eval.errors` exposes the closed failure vocabulary; the
CLI maps each to exit code `2`:

| Class                     | Raised when                                                      |
| ------------------------- | ---------------------------------------------------------------- |
| `ShopUnreachableError`    | The homepage navigation itself fails.                            |
| `PageDiscoveryError`      | Page-selection invariants are violated (e.g. unknown bucket).    |
| `MetricsValidationError`  | A `metrics.json` fails closed-schema validation.                 |
| `PagesClassifierError`    | The `/pages/<slug>` classifier returned an invalid response.     |
| `ResumeError`             | An existing `--out` is inconsistent with the current config.     |
| `EnvEvalError`            | Common base — catch this in library callers.                     |

---

## Out of scope (v0.1)

- Authenticated flows (login, account, wishlist).
- Checkout (cart-to-payment).
- Mobile / responsive viewports — desktop only.
- Lighthouse-style perf metrics, asset weight, rendered page mass.
- Composite quality scores or learned weighting across metrics.
- Re-deriving a Shop Manual or capabilities — that is
  [`shop_arena.explore`](../explore/README.md).

---

## Testing

```bash
# Unit + replay tests (no live browser, no live LLM)
uv run --frozen --package shop-arena pytest packages/shop_arena/tests/env_eval -q

# Show CLI help — exercises argparse wiring
uv run --frozen shop-env-eval --help
uv run --frozen shop-env-eval run --help
```

Live smoke tests (against the sandbox URLs in the impl plan) are
described in [`docs/internal/impl/env_eval_impl.md`](../../../../../docs/internal/impl/env_eval_impl.md);
they require a running BrowserGym install and, for the rubric and
stateful smoke, valid LLM credentials.
