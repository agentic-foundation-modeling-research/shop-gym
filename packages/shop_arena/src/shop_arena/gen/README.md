# `shop_arena.gen`

SandboxShop generation pipeline. Given one or more anonymized **Shop
Manuals** (the published output of `shop_arena.explore`), `shop_arena.gen` produces
a deterministic, hostable **SandboxShop**: a JSON dataset matching the
`shop_backend` Storefront-API contract *plus* a generated Hydrogen
storefront that renders against it.

- Spec: [`docs/specs/shop_arena/shop_gen.md`](../../../../docs/specs/shop_arena/shop_gen.md)
- Implementation plan: [`docs/impl/shop_gen_implementation.md`](../../../../docs/impl/shop_gen_implementation.md)
- Status: **v0.1.0** — M0–M6 landed (step DAG + manual merge + data
  synth + data validation + build harness loop + advisory final eval).
  Public surface: `run`, `ShopGenConfig`, `ShopGenResult`,
  `__version__`. v0.2 follow-ups (image generation, programmatic
  per-shop allowlist, hosting auto-retry) are out of scope for v0.1.

---

## Install

`shop_arena.gen` ships as part of the `shop-arena` distribution. From the
repo root:

```bash
uv sync
```

That installs the `shop-gen` console script defined by
`packages/shop_arena/pyproject.toml`.

---

## Prerequisites

`shop-gen` is an orchestrator: it spawns a `shop-backend` sidecar for
data validation and the build loop, and shells out to an agent runtime
for the Phase 4 plan/exec loop.

| Component                  | When required                                       | How to install                                                  |
| -------------------------- | --------------------------------------------------- | --------------------------------------------------------------- |
| Python ≥ 3.12 + `uv`       | Always                                              | [astral.sh/uv](https://docs.astral.sh/uv/), then `uv sync`      |
| `pnpm` ≥ 9 + Node ≥ 20     | Phase 3 hosting check + Phase 4 build verifiers     | [pnpm.io/installation](https://pnpm.io/installation), then `pnpm install` at repo root |
| `shop-backend` build       | Phase 3 + Phase 4                                   | `pnpm --filter @shop-gym/shop-backend build`                    |
| `pi` CLI                   | `--runtime pi` (default) on live runs               | Internal — see `packages/harness/README.md`                     |
| `claude` CLI               | `--runtime claude_code` on live runs                | [docs.claude.com/claude-code](https://docs.claude.com/claude-code) |
| Runtime API key            | Live runs (not `replay`-only tests)                 | `ANTHROPIC_API_KEY` for `claude_code`; runtime env vars for `pi` |

The replay-only tests under `tests/gen/` need none of the runtime
or sidecar prerequisites — see [Testing](#testing) below.

---

## Usage

### CLI

Four workflows cover the typical use cases. All four take the same
positional `<seed_dir>...` and `--out-dir <dir>` arguments; the flags
below select *which* steps run.

**1. Full run** — every stale step end-to-end. Idempotent; re-running
with the same `--out-dir` is a no-op once everything is up to date.

```bash
uv run shop-gen <seed_dir>... --out-dir outputs/shops/my-shop
```

**2. Re-run a specific step (cascade downstream)** — `--from <step>`
marks the named step and every downstream descendant stale on disk and
re-runs them. `--only <step>` is the build-loop redo flag from spec
§5.7.3: when invoked against a `[x]` task in
`<out_dir>/runs/build/plan.md` it appends a fresh `<task>_redo_<N>`
PENDING bullet and forces `run_build_harness_loop` to resume — the
original `[x]` is never mutated.

```bash
uv run shop-gen --from synth_collections <seed>... --out-dir outputs/shops/my-shop
uv run shop-gen --only gen_homepage      <seed>... --out-dir outputs/shops/my-shop
```

**3. Run up to a step (halt early)** — `--to <step>` slices the
registry to `<step>` plus every transitive ancestor before execution,
so the runner halts once `<step>` produces its outputs. Useful for
stopping at a phase boundary (e.g. `--to assemble_data` produces the
full `data/` tree without booting the `shop-backend` sidecar or
running the build loop). Composes with `--from` / `--only`;
force-stale ids must lie inside the slice.

```bash
uv run shop-gen --to assemble_data <seed>... --out-dir outputs/shops/my-shop
```

**4. Fresh run from scratch** — pick a different `--out-dir`. There is
no destructive `--fresh` flag; a clean output directory gives you a
deterministic clean run without putting an existing workspace at risk.

```bash
uv run shop-gen <seed>... --out-dir outputs/shops/my-shop-v2
```

#### Passive controls

```bash
uv run shop-gen --status     --out-dir outputs/shops/my-shop
uv run shop-gen --list-steps
```

#### Scale + behavior knobs

```bash
uv run shop-gen <seed>... --out-dir outputs/shops/my-shop \
    --collections 10 \
    --products-per-collection 20 \
    --images-per-product 2 \
    --image-backend placeholder \
    --runtime pi \
    --model anthropic/claude-opus-4-7 \
    --max-iters 30
```

`<seed_dir>` is the path to a `shop_manuals/<domain>/<run_id>/`
directory produced by `shop-explore`. Pass two or more seeds to
trigger Phase 1 (manual merge); a single seed takes the byte-for-byte
copy fast path.

#### Progress logging

Every CLI invocation emits timestamped progress logs to stderr at INFO
level. Each run is bracketed by a ``start run`` and ``end run`` line;
every step emits ``run`` (starting), ``done`` (ok with elapsed
wall-clock), or ``skip`` (already fresh). Failures log ``fail`` at
ERROR before re-raising.

```
23:32:21 shop-gen INFO: start run — out_dir=outputs/shops/my-shop seeds=1 runtime=pi model=anthropic/claude-opus-4-7
23:32:21 shop-gen INFO: run  copy_seed_manual (manual_merge) — starting
23:32:21 shop-gen INFO: done copy_seed_manual (manual_merge) — ok in 0.42s
23:32:21 shop-gen INFO: skip synth_identity (data_synth) — fresh
23:32:21 shop-gen INFO: end run   — ran=1 skipped=1 total=0.42s
```

Library callers configure their own logging; the package logger is
``shop_arena.gen`` (sub-loggers ``shop_arena.gen.pipeline`` and
``shop_arena.gen.steps.runner``) so they can be filtered or routed
independently.

### Library

```python
from pathlib import Path

from shop_arena.gen import ShopGenConfig, run

config = ShopGenConfig(
    seeds=(Path("outputs/shop_manuals/example-shop.com/2025-01-01-12-00"),),
    out_dir=Path("outputs/shops/example"),
    name="example",
)
result = run(config)
print(result.data_dir, result.hydrogen_dir, result.final_eval_path)
```

Re-running with the same `out_dir` is idempotent: every step that is
already up to date is skipped. Pass `force_ids=frozenset({"step_id"})`
to emulate `--from <step>` programmatically.

---

## Runtime selection

`--runtime` chooses the agent runtime that drives the Phase 4 build
loop. Resolution goes through `harness.get_runtime` (see
`packages/harness`).

| Runtime       | Default model                  | Notes                                                                  |
| ------------- | ------------------------------ | ---------------------------------------------------------------------- |
| `pi`          | `anthropic/claude-opus-4-7`    | **Default.** Native `pi` runtime; required for live runs. Model follows `pi`'s grammar (`sonnet:high`, `anthropic/...`). |
| `claude_code` | `opus`                         | Alternative runtime; `--model` is forwarded as `claude --model` and follows the `claude` CLI's grammar (aliases like `opus`/`sonnet`, or pinned IDs like `claude-opus-4-5`). |

The default model is per-runtime so the same `--model`-omitted invocation
works for both grammars. Override per-run with `--model M`; pass `--model ""`
to skip the flag and let the runtime use its built-in default. Mixing the
two grammars (e.g. `--runtime claude_code --model anthropic/foo`) is
rejected at config-construction time with a `ValidationError`.

Tests use `harness.runtimes.replay` directly (not exposed as a CLI
choice) so CI never pays for live LLM calls. See
[Record-cassette workflow](#record-cassette-workflow).

The Phase 5 `final_eval` LLM judge is independent of `--runtime`: it
makes one direct LLM call. v0.1 wires a stub at the CLI; the library
entrypoint accepts a custom `LLMCompleter` for tests.

---

## Step DAG quick-reference

The pipeline is a DAG of named steps grouped into five phases. The
orchestrator computes staleness per step and re-runs only what's
needed. `shop-gen --list-steps` prints the live registry; the table
below is the same set, frozen as a copy/paste reference for
`--from` / `--to` / `--only`.

| Phase             | Steps (in registration order)                                                                                                                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `manual_merge`    | `copy_seed_manual` (single-seed)  •  `merge_capabilities`, `merge_manual_prose`, `compute_merge_stats`, `write_merge_manifest` (multi-seed)                                                                  |
| `data_synth`      | `synth_identity`, `synth_store`, `synth_pages`, `synth_policies`, `synth_collections`, `synth_product_skeletons`, `synth_product_details`, `synth_alt_text`, `gen_images`, `synth_navigation`, `assemble_data` |
| `data_validation` | `validate_schema`, `validate_hosting`                                                                                                                                                                        |
| `build`           | `clone_template`, `write_env_file`, `start_sidecar`, `run_build_harness_loop`                                                                                                                                |
| `final_eval`      | `final_eval`                                                                                                                                                                                                 |

```
[phase 1: manual_merge]                     [phase 2: data_synth]
─────────────────────────                   ─────────────────────
multi-seed (N > 1):                         synth_identity
  merge_capabilities                          ├─► synth_store
    ▼                                         ├─► synth_pages
  merge_manual_prose                          ├─► synth_policies
    ▼                                         └─► synth_collections
  compute_merge_stats                                  ├─► synth_navigation
    ▼                                                  └─► synth_product_skeletons
  write_merge_manifest                                        ├─► synth_product_details
                                                              │      ├─► synth_alt_text
single-seed (N = 1):                                          │      └─► gen_images
  copy_seed_manual                                     ▼
                                            assemble_data  (terminal — runs allowlist scrub)

[phase 3: data_validation]                  [phase 4: build]
──────────────────────────                  ────────────────
validate_schema                             clone_template
  ▼                                           ▼
validate_hosting                            write_env_file
  (boots shop-backend on a free port,         ▼
   runs the §5.4 query suite)               start_sidecar
                                              ▼
                                            run_build_harness_loop
                                              (one harness.run_plan_exec_loop
                                               invocation; planner emits
                                               gen_theme … visual_fix; verifier
                                               set gates each task)

[phase 5: final_eval]
─────────────────────
final_eval  (advisory; never blocks the run)
```

Multi-seed runs register the four-step manual-merge sub-DAG; single-
seed runs register the `copy_seed_manual` shortcut. Phases 2–5 are
config-independent at v0.1.

The build loop's tasks (`gen_theme`, `gen_navigation`, `gen_homepage`,
`visual_fix`, …) live *inside* `run_build_harness_loop` — they're
not separate Python steps. Re-running an individual build-loop task
is the `--only gen_<task>` redo flow above.

---

## Re-runs and staleness

Re-running `shop-gen` against the same `--out-dir` is **idempotent**:
every step that is already up to date is skipped, and only stale
steps run. This is what makes Workflow 2 (re-run a specific step) and
Workflow 3 (halt at a step, then continue later) safe and cheap.

### When is a step stale?

A step is marked stale (re-run) if **any** of these are true; otherwise
it is fresh and skipped:

| # | Trigger                                                                                                            | Typical cause                                                            |
| - | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| 1 | Step id is in `force_ids`                                                                                          | You passed `--from <id>` or `--only <id>`                                |
| 2 | Any upstream step is stale                                                                                         | Cascade — re-running A re-runs everything downstream of A                |
| 3 | No state record • fingerprint is `None` • last status was `FAILED` / `RUNNING` / `PENDING`                         | First run, prior crash, prior failure (`RUNNING` left over = mid-run kill) |
| 4 | Any declared output file is missing on disk                                                                        | You deleted artifacts under `<out_dir>/`                                 |
| 5 | Any declared input file is missing, or an upstream `StepInput` has no fingerprint                                  | Seed file got moved/deleted, upstream step never ran                     |
| 6 | Recorded fingerprint ≠ freshly computed fingerprint                                                                | A seed file's bytes changed                                              |

The fingerprint is `sha256` over each declared input: file contents
for `FileInput`, upstream fingerprint for `StepInput`. Edits to seed
files therefore cascade through the DAG automatically (rows 2 + 6).

### Where state lives

`<out_dir>/.shop_gen/state.json` — per-step status, fingerprint, and
ISO-8601 timestamp. The runner writes it after every transition
(`RUNNING` on entry, `FRESH` on success, `FAILED` on exception), so a
crash mid-run is recoverable: the next invocation picks up from the
last clean checkpoint.

### Inspecting a workspace before re-running

```bash
# Per-step status table (id, phase, status, fingerprint, last ts).
uv run shop-gen --status --out-dir outputs/shops/my-shop

# Raw record — useful when you want to diff fingerprints across runs.
cat outputs/shops/my-shop/.shop_gen/state.json
```

The progress logs (see [Progress logging](#progress-logging)) also
make staleness visible per step. A re-run with one stale upstream
looks like:

```
22:01:14 shop-gen INFO: start run — out_dir=outputs/shops/my-shop seeds=1 …
22:01:14 shop-gen INFO: skip copy_seed_manual (manual_merge) — fresh
22:01:14 shop-gen INFO: skip synth_identity (data_synth) — fresh
22:01:14 shop-gen INFO: run  synth_collections (data_synth) — starting     ← stale
22:01:42 shop-gen INFO: done synth_collections (data_synth) — ok in 27.84s
22:01:42 shop-gen INFO: run  synth_navigation (data_synth) — starting       ← cascade
…
22:02:18 shop-gen INFO: end run   — ran=4 skipped=7 total=1m04.2s
```

### Subtle case: untracked file mutations

The fingerprint cascade only sees files a step has *declared* as
`FileInput` / `StepInput`. If you mutate a workspace file that no step
declares (e.g. you hand-edit `data/products.json` after Phase 2
completes), the runner has no way to detect the change and will
happily skip downstream steps. Stick to editing seeds, or use
`--from <step>` to force the cone of re-runs explicitly.

---

## Build-loop state (harness layer)

`run_build_harness_loop` is a single row in `.shop_gen/state.json`
from the pipeline's perspective, but inside it the harness drives
its own plan-then-loop state machine over many iterations, with
state persisted under `<out_dir>/runs/build/`. The two layers are
independent: the pipeline owns "did the step finish?", the harness
owns "where in the loop am I?". They meet only at the step's
return-or-raise.

### Files under `runs/build/`

| File / dir                            | Purpose                                                                |
| ------------------------------------- | ---------------------------------------------------------------------- |
| `run.json`                            | `PlanExecLoopResult` snapshot; rewritten after every iteration.        |
| `plan.md`                             | Live plan — planner writes once, executors mutate as tasks complete.   |
| `prompts/`                            | Frozen prompt copies for the run.                                      |
| `iters/plan/`                         | The single planner iteration (trajectory + plan snapshots).            |
| `iters/exec-NNNN/`                    | One per executor iteration; their count drives the next index.         |
| `artifact/manual/`                    | Seed-immutable working tree (manifest captured by `Workspace.create`). |
| `artifact/{hydrogen,data}/`           | Mutable working tree; executors edit files in place each iteration.    |

### Sources of truth

The harness derives every loop decision from the filesystem, not
from `run.json`:

| Question                                       | Source                                                |
| ---------------------------------------------- | ----------------------------------------------------- |
| Did the planner already run?                   | `iters/plan/trajectory.json` exists                   |
| What's the next exec iter index?               | `count(iters/exec-NNNN/trajectory.json) + 1`          |
| Which task does the executor pick next?        | `plan.md` — highest-priority `[ ]` task               |
| Did the prior run terminate, and how?          | `run.json.final_status`                               |
| Was an iter mid-flight at crash time?          | exec dir without `trajectory.json` → quarantined      |

`run.json` is the only file the harness writes; everything else is
derived from on-disk telemetry.

### Two-layer call flow

```
shop-gen <args>
  │
  ▼
pipeline runner          ── reads/writes .shop_gen/state.json
  │
  ▼   run_build_harness_loop is stale (RUNNING / FAILED / force_ids)?
RunBuildHarnessLoopStep.run()
  • _setup_run_dir()         (Workspace.create + pnpm install if run_dir empty)
  • _verifiers_factory()     (verifier list rebuilt every call)
  • sidecar_lifecycle()      (spawn shop-backend subprocess)
  │
  ▼
run_plan_exec_loop(force=True)
  • Workspace.open / create
  • _quarantine_partial_iters  (drop half-written exec dirs)
  • run_planner               (only if iters/plan/ is absent)
  • loop: pick PENDING task → exec → mutate plan.md → rewrite run.json
  │
  ▲
  └── returns; pipeline records the step FRESH or FAILED in state.json
```

The pipeline's `RUNNING` row for `run_build_harness_loop` is the
only visible signal of an in-flight or crashed harness run;
everything else lives one level down under `runs/build/`.

### Granularity asymmetry

|                | Pipeline (Layer 1)                  | Harness (Layer 2)                              |
| -------------- | ----------------------------------- | ---------------------------------------------- |
| Granularity    | one step                            | one iter (planner or exec-NNNN)                |
| Invalidation   | fingerprint of declared I/O         | filesystem presence (trajectories, plan.md)    |
| Code edits     | not tracked                         | not tracked                                    |
| Re-entry knob  | `--from` / `--only`                 | `force=True` (hardcoded by the step)           |

Two consequences worth knowing:

- **Editing verifier or prompt source does not invalidate
  `run_build_harness_loop`.** The next re-entry rebuilds the
  verifier list and re-loads prompts, but doesn't *trigger* one.
  Force re-entry with `--from run_build_harness_loop`.
- **Deleting a non-tail `iters/exec-NNNN/` dir corrupts the iter
  numbering.** The next iter index is `count + 1` over exec dirs
  that hold a `trajectory.json`, so punching a hole in the middle
  collides with an existing dir name. Only delete a contiguous tail.

### Common recipes

| Goal                                                  | Recipe                                                                                                                          |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Resume a crashed harness run                          | Bare re-run. The `RUNNING` step row is auto-stale; the harness's `force=True` bypasses refusal policy.                          |
| Redo one build-loop task                              | `--only <task_id>` — appends `<task>_redo_<N>` to `plan.md`, forces the step.                                                   |
| Re-enter the build phase, keep upstream artifacts     | `rm -rf runs/build/` (the step's declared output disappears → auto-stale). The step re-clones, re-installs, re-plans.           |
| Redo executor iterations, keep planner output         | Restore `plan.md` from `iters/plan/plan.after.md`; `rm -rf iters/exec-*`; restore `artifact/{hydrogen,data}/` from `<out_dir>/{hydrogen,data}/`. |
| Plumb a verifier / prompt change                      | `--from run_build_harness_loop`. No upstream is invalidated — the change is code, not data.                                     |

---

## Output layout

`out_dir` is the run workspace. Every published artifact lives at a
predictable path under it.

```
<out_dir>/
├── manual/                     # PUBLISHED — manual fed into the build loop
│   ├── manual.md
│   ├── capabilities.json
│   ├── stats.json
│   └── manifest.json
├── identity.json               # PUBLISHED — fake-brand identity (name, descriptor, tone, …)
├── data/                       # PUBLISHED — SandboxShop dataset (shop_backend §8.1)
│   ├── store.json
│   ├── products.json
│   ├── collections.json
│   ├── navigation.json
│   ├── pages.json
│   ├── policies.json
│   └── images/                 # placeholder SVGs (v0.1) or generated images (v0.2)
├── hydrogen/                   # PUBLISHED — generated Hydrogen app
├── data_validation.json        # PUBLISHED — schema + hosting check verdict
├── sidecar.json                # PUBLISHED — start_sidecar pre-flight verdict
├── final_eval.json             # PUBLISHED — advisory quality verdict (never blocks)
├── runs/
│   └── build/                  # debugging — harness run dir for Phase 4
│       ├── plan.md
│       ├── run.json
│       ├── iters/exec-NNNN/
│       └── artifact/
│           ├── hydrogen/
│           └── data/
└── .shop_gen/                  # internal — step state + cached intermediates
    ├── state.json              # per-step status, fingerprints, timestamps
    └── stage_cache/            # cached Phase 2 stage outputs
```

`ShopGenResult` (returned by `shop_arena.gen.run`) exposes typed paths to
the seven published artifacts. Inspecting the disk for partial results
is supported: `result.data_dir.exists()` etc. tells you which steps
the current run actually completed.

---

## Brand safety

Every brand-shaped string in `data/*.json` and
`hydrogen/app/**/*.{tsx,ts,css,md}` is drawn from the static
10-token allowlist at `brands/fake_brands.json`. Two enforcement
passes back this up:

- **`assemble_data`** runs the allowlist scanner over every string
  in the final dataset. Any unmatched candidate raises
  `BrandLeakError` and marks the upstream synthesis step stale —
  no silent redaction.
- **`no_brand_leak` build verifier** runs the same scanner over the
  hydrogen tree after each executor iteration. A leak fails the
  iteration and surfaces in `{{verifier_feedback}}` for the next
  retry.

See spec §5.6 for the rationale (allowlist > blocklist) and the
safe-noun list that absorbs false positives.

---

## Testing

```bash
# Replay-only — no API key, no sidecar, no Node toolchain required.
uv run pytest packages/shop_arena/tests/gen
```

Replay-only coverage includes the step DAG runner, every Phase 1–3
step against fixture LLM clients, the brand-allowlist scanner, the
build-loop driver against the
[`fixture_build_loop` cassette](../../tests/gen/cassettes/fixture_build_loop/README.md),
the full Phase 4 verifier set, and the advisory `final_eval` step.

To exercise the Phase 4 driver end-to-end against the M5 cassette:

```bash
# T5.9 — build-loop driver replay
uv run pytest packages/shop_arena/tests/gen/test_build_loop_replay.py

# T5.10 — full Phase 4 (driver + verifier set) from the M4 dataset fixture
uv run pytest packages/shop_arena/tests/gen/test_phase4_e2e_replay.py
```

Both suites run deterministically without API keys — they wire
`harness.runtimes.replay.ReplayRuntime` to the
`fixture_build_loop/` cassette and stub the sidecar / verifier
side-effects through their public injection seams (no internal
monkey-patching).

---

## Record-cassette workflow

`shop_arena.gen`'s Phase 4 replay tests run against
`harness.runtimes.replay`, so they need no network or LLM access.
The cassette lives under
`tests/gen/cassettes/<fixture_slug>/` and follows the harness
§5.6 layout: a `plan/` directory plus one `exec-NNNN/` directory
per executor iteration, each holding a `trajectory.json` and a
`workspace_after/` snapshot.

To refresh the cassette against a real `shop-backend` sidecar with
the live `pi` runtime:

```bash
# Pick the fixture slug used by tests.
export FIXTURE=fixture_build_loop

# Build the shop-backend CLI the loop step expects.
pnpm --filter @shop-gym/shop-backend build

HARNESS_RECORD=1 \
  uv run shop-gen --runtime pi \
    --out-dir packages/shop_arena/tests/gen/cassettes/$FIXTURE/_recording \
    <seed_manual_dir>
```

`HARNESS_RECORD=1` flips `harness.runtimes.replay` from pure-replay
into a record-then-write mode that delegates each iteration to the
fallback live runtime and persists `trajectory.json` +
`workspace_after/` per iteration. After a successful record:

1. Move the per-iteration cassette directories
   (`plan/`, `exec-0001/`, …) into
   `tests/gen/cassettes/$FIXTURE/`.
2. Redact API keys from any captured `iters/*/native.log` you intend
   to commit.
3. Update `tests/gen/cassettes/$FIXTURE/README.md` with the
   recording provenance.
4. Run `uv run pytest packages/shop_arena/tests/gen` to confirm
   the cassette replays cleanly.

The synthetic `fixture_build_loop` shipped with the repo is hand-
crafted (no live source) and is the canonical replay fixture for the
M5 tests. Recorded fixtures land in v0.2 alongside the live build
loop tag.

---

## Module layout

```
packages/shop_arena/src/shop_arena/gen/
├── __init__.py                  # re-exports run, ShopGenConfig, ShopGenResult, __version__
├── _version.py
├── py.typed                     # PEP 561 typing marker
├── cli.py                       # argparse → pipeline dispatch
├── pipeline.py                  # phase-aware step registry + run/status/list_steps
├── config.py                    # ShopGenConfig + ShopGenResult (pydantic v2)
├── steps/                       # base.Step, runner, state.json
├── manual_merge/                # phase 1 — capabilities, prose, stats, manifest, copy_seed
├── data_synth/                  # phase 2 — identity → assemble (incl. schema mirrors + prompts)
├── data_validation/             # phase 3 — validate_schema, validate_hosting
├── build/                       # phase 4 — env/sidecar/loop + verifiers/ + prompts/
├── final_eval/                  # phase 5 — playwright_smoke + LLM quality_judge
├── brands/                      # fake_brands.json + allowlist scanner
└── templates/
    └── hydrogen/                # vendored Hydrogen template (cloned per run)
```

## Public surface

Re-exported from `shop_arena.gen` (per spec §8.1):

- `run`, `ShopGenConfig`, `ShopGenResult`
- `__version__`

Internal sub-packages (`shop_arena.gen.build`, `shop_arena.gen.data_synth`, …)
are not part of the v0.1 public surface; their layout may change
between minor versions.
