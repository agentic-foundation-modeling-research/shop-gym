# `shop_explore`

Storefront exploration pipeline that produces an anonymized **Shop
Manual** — a structured, machine- and human-readable description of a
live storefront's UX, IA, and feature set.

- Spec: [`docs/specs/shop_arena/shop_explore.md`](../../../../docs/specs/shop_arena/shop_explore.md)
- Implementation plan: [`docs/impl/shop_explore_implementation.md`](../../../../docs/impl/shop_explore_implementation.md)
- Status: **v0.1 (in progress)** — M1–M3 + T5.1 landed; M4 live-runtime
  smoke + M5 release pending.

---

## Install

`shop_explore` ships as part of the `shop-arena` distribution. From the
repo root:

```bash
uv sync
```

That installs the `shop-explore` console script defined by
`packages/shop_arena/pyproject.toml`.

---

## Usage

### Library

```python
from shop_explore import explore, ExploreConfig

result = explore(ExploreConfig(url="https://example-shop.com",
                                runtime="pi"))
assert result.manual_path.exists()
```

### CLI

```
shop-explore <url> [--out PATH] [--runtime {pi,claude_code}]
                   [--max-iters N] [--timeout SECONDS]
                   [--prefetch-only] [--synthesize-only PATH]
```

Run `shop-explore --help` for the full surface.

#### Quick-start: `--prefetch-only`

The deterministic §5.9 prefetch step is the cheapest way to verify
`shop_explore` is wired up correctly: it makes a fixed set of HTTP
calls, no LLM, no browser. Output lands under
`<out>/artifact/prefetch/`.

```bash
uv run shop-explore --prefetch-only \
    --out /tmp/shop-explore-smoke \
    https://theme-dawn-demo.myshopify.com

# Inspect the result.
ls /tmp/shop-explore-smoke/artifact/prefetch/
cat /tmp/shop-explore-smoke/artifact/prefetch/prefetch.json | jq '.entries | length'
```

The same path is exercised by `tests/shop_explore/test_cli.py` against
a `respx`-mocked storefront, so the snippet is regression-covered.

#### Full pipeline

```bash
uv run shop-explore https://example-shop.com
```

Without flags this drives the full §5.2 pipeline: prefetch → harness
plan/exec loop → deterministic synthesis. Output lands under
`outputs/shop_manuals/<domain>/<run_id>/`. The CLI v0.1 wires a no-op
LLM client for the synthesis pass, so `manual.md` is currently emitted
via the deterministic fallback (concatenation of `parts/*.md`); a real
LLM client is wired in a later milestone.

#### `--synthesize-only` (re-merge an existing run)

```bash
uv run shop-explore --synthesize-only outputs/shop_manuals/example-shop.com/<run_id>/
```

Useful for iterating on the synthesis prompt or re-running merge after
hand-editing `parts/*.caps.json`.

---

## Runtime selection

`--runtime` chooses the agent runtime that drives the harness
plan/exec loop. Resolution goes through `harness.get_runtime` (see
`packages/harness`).

| Runtime       | Notes                                                                  |
| ------------- | ---------------------------------------------------------------------- |
| `pi`          | **Default.** Native `pi` runtime; required for live storefront runs.  |
| `claude_code` | Alternative runtime selectable via `harness.get_runtime("claude_code")`. |

Tests use `harness.runtimes.replay` directly (not exposed as a CLI
choice) so CI never pays for live LLM calls. See
[record-cassette workflow](#record-cassette-workflow) below.

The synthesis pass (§5.10) is independent of the agent runtime: it
makes one direct LLM call from `shop_explore.synthesize`. v0.1 wires a
no-op stub at the CLI layer; the library entrypoint accepts a custom
`LLMClient` for tests and future wiring.

---

## Output layout

`out_dir == run_dir`. The harness owns the top-level structure;
`shop_explore` owns everything under `artifact/`.

```
outputs/shop_manuals/<domain>/<run_id>/
├── AGENTS.md                 # harness-stable; written by shop_explore
├── prompts/                  # planner.md, execute.md
├── plan.md                   # evolving; planner-emitted task list
├── iters/                    # per-iteration trajectories (harness)
├── run.json                  # run summary (harness)
└── artifact/                 # owned by shop_explore + agents
    ├── manual.md             # PUBLISHED — prose, anonymized
    ├── capabilities.json     # PUBLISHED — schema-validated tags
    ├── stats.json            # PUBLISHED — analysis statistics
    ├── manifest.json         # PUBLISHED — run summary + omitted_areas
    ├── prefetch/             # seeded by shop_explore (no LLM)
    │   ├── index.html
    │   ├── sitemap.xml
    │   ├── robots.txt
    │   ├── products.json
    │   ├── collections.json
    │   ├── search_suggest.json
    │   ├── cart.js
    │   ├── policies/
    │   └── prefetch.json
    ├── parts/                # written by executors
    │   ├── <task_id>.md
    │   └── <task_id>.caps.json
    └── evidence/             # written by executors
        └── <task_id>/
            ├── snapshots/
            ├── screenshots/
            └── network.jsonl
```

The five **published** artifacts (`manual.md`, `capabilities.json`,
`stats.json`, `manifest.json`, plus the `prefetch/` directory) form
the contract consumed by downstream `shop_gen`. See spec §5.4.

---

## Record-cassette workflow

`shop_explore`'s pipeline tests run against
`harness.runtimes.replay` so they need no network or LLM access. The
cassettes live under `tests/shop_explore/cassettes/<fixture_slug>/`
and follow the harness §5.6 minimal layout (`plan/`, `exec-0001/`, …,
each with `trajectory.json` + `workspace_after/`).

To record (or refresh) a cassette against a real storefront with the
live `pi` runtime:

```bash
# Pick the fixture slug used by tests (see tests/shop_explore/cassettes/README.md).
export FIXTURE=fixture_dawn_demo
export FIXTURE_URL=https://theme-dawn-demo.myshopify.com

HARNESS_RECORD=1 \
  uv run shop-explore --runtime pi \
    --out packages/shop_arena/tests/shop_explore/cassettes/$FIXTURE/_recording \
    $FIXTURE_URL
```

`HARNESS_RECORD=1` flips `harness.runtimes.replay` from pure-replay
into a record-then-write mode that delegates each iteration to the
fallback live runtime and persists `trajectory.json` +
`workspace_after/` per iteration. After a successful record:

1. Move the per-iteration cassette directories
   (`plan/`, `exec-0001/`, …) into
   `tests/shop_explore/cassettes/$FIXTURE/`.
2. Redact API keys from any captured `iters/*/native.log` you intend
   to commit.
3. Update `tests/shop_explore/cassettes/README.md` with the recording
   provenance.
4. Run `uv run pytest packages/shop_arena/tests/shop_explore` to
   confirm the cassette replays cleanly.

The synthetic `fixture_drawer_shop` is hand-crafted (no live source)
and stays the canonical replay fixture for the M2/M3 tests; the
recorded fixtures back T4.2–T4.5 of the implementation plan.

---

## Module layout

```
packages/shop_arena/src/shop_explore/
├── __init__.py            # public re-exports (spec §8.1)
├── cli.py                 # argparse → explore()
├── config.py              # ExploreConfig, ExploreResult (pydantic v2)
├── pipeline.py            # explore() — orchestrates the four steps
├── stats.py               # compute_stats(prefetch, capabilities)
├── coverage.py            # SC5 gate (test-side, not in public surface)
├── prefetch/              # §5.9 deterministic HTTP prefetch
│   ├── __init__.py        # re-exports run, PrefetchResult, ShopUnreachableError, defaults
│   ├── models.py          # PrefetchEntry, PrefetchResult, ShopUnreachableError
│   └── runner.py          # run() + fetch plan + bot-block detection
├── capabilities/          # §5.5 capabilities schema + merge
│   ├── __init__.py        # re-exports Capabilities, Conflict, merge_fragments, …
│   ├── schema.py          # Capabilities + nested section models
│   └── merge.py           # merge_fragments + Conflict + deep-merge helpers
├── synthesize/            # §5.10 post-loop synthesis
│   ├── __init__.py        # re-exports synthesize, SynthesisResult, LLMClient, …
│   ├── core.py            # synthesize() entrypoint + result/error/protocol types
│   ├── manual.py          # MANUAL_MIN_CHARS + render_manual + concat_parts
│   └── manifest.py        # build_manifest + plan.md parsers
├── prompts/
│   ├── agents.md
│   ├── planner.md
│   ├── execute.md
│   └── synthesize_manual.md
└── py.typed
```

## Public surface

Re-exported from `shop_explore` (per spec §8.1):

- `explore`, `ExploreConfig`, `ExploreResult`, `RuntimeName`
- `Capabilities`, `CapabilitiesValidationError`
- `Stats`
- `ShopUnreachableError`, `SynthesisError`
- `__version__`

Function-level entrypoints stay namespaced: `prefetch.run`,
`synthesize.synthesize`, `capabilities.merge_fragments`.

## Testing

```bash
uv run pytest packages/shop_arena/tests/shop_explore
```

Tests cover prefetch (`respx` cassette), capabilities schema +
merge, stats, the CLI `--prefetch-only` / `--synthesize-only` paths,
the full pipeline against `harness.runtimes.replay`, and the
anonymization regex scan (SC3).
