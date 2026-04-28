# `shop_gen`

SandboxShop generation pipeline. Given one or more anonymized **Shop
Manuals** (the published output of `shop_explore`), `shop_gen` produces
a deterministic, hostable **SandboxShop**: a JSON dataset matching the
`shop_backend` Storefront-API contract *plus* a generated Hydrogen
storefront that renders against it.

- Spec: [`docs/specs/shop_arena/shop_gen.md`](../../../../docs/specs/shop_arena/shop_gen.md)
- Implementation plan: [`docs/impl/shop_gen_implementation.md`](../../../../docs/impl/shop_gen_implementation.md)
- Status: **v0.1.0** — M0–M6 landed (step DAG + manual merge + data
  synth + data validation + build harness loop + advisory final eval).
  Public surface: `run`, `ShopGenConfig`, `ShopGenResult`,
  `__version__`. v0.2 follow-ups (AI image backend, programmatic
  per-shop allowlist, hosting auto-retry) are out of scope for v0.1.

---

## Install

`shop_gen` ships as part of the `shop-arena` distribution. From the
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
| Python ≥ 3.11 + `uv`       | Always                                              | [astral.sh/uv](https://docs.astral.sh/uv/), then `uv sync`      |
| `pnpm` ≥ 9 + Node ≥ 20     | Phase 3 hosting check + Phase 4 build verifiers     | [pnpm.io/installation](https://pnpm.io/installation), then `pnpm install` at repo root |
| `shop-backend` build       | Phase 3 + Phase 4                                   | `pnpm --filter @shop-gym/shop-backend build`                    |
| `pi` CLI                   | `--runtime pi` (default) on live runs               | Internal — see `packages/harness/README.md`                     |
| `claude` CLI               | `--runtime claude_code` on live runs                | [docs.claude.com/claude-code](https://docs.claude.com/claude-code) |
| Runtime API key            | Live runs (not `replay`-only tests)                 | `ANTHROPIC_API_KEY` for `claude_code`; runtime env vars for `pi` |

The replay-only tests under `tests/shop_gen/` need none of the runtime
or sidecar prerequisites — see [Testing](#testing) below.

---

## Usage

### CLI

```bash
# Default: run every stale step. Idempotent.
uv run shop-gen <seed_dir>... --out-dir outputs/shops/my-shop

# Step-targeted re-runs
uv run shop-gen --from synth_identity   <seed>...   # rerun step + downstream
uv run shop-gen --only gen_homepage     <seed>...   # rerun a single build-loop task

# Passive controls
uv run shop-gen --status     --out-dir outputs/shops/my-shop
uv run shop-gen --list-steps

# Scale + behavior knobs
uv run shop-gen <seed>... \
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

`--from <step>` marks the named step and every downstream descendant
stale on disk and re-runs them. `--only <step>` is the build-loop
redo flag from spec §5.7.3: when invoked against a `[x]` task in
`<out_dir>/runs/build/plan.md` it appends a fresh
`<task>_redo_<N>` PENDING bullet and forces
`run_build_harness_loop` to resume — the original `[x]` is never
mutated.

### Library

```python
from pathlib import Path

from shop_gen import ShopGenConfig, run

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
needed. `shop-gen --list-steps` prints the live registry.

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
                                               gen_theme … consolidate; verifier
                                               set gates each task)

[phase 5: final_eval]
─────────────────────
final_eval  (advisory; never blocks the run)
```

Multi-seed runs register the four-step manual-merge sub-DAG; single-
seed runs register the `copy_seed_manual` shortcut. Phases 2–5 are
config-independent at v0.1.

The build loop's tasks (`gen_theme`, `gen_navigation`, `gen_homepage`,
`consolidate`, …) live *inside* `run_build_harness_loop` — they're
not separate Python steps. Re-running an individual build-loop task
is the `--only gen_<task>` redo flow above.

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
│   └── images/                 # placeholder SVGs (v0.1) or AI images (v0.2)
├── hydrogen/                   # PUBLISHED — generated Hydrogen app
├── data_validation.json        # PUBLISHED — schema + hosting check verdict
├── final_eval.json             # PUBLISHED — advisory quality verdict (never blocks)
├── runs/
│   └── build/                  # debugging — harness run dir for Phase 4
│       ├── plan.md
│       ├── iters/exec-NNNN/
│       └── artifact/hydrogen/
└── .shop_gen/                  # internal — step state + cached intermediates
    ├── state.json              # per-step status, fingerprints, timestamps
    └── stage_cache/            # cached Phase 2 stage outputs
```

`ShopGenResult` (returned by `shop_gen.run`) exposes typed paths to
the seven published artifacts. Inspecting the disk for partial results
is supported: `result.data_dir.exists()` etc. tells you which steps
the current run actually completed.

---

## Brand safety

Every brand-shaped string in `data/*.json` and
`hydrogen/app/**/*.{tsx,ts,css,md}` is drawn from the static
8-token allowlist at `brands/fake_brands.json`. Two enforcement
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
uv run pytest packages/shop_arena/tests/shop_gen
```

Replay-only coverage includes the step DAG runner, every Phase 1–3
step against fixture LLM clients, the brand-allowlist scanner, the
build-loop driver against the
[`fixture_build_loop` cassette](../../tests/shop_gen/cassettes/fixture_build_loop/README.md),
the full Phase 4 verifier set, and the advisory `final_eval` step.

To exercise the Phase 4 driver end-to-end against the M5 cassette:

```bash
# T5.9 — build-loop driver replay
uv run pytest packages/shop_arena/tests/shop_gen/test_build_loop_replay.py

# T5.10 — full Phase 4 (driver + verifier set) from the M4 dataset fixture
uv run pytest packages/shop_arena/tests/shop_gen/test_phase4_e2e_replay.py
```

Both suites run deterministically without API keys — they wire
`harness.runtimes.replay.ReplayRuntime` to the
`fixture_build_loop/` cassette and stub the sidecar / verifier
side-effects through their public injection seams (no internal
monkey-patching).

---

## Record-cassette workflow

`shop_gen`'s Phase 4 replay tests run against
`harness.runtimes.replay`, so they need no network or LLM access.
The cassette lives under
`tests/shop_gen/cassettes/<fixture_slug>/` and follows the harness
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
    --out-dir packages/shop_arena/tests/shop_gen/cassettes/$FIXTURE/_recording \
    <seed_manual_dir>
```

`HARNESS_RECORD=1` flips `harness.runtimes.replay` from pure-replay
into a record-then-write mode that delegates each iteration to the
fallback live runtime and persists `trajectory.json` +
`workspace_after/` per iteration. After a successful record:

1. Move the per-iteration cassette directories
   (`plan/`, `exec-0001/`, …) into
   `tests/shop_gen/cassettes/$FIXTURE/`.
2. Redact API keys from any captured `iters/*/native.log` you intend
   to commit.
3. Update `tests/shop_gen/cassettes/$FIXTURE/README.md` with the
   recording provenance.
4. Run `uv run pytest packages/shop_arena/tests/shop_gen` to confirm
   the cassette replays cleanly.

The synthetic `fixture_build_loop` shipped with the repo is hand-
crafted (no live source) and is the canonical replay fixture for the
M5 tests. Recorded fixtures land in v0.2 alongside the live build
loop tag.

---

## Module layout

```
packages/shop_arena/src/shop_gen/
├── __init__.py                  # re-exports run, ShopGenConfig, ShopGenResult, __version__
├── _version.py
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

Re-exported from `shop_gen` (per spec §8.1):

- `run`, `ShopGenConfig`, `ShopGenResult`
- `__version__`

Internal sub-packages (`shop_gen.build`, `shop_gen.data_synth`, …)
are not part of the v0.1 public surface; their layout may change
between minor versions.
