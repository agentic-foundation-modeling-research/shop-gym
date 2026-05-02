# `shop_arena.explore`

Storefront exploration pipeline that produces an anonymized **Shop
Manual** — a structured, machine- and human-readable description of a
live storefront's UX, IA, and feature set.

- Spec: [`docs/specs/shop_arena/shop_explore.md`](../../../../docs/specs/shop_arena/shop_explore.md)
- Implementation plan: [`docs/impl/shop_explore_implementation.md`](../../../../docs/impl/shop_explore_implementation.md)
- Status: **v0.1.0 released** — M1–M5 landed (tag `shop-explore-v0.1.0`).
  v0.2 follow-ups (real-LLM synthesis, live `fixture_demo_storefront`
  cassette, exact `products_total`) tracked in M6 of the impl plan.

---

## Install

`shop_arena.explore` ships as part of the `shop-arena` distribution. From the
repo root:

```bash
uv sync
```

That installs the `shop-explore` console script defined by
`packages/shop_arena/pyproject.toml`.

---

## Prerequisites

`shop-explore` is an orchestrator — it shells out to an agent runtime
and, through that runtime, to a browser-automation skill. Make sure the
relevant pieces are installed before running a live exploration:

| Component                  | When required                       | How to install                                                  |
| -------------------------- | ----------------------------------- | --------------------------------------------------------------- |
| Python ≥ 3.12 + `uv`       | Always                              | [astral.sh/uv](https://docs.astral.sh/uv/), then `uv sync`      |
| `claude` CLI               | `--runtime claude_code`             | [docs.claude.com/claude-code](https://docs.claude.com/claude-code) |
| `pi` CLI                   | `--runtime pi`                      | Internal — see `packages/harness/README.md`                     |
| `pnpm` ≥ 9 (or `npm` ≥ 10) | Any run that drives a browser       | [pnpm.io/installation](https://pnpm.io/installation)            |
| `pi-playwright` skill      | Any run that drives a browser       | `pnpm add -g pi-playwright` (or `npm i -g pi-playwright`)       |
| Runtime API key            | Live runs (not `replay`-only tests) | `ANTHROPIC_API_KEY` for `claude_code`, runtime env vars for `pi` |

Quick sanity checks:

```bash
uv --version                                  # Python toolchain
claude --version                              # only if --runtime claude_code
pi --version                                  # only if --runtime pi
node "$(pnpm root -g)/pi-playwright/skills/playwright-browser/scripts/pw.js" --help
```

The last command should print the playwright wrapper's help. If it
fails, `shop-explore` will still start, but the rendered `AGENTS.md`
will contain `SKILL_DIR="<unresolved>"` and the agent will fail the
first time it tries to drive the browser. The pipeline logs a
`could not resolve pi-playwright skill dir` warning at startup when
this happens — watch for it.

The pipeline pre-opens a shared `pw.js` browser session (`pw.js open
about:blank`) before the harness loop starts and closes it after, so
executor iterations skip the cold-start penalty and don't waste tool
calls on `Browser '<session>' is not open` errors. The session id is
derived from the run dir name and exported as `PLAYWRIGHT_CLI_SESSION`
for the duration of the loop. The pre-open is best-effort: if `pnpm`,
`node`, or the playwright skill is missing, a warning is logged and
the run continues (the agent's first `pw.js goto` will then cold-start
the browser itself).

The `--prefetch-only` and `--synthesize-only` flows do not touch the
agent runtime or the browser skill, so the only hard requirement for
those is `uv sync`.

---

## Usage

### Library

```python
from shop_arena.explore import explore, ExploreConfig

result = explore(ExploreConfig(url="https://example-shop.com",
                                runtime="pi"))
assert result.manual_path.exists()
```

### CLI

```
shop-explore <url> [--out PATH] [--runtime {pi,claude_code}]
                   [--model MODEL] [--max-iters N] [--timeout SECONDS]
                   [--force-resume]
                   [--prefetch-only] [--synthesize-only PATH]
```

Run `shop-explore --help` for the full surface.

#### Quick-start: `--prefetch-only`

The deterministic §5.9 prefetch step is the cheapest way to verify
`shop_arena.explore` is wired up correctly: it makes a fixed set of HTTP
calls, no LLM, no browser. Output lands under
`<out>/artifact/prefetch/`.

```bash
uv run shop-explore --prefetch-only \
    --out /tmp/shop-explore-smoke \
    https://demo-storefront.example.invalid

# Inspect the result.
ls /tmp/shop-explore-smoke/artifact/prefetch/
cat /tmp/shop-explore-smoke/artifact/prefetch/prefetch.json | jq '.entries | length'
```

The same path is exercised by `tests/explore/test_cli.py` against
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

#### Resuming a prior run

Pointing `--out` at an existing `run_dir` triggers resume mode (see
[`docs/specs/harness/resume.md` §5.6](../../../../docs/specs/harness/resume.md#56-shop-explore-cli)).
The CLI reads the prior `run.json`'s `config_snapshot` and:

* Defaults `--runtime`, `--model`, `--max-iters`, and `--timeout` to the
  prior values when not supplied (per resume.md §5, `max_iters` is granted
  as *additional* budget, not a lifetime total).
* Errors out with exit code `2` if the supplied positional `<url>` or
  `--runtime` does not match the prior run.
* Forwards `--force-resume` to the harness so the §5.5 refusal policy
  (e.g. `protocol_violation`, `invalid_plan`, `runtime_error`) can be
  overridden when the operator has triaged the prior failure.

```bash
# Continue a run that hit BUDGET_EXHAUSTED with another 10 iterations.
uv run shop-explore https://example-shop.com \
    --out outputs/shop_manuals/example-shop.com/<run_id>/ \
    --max-iters 10
```

Each attempt is appended to `config_snapshot.resume_history` in
`run.json` (one entry per call to `run_plan_exec_loop`, per
resume.md §5.7).

> **Cross-machine resume caveat.** The harness `Workspace.open` resume
> check requires byte-for-byte equality on `AGENTS.md`. Because the
> rendered `AGENTS.md` bakes in the absolute path of the
> `pi-playwright` skill on the recording machine (see
> [Design notes](#design-notes--agentsmd-template-rendering) below),
> resuming a run on a different machine — or after a `pnpm` global
> reinstall that moved the skill — will fail with a workspace-mismatch
> error. Re-render or re-run on the original machine, or run
> `--synthesize-only` against the existing `parts/` if you only need
> to refresh the manual.

---

## Workflow

`shop_arena.explore` is split across three planes: an orchestrator (this
package), the harness (`packages/harness`), and the agent runtime
(`pi` / `claude_code`). The agent runs as a subprocess and does **not**
have access to the codebase — anything that needs Python-side logic
runs in the orchestrator before or after the harness loop.

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Orchestrator (shop_arena.explore.pipeline.explore)                     │
│    Runs in your Python process — has full codebase access.          │
│    ─────────────────────────────────────────────────────────        │
│    a. Resolve run_dir                                               │
│    b. Read prompt files from disk (agents.md, planner.md, …)        │
│    c. Call shop_arena.explore.prefetch.run(url, dest_dir=…)               │
│       Writes deterministic HTTP fetches to a temp seed dir:         │
│         /tmp/shop-explore-seed-XXXX/artifact_seed/prefetch/         │
│       (httpx calls: index.html, sitemap.xml, products.json, …)      │
│    d. Build PlanExecLoopConfig with artifact_seed_dir=seed_dir      │
│    e. Hand off to harness ↓                                         │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. Harness (run_plan_exec_loop) — control plane                     │
│    Pure orchestration. No LLM, no codebase access for agent.        │
│    ─────────────────────────────────────────────────────────        │
│    a. Workspace.create():                                           │
│       - mkdir run_dir/                                              │
│       - copy artifact_seed_dir/* → run_dir/artifact/                │
│         (so prefetch/ shows up inside the workspace)                │
│       - snapshot SeedManifest (sha256 of every seeded file)         │
│    b. Planner iter: spawn `pi --print --mode json` with cwd=run_dir │
│       stdin = planner.md prompt → writes plan.md                    │
│    c. Loop up to max_iters:                                         │
│       - parse plan.md, pick next PENDING task                       │
│       - spawn `pi …` with cwd=run_dir, prompt = execute.md          │
│         + <<<harness-control>>> task header                         │
│       - snapshot trajectory, run protocol checks (incl.             │
│         seed_immutability — agent must NOT mutate prefetch/)        │
│    d. Return when COMPLETED / BUDGET_EXHAUSTED / failure            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. Agent (`pi` subprocess) — data plane                             │
│    cwd = run_dir/. AGENTS.md anchors its instructions.              │
│    ─────────────────────────────────────────────────────────        │
│    Accessible:                                                      │
│      + run_dir/ (plan.md it edits, prompts/, AGENTS.md)             │
│      + run_dir/artifact/prefetch/ (seeded by step 1)                │
│      + whatever tools `pi` ships with (browser, file I/O, etc.)     │
│    Not accessible:                                                  │
│      − shop_arena.explore source code                                     │
│      − shop_arena.explore.prefetch module / any Python codebase APIs      │
│    ─────────────────────────────────────────────────────────        │
│    Each iteration writes parts/<task_id>.md and                     │
│    parts/<task_id>.caps.json into run_dir/artifact/.                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. Synthesis (shop_arena.explore.synthesize.synthesize)                   │
│    Back in your Python process — full codebase access again.        │
│    ─────────────────────────────────────────────────────────        │
│    a. Read parts/*.caps.json, deep-merge → capabilities.json        │
│    b. One LLM call (synthesize_manual.md prompt + capabilities +    │
│       parts concat) → manual.md (or fallback to concat)             │
│    c. Compute stats.json, manifest.json                             │
└─────────────────────────────────────────────────────────────────────┘
```

The bridge between the orchestrator and the agent is
`PlanExecLoopConfig.artifact_seed_dir`. `pipeline.explore` runs
`prefetch.run` into a temp seed directory, hands the path to the
harness, and `Workspace.create` copies the tree into
`run_dir/artifact/` while fingerprinting it. The post-iteration
**seed-immutability protocol check** rejects any iteration that
mutates, deletes, or extends the prefetched files — so the agent
treats `prefetch/` as read-only ground truth. See
[`docs/specs/harness/plan_exec_loop.md`](../../../../docs/specs/harness/plan_exec_loop.md)
§5.4 and
[`docs/specs/harness/seed_immutability.md`](../../../../docs/specs/harness/seed_immutability.md)
for details.

---

## Runtime selection

`--runtime` chooses the agent runtime that drives the harness
plan/exec loop. Resolution goes through `harness.get_runtime` (see
`packages/harness`).

| Runtime       | Default model                  | Notes                                                                  |
| ------------- | ------------------------------ | ---------------------------------------------------------------------- |
| `pi`          | `anthropic/claude-opus-4-7`    | **Default.** Native `pi` runtime; required for live storefront runs. Model follows `pi`'s grammar (`sonnet:high`, `anthropic/...`). |
| `claude_code` | `opus`                         | Alternative runtime; `--model` is forwarded as `claude --model` and follows the `claude` CLI's grammar (aliases like `opus`/`sonnet`, or pinned IDs like `claude-opus-4-5`). |

The default model is per-runtime so the same `--model`-omitted invocation
works for both grammars (`pi`'s provider-prefixed IDs vs the `claude` CLI's
bare aliases). Override per-run with `--model M`; pass `--model ""` to skip
the flag entirely and let the runtime use its own built-in default.

Tests use `harness.runtimes.replay` directly (not exposed as a CLI
choice) so CI never pays for live LLM calls. See
[record-cassette workflow](#record-cassette-workflow) below.

The synthesis pass (§5.10) is independent of the agent runtime: it
makes one direct LLM call from `shop_arena.explore.synthesize`. v0.1 wires a
no-op stub at the CLI layer; the library entrypoint accepts a custom
`LLMClient` for tests and future wiring.

---

## Output layout

`out_dir == run_dir`. The harness owns the top-level structure;
`shop_arena.explore` owns everything under `artifact/`.

```
outputs/shop_manuals/<domain>/<run_id>/
├── AGENTS.md                 # harness-stable; written by shop_arena.explore
├── prompts/                  # planner.md, execute.md
├── plan.md                   # evolving; planner-emitted task list
├── iters/                    # per-iteration trajectories (harness)
├── run.json                  # run summary (harness)
└── artifact/                 # owned by shop_arena.explore + agents
    ├── manual.md             # PUBLISHED — prose, anonymized
    ├── capabilities.json     # PUBLISHED — schema-validated tags
    ├── stats.json            # PUBLISHED — analysis statistics
    ├── manifest.json         # PUBLISHED — run summary + omitted_areas
    ├── prefetch/             # seeded by shop_arena.explore (no LLM)
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
the contract consumed by downstream `shop_arena.gen`. See spec §5.4.

---

## Record-cassette workflow

`shop_arena.explore`'s pipeline tests run against
`harness.runtimes.replay` so they need no network or LLM access. The
cassettes live under `tests/explore/cassettes/<fixture_slug>/`
and follow the harness §5.6 minimal layout (`plan/`, `exec-0001/`, …,
each with `trajectory.json` + `workspace_after/`).

To record (or refresh) a cassette against a real storefront with the
live `pi` runtime:

```bash
# Pick the fixture slug used by tests (see tests/explore/cassettes/README.md).
export FIXTURE=fixture_demo_storefront
export FIXTURE_URL=https://demo-storefront.example.invalid

HARNESS_RECORD=1 \
  uv run shop-explore --runtime pi \
    --out packages/shop_arena/tests/explore/cassettes/$FIXTURE/_recording \
    $FIXTURE_URL
```

`HARNESS_RECORD=1` flips `harness.runtimes.replay` from pure-replay
into a record-then-write mode that delegates each iteration to the
fallback live runtime and persists `trajectory.json` +
`workspace_after/` per iteration. After a successful record:

1. Move the per-iteration cassette directories
   (`plan/`, `exec-0001/`, …) into
   `tests/explore/cassettes/$FIXTURE/`.
2. Redact API keys from any captured `iters/*/native.log` you intend
   to commit.
3. Update `tests/explore/cassettes/README.md` with the recording
   provenance.
4. Run `uv run pytest packages/shop_arena/tests/explore` to
   confirm the cassette replays cleanly.

The synthetic `fixture_drawer_shop` is hand-crafted (no live source)
and stays the canonical replay fixture for the M2/M3 tests; the
recorded fixtures back T4.2–T4.5 of the implementation plan.

---

## Design notes — `AGENTS.md` template rendering

`prompts/agents.md` is a **template**, not a final prompt.
`pipeline.explore` renders two placeholders into it once per run before
handing the result to the harness:

| Placeholder                | Source                                           | Purpose                                                              |
| -------------------------- | ------------------------------------------------ | -------------------------------------------------------------------- |
| `{{PLAYWRIGHT_SKILL_DIR}}` | `pnpm root -g` (then `npm root -g` as fallback)  | Lets the agent run `node $SKILL_DIR/scripts/pw.js …` without discovering the path itself |
| `{{CAPABILITIES_SCHEMA}}`  | `shop_arena.explore.capabilities.schema` source        | Pins the closed pydantic schema inline so it can never drift from the model |

The substitution lives in `pipeline._render_agents_md`. The skill-path
resolver (`_resolve_playwright_skill_dir`) tries `pnpm` first to match
the project standard, falls back to `npm`, and returns `None` (rendered
as the literal string `"<unresolved>"`) when neither is installed or
the global package is missing. A warning is logged so misconfigured
environments fail loudly the first time an iteration touches
`$SKILL_DIR`.

### Why pre-resolve the skill path?

Each executor iteration pays a 4–5 bash-call discovery cost if it has
to find the skill itself (`require.resolve`, `pnpm root -g`, `find`,
…). Pre-rendering trades that per-iteration cost for one resolution at
pipeline startup, which materially shrinks Claude Code wall-time on
20-iter runs.

The tradeoff is that `AGENTS.md` now bakes in an absolute filesystem
path, so it is **machine-specific**. This is fine for the typical
workflow (one machine drives a run end-to-end and may resume on the
same machine) but breaks cross-machine resume (see the [Resuming a
prior run](#resuming-a-prior-run) caveat). If we ever need portable
run dirs, the cleanest follow-up is to switch the placeholder to an
environment-variable indirection (`SKILL_DIR="${SHOP_EXPLORE_SKILL_DIR}"`)
that the harness sets at runtime spawn — keeping the identity bytes
machine-stable. Today's bake-in is the simpler shortcut and is
documented as such.

---

## Module layout

```
packages/shop_arena/src/shop_arena/explore/
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

Re-exported from `shop_arena.explore` (per spec §8.1):

- `explore`, `ExploreConfig`, `ExploreResult`, `RuntimeName`
- `Capabilities`, `CapabilitiesValidationError`
- `Stats`
- `ShopUnreachableError`, `SynthesisError`
- `__version__`

Function-level entrypoints stay namespaced: `prefetch.run`,
`synthesize.synthesize`, `capabilities.merge_fragments`.

## Testing

```bash
uv run pytest packages/shop_arena/tests/explore
```

Tests cover prefetch (`respx` cassette), capabilities schema +
merge, stats, the CLI `--prefetch-only` / `--synthesize-only` paths,
the full pipeline against `harness.runtimes.replay`, and the
anonymization regex scan (SC3).
