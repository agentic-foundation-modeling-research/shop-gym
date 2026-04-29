# Resume Support for Plan + Exec Runs (`packages/harness`)

Status: **Implemented** · Version: **0.1**
Owners: ShopGym

> An optional resume path that lets a partial run continue in place
> instead of paying for the planner and the already-completed executor
> tasks again. Builds on the existing append-only telemetry layout and
> the `[x]`/`[ ]` markers the parser already enforces.

---

## 1. Overview

A `run_plan_exec_loop` invocation today is "all or nothing". If the
process dies mid-run — caller `Ctrl+C`, executor `TIMEOUT`, runtime
crash, OOM — the next invocation starts from scratch in a new
timestamped `run_dir`: the planner re-runs (often the most expensive
step in a `shop_arena.explore` run, e.g. ~$5 + 6 min for `example-shop.com`), and
every `[x]` task is replayed.

The state needed to skip those steps is already on disk. `plan.md`
already encodes which tasks are `[x]`; `iters/<id>/trajectory.json` is
already immutable; `telemetry.recovery.reconstruct(run_dir)` already
rebuilds `PlanExecLoopResult` from the append-only files. This spec
adds one entry point that opens an existing `run_dir` instead of
materialising a new one, validates the workspace is coherent, and
re-enters the loop at the next available executor iteration.

Two design choices keep the surface narrow:

- **Same `run_dir`, dense numbering.** Resume mutates the existing
  workspace rather than copying state into a fresh one. Each iter
  directory still corresponds to exactly one subprocess; partial
  iterations are quarantined, not blended.
- **Plan + prompts are the resume identity.** A run can only be
  resumed under byte-identical `AGENTS.md`, `prompts/planner.md`,
  `prompts/execute.md`, and seed manifest. The planner contract
  embeds the prompt; resuming under a different prompt would
  silently mix two policies into one task list.

---

## 2. Terminology

- **Healthy iter dir** — `iters/<id>/` containing `trajectory.json`
  and (for executors) `metadata.json` + `checks/protocol.json`. These
  are the iterations the harness has fully recorded; `recovery.py`
  already consumes only this shape.
- **Partial iter dir** — `iters/<id>/` that exists on disk but is
  missing `trajectory.json`. Created when a process dies between
  `iter_dir.mkdir(parents=True)` (`loop.py:232`) and `_write_trajectory`
  (`loop.py:251`). Today the harness loop never reads these; with the
  T2.4-followup fix in `loop.py` they no longer count toward
  `_exec_iter_count`, but the directory remains.
- **Resume identity** — the tuple `(AGENTS.md bytes, planner prompt
  bytes, execute prompt bytes, seed manifest)`. Two runs with the
  same identity are continuation-compatible; otherwise they are
  different runs sharing a directory and resume must refuse.
- **Quarantine** — the act of renaming `iters/<id>/` to
  `iters/<id>.aborted/` with a sentinel marker so the next attempt
  can reuse `<id>` cleanly while preserving the partial native log
  for debugging.

---

## 3. Current Status

- Implemented in `packages/harness`:
  - `Workspace.open(run_dir, config=...)` validates the resume identity
    tuple (`AGENTS.md`, planner prompt, execute prompt, and seed
    manifest) and re-adopts an existing workspace.
  - `run_plan_exec_loop(config, runtime, *, force=False)` infers fresh
    vs. resume mode from `config.run_dir`, skips the planner when
    `iters/plan/trajectory.json` exists, reconstructs executor counters
    from `iters/`, quarantines partial executor directories, and grants
    `max_iters` as additional budget for the resumed attempt.
  - `.harness/seed_manifest.json` is persisted for seeded runs so the
    seed-immutability check remains enforceable on resume.
  - `config_snapshot.resume_history` is appended in `run.json` once per
    fresh or resumed attempt.
  - Resume refusal is implemented for prior bad terminal states
    (`protocol_violation`, `invalid_plan`, `runtime_error`, and
    unexpected statuses); `force=True` overrides the refusal gate.
- Implemented in `shop_arena.explore`:
  - Pointing `shop-explore --out` at an existing run directory enters
    resume mode.
  - The CLI reads prior `run.json` values for `runtime`, `model`,
    `max_iters`, and `timeout` when omitted, validates URL/runtime
    compatibility, and forwards `--force-resume` to the harness.
- Tests cover workspace identity mismatches, seed-manifest resume,
  planner-skip behavior, partial-dir quarantine, bad-state refusal,
  `force=True`, budget-exhausted continuation, and `shop-explore`
  resume argument handling.

---

## 4. Desired Status

### 4.1 I/O contract

Mode is inferred from `config.run_dir`'s on-disk state — there is
no `resume` flag on the public surface.

- **Fresh run.** `config.run_dir` does not exist, or exists but is
  empty. The harness runs `Workspace.create` exactly as today and
  drives the loop from scratch. Behavior is byte-identical to
  today aside from §5.1's seed-manifest persistence and §5.7's
  `resume_history` field.
- **Resume.** `config.run_dir` exists and is non-empty. The harness
  runs `Workspace.open(run_dir, config)` instead of
  `Workspace.create`, validates resume identity, and re-enters the
  loop:
  - The workspace must contain at minimum `AGENTS.md`,
    `prompts/planner.md`, `prompts/execute.md`, `plan.md`, and
    `iters/`. Missing files are a hard error
    (`ResumeMismatchError(field=...)`).
  - On identity mismatch the harness raises
    `ResumeMismatchError(field, run_dir, prior, current)` without
    mutating the workspace.
  - The harness skips planner work if `iters/plan/trajectory.json`
    exists; otherwise it runs the planner exactly as a fresh run
    would.
  - The harness quarantines any partial executor iter dir before
    spawning the next iteration.
  - The executor loop continues until the existing terminal
    conditions fire (`COMPLETED`, `BUDGET_EXHAUSTED`,
    `PROTOCOL_VIOLATION`, `INVALID_PLAN`, `TIMEOUT`, `RUNTIME_ERROR`).
  - `max_iters` is interpreted as the *additional* executor budget
    for this attempt. The total executor count across attempts is
    `prior_exec_count + new_attempt_iters`; only the latter counts
    against `max_iters`. A caller who wants to bound the lifetime
    total uses `max_iters = total - prior_exec_count`.

A `force: bool = False` keyword on `run_plan_exec_loop` is the only
new argument; it overrides §5.5's refusal policy for bad-state
prior runs and is also exposed as `--force-resume` on the CLI. It
has no effect when the resume identity does not match — identity
is non-overridable.

The implication for callers: pointing `--out` at an existing
`run_dir` *is* the resume affordance. Today that path raises
`WorkspaceError("run_dir is not empty: …")`; under this spec it
runs in resume mode (or refuses with `ResumeMismatchError` /
the §5.5 policy).

### 4.2 Success criteria

- **SC-R1.** A run that times out at `exec-0001` can be resumed;
  the second attempt does not re-run the planner, starts at the
  same `selected_task_id`, and the final `run.json` reports
  `plan_iter_count=1`, `exec_iter_count` equal to the count of
  healthy executor dirs at completion, and `trajectory_paths`
  ordered planner-then-executors with no gaps.
- **SC-R2.** A run completed under a different `AGENTS.md` /
  prompt / seed cannot be resumed: `ResumeMismatchError` fires
  before any subprocess is spawned and no file is written under
  `run_dir`.
- **SC-R3.** A run completed (`final_status=completed`) is a
  resume no-op: the loop records no new iterations and returns a
  result equivalent to `reconstruct(run_dir)`.
- **SC-R4.** A run resumed after `protocol_violation` or
  `invalid_plan` refuses by default and surfaces a one-line
  diagnostic. (`--force-resume` is out of scope for v0.1.)
- **SC-R5.** The seed-immutability check continues to fire on
  every resumed iteration. Mutations introduced *between* attempts
  (caller editing files in the seeded subtree by hand) are caught
  on the first iteration of the resumed attempt, not silently.

---

## 5. Proposal

### 5.1 Architecture

Resume is a thin entry-mode change on top of the existing loop. No
new state machine; the existing `_LoopState` is reused. Two modules
grow:

- `harness.workspace` gains `Workspace.open(run_dir, *, config)`
  that validates resume identity and returns a `Workspace` whose
  stable surfaces already exist on disk.
- `harness.loop` gains an entry-mode branch in `run_plan_exec_loop`:
  when `config.run_dir` is non-empty, build the workspace via
  `Workspace.open` instead of `Workspace.create`, reconstruct the
  loop counters from `iters/` (mirroring `recovery._scan_iter_dirs`),
  quarantine any partial executor dir, skip the planner if its
  trajectory is on disk, and call `state.run_executor_loop()`
  directly.

The seed manifest must outlive the original process, so a third
small change is required:

- `Workspace.create` writes `<run_dir>/.harness/seed_manifest.json`
  immediately after `snapshot_seed` builds it. `Workspace.open`
  reads it back. The `.harness/` prefix keeps internal harness
  state out of `artifact/` (and therefore out of the seeded subtree
  by construction).

### 5.2 Resume identity

Validated in `Workspace.open(run_dir, config)` in this order; the
first mismatch raises and the function returns no value:

1. `AGENTS.md` bytes equal `config.agents_md` bytes.
2. `prompts/planner.md` bytes equal `config.prompts.planner` bytes.
3. `prompts/execute.md` bytes equal `config.prompts.execute` bytes.
4. If `config.artifact_seed_dir` is set, the freshly-computed
   manifest from `config.artifact_seed_dir` equals
   `<run_dir>/.harness/seed_manifest.json`. If
   `config.artifact_seed_dir` is `None` *and* a manifest file
   exists, that is also a mismatch (the prior run was seeded;
   resuming unseeded would defeat the immutability check).
5. `plan.md` parses without `InvalidPlanError`. (Resuming a
   broken plan refuses by default — see §5.5.)

The error type is `ResumeMismatchError(field, run_dir, prior_repr,
current_repr)`. Field names are stable strings (`agents_md`,
`prompts.planner`, `prompts.execute`, `seed_manifest`, `plan_md`)
so callers and tests can match without parsing free-text messages.

### 5.3 Loop-state reconstruction

`Workspace.open` returns a workspace; `_LoopState` is then
constructed with counters reconstructed from disk:

```python
plan_exists = (workspace.iters_dir / PLAN_ITER_ID / "trajectory.json").is_file()
exec_dirs = sorted(
    d for d in workspace.iters_dir.iterdir()
    if d.is_dir()
    and _EXEC_ITER_ID_RE.match(d.name)
    and (d / "trajectory.json").is_file()
)
state._plan_iter_count = 1 if plan_exists else 0
state._exec_iter_count = len(exec_dirs)
state._trajectory_paths = (
    [f"iters/{PLAN_ITER_ID}/trajectory.json"] if plan_exists else []
) + [f"iters/{d.name}/trajectory.json" for d in exec_dirs]
```

This is exactly the shape `recovery._scan_iter_dirs` produces. The
two paths share a private helper to avoid drift.

The planner branch in `run_plan_exec_loop` becomes:

```python
if not state.plan_already_recorded() and not state.run_planner():
    return state.finalize()
state.run_executor_loop()
return state.finalize()
```

where `plan_already_recorded` checks `_plan_iter_count > 0`.

### 5.4 Quarantine for partial executor dirs

Before `run_executor_loop` enters its first iteration of the
resumed attempt, `_quarantine_partial_iters` runs once:

- For every `iters/<exec_id>/` whose `trajectory.json` is missing,
  rename the directory to `iters/<exec_id>.aborted-<N>/` where
  `<N>` is the smallest integer that makes the destination unique.
- Write a `aborted.txt` sentinel inside the quarantined directory
  containing the resume timestamp and the prior `final_status`
  read from the in-memory `_LoopState` (not from `run.json`, which
  may not have been rewritten).

The numbering invariant becomes:

- `iters/exec-NNNN/` is healthy (or about to be written).
- `iters/exec-NNNN.aborted-K/` is a quarantined partial.

`recovery._scan_iter_dirs` already filters by
`(d / "trajectory.json").is_file()` so quarantined directories are
ignored by the recovery path with no change.

### 5.5 Refusal policy

By default `Workspace.open` refuses if the prior `final_status`
implies the workspace is in a bad state:

- `protocol_violation`: refuse. The plan or seed has an enforced
  invariant violation; rerunning the executor will hit the same
  check.
- `invalid_plan`: refuse. `plan.md` does not parse; resuming would
  re-run protocol checks against a broken plan.
- `runtime_error`: refuse by default. The runtime threw an
  unexpected exception and the workspace state may be inconsistent
  with the on-disk plan. Allow override via a `force=True` keyword
  on `run_plan_exec_loop` (CLI: `--force-resume`).
- `timeout`, `budget_exhausted`: allow. These are clean "ran out
  of clock / budget" failures and the workspace is consistent.
- `completed`: allow as no-op (executor loop exits immediately
  via `select_next is None`).

The prior `final_status` is read from the most recent `run.json`.
If `run.json` is missing or malformed, fall back to
`reconstruct(run_dir).final_status`. If both fail, refuse.

### 5.6 CLI surface

- Resume is opted into by pointing `--out` at an existing,
  non-empty run directory; there is no separate `--resume` flag.
  When the CLI detects the directory is non-empty, it reads the
  prior config from `run.json` (URL, runtime, max_iters, timeout)
  and uses those values to fill any unspecified flags before
  constructing the `ExploreConfig`.
- `--max-iters` and `--timeout` may be re-specified to bump the
  resumed attempt's budget; passing neither re-uses the prior
  values.
- `--force-resume` (boolean) propagates to
  `run_plan_exec_loop(force=True)` for §5.5 overrides. It has no
  effect on a fresh run.
- `--url` and `--runtime` must match `run.json` if supplied; a
  mismatch is a CLI-level error before any harness call. The
  motivating use case is "I forgot to add `--out` last time and
  the process died" — the URL and runtime are already what the
  caller wanted; they only need `--out <run_dir>` to continue.

### 5.7 `run.json` provenance

Extend `run.json`'s `config_snapshot` with one new optional field:

```json
"resume_history": [
  {"started_at": "...", "ended_at": "...", "final_status": "timeout"},
  {"started_at": "...", "ended_at": "...", "final_status": "completed"}
]
```

Each entry records one attempt. The list is appended to (never
rewritten in place) by reading the prior `run.json` on resume,
appending one entry, and writing the rewritten file atomically as
today. A fresh run produces a single-entry history.

This is the only persistent change to `run.json`; iteration counts
and trajectory paths continue to be the union across all attempts
since the iter directories are dense.

### 5.8 Determinism guarantees

- A run that completes on a single attempt produces identical
  `run.json`, `plan.md`, and `iters/` content as today, except for
  the new single-entry `resume_history`.
- A run that completes across N attempts has the same `iters/`
  content as a single-attempt run that performed the same task
  selection sequence. Quarantined `*.aborted-*/` directories are
  the sole on-disk difference and are explicitly marked.

---

## 6. Alternative

**A. Copy-forward: every resume creates a new `run_dir`.** Reject.
On resume, copy `iters/`, `plan.md`, `artifact/` into a new
timestamped `run_dir` and continue there. Pros: each `run_dir` still
represents one attempt; no in-place mutation. Cons: doubles disk
usage on each resume (native logs are large — ~330 KB per
iteration in the motivating failure), breaks the simple "one shop
+ one run = one path" mental model, and forces the caller to
chase the latest path. Approach A is strictly cheaper and equally
deterministic given the §5.7 history field.

**B. External workaround using existing primitives.** Reject as
the long-term answer; document as the short-term mitigation.
Today a caller can:

1. Read `<prior>/plan.md` and `<prior>/artifact/`.
2. `mkdir <new>`, copy plan.md into it, then run with
   `--out <new>` and a planner prompt that says "if `plan.md`
   already has tasks, do not rewrite it".

This works only by accident: the planner contract makes no
no-op-on-existing-plan promise, and the seeded subtree of the
prior run is not the seed of the new run, so the immutability
check would either need to be disabled or the prior `prefetch/`
re-supplied as `artifact_seed_dir`. Approach A makes the
guarantees first-class.

**C. In-process retry inside the runtime.** Reject. Move the
retry budget *inside* the runtime (e.g.
`ClaudeCodeRuntime(retry=2)`). Pros: zero harness changes. Cons:
masks the iteration boundary from the harness, defeats per-iter
telemetry, and only addresses transient failures — not
process-death failures, which is the motivating case.

**D. Always allow resume, never validate identity.** Reject.
Cheaper to implement, but invisibly mixes plan policies when a
caller bumps `AGENTS.md` between attempts. The §5.2 identity
check is the price of safe in-place resume.

---

## 7. Milestones

**M1 — Persist seed manifest.** Done. `Workspace.create` writes
`<run_dir>/.harness/seed_manifest.json` after `snapshot_seed`.
`Workspace.open` is not added yet; this milestone is
forward-compatibility plumbing only. No behavior change for
existing flows. Tests cover: file written iff `artifact_seed_dir`
is set, manifest round-trips, `.harness/` is excluded from the
seeded-subtree scan.

**M2 — `Workspace.open(run_dir, config)` and identity check.** Done.
Constructor that validates the §5.2 identity tuple and returns a
populated `Workspace`. `ResumeMismatchError` exception type with
typed fields. No loop wiring yet. Tests cover: each mismatch
field, missing files, missing seed manifest when seeded,
`InvalidPlanError` propagation.

**M3 — `run_plan_exec_loop(config, runtime, *, force=False)` with
mode inferred from `config.run_dir`.** Done. Loop-state reconstruction
from `iters/`, planner-skip branch, `_quarantine_partial_iters`
helper, refusal policy from §5.5. Integration tests cover:
resume-after-timeout continues at next exec id;
resume-after-completed is a no-op; resume after
`protocol_violation` refuses by default; `force=True` overrides;
quarantined `*.aborted-*/` directory is created and contains
the partial native log.

**M4 — `shop-explore --out <existing_run_dir>` resume path and
`run.json` history.** Done. Prior-config readback from `run.json` when
`--out` points at a non-empty directory. `--force-resume` flag.
Append-only `resume_history` extension to the `run.json`
snapshot. README + `AGENTS.md` index updates.

**M5 — Release docs/versioning.** Partially done. The code is present
in the workspace and the parent spec now cross-links the extension.
Package changelog/version updates should be handled with the next
release cut.

---

## 8. Appendix

### 8.1 Public surface (informative)

- **New types**: `ResumeMismatchError`.
- **New functions**: `Workspace.open(run_dir, *, config)`.
- **Changed signatures**: `run_plan_exec_loop` gains
  `force: bool = False`. Mode (fresh vs resume) is inferred from
  `config.run_dir`'s on-disk state — there is no `resume`
  keyword.
- **Changed semantics**: `Workspace.create(run_dir, ...)` continues
  to refuse a non-empty `run_dir`; the new `Workspace.open` is
  what the loop calls in resume mode.
- **No new `FinalStatus`.** Resume reuses the existing terminal
  values.
- **No new telemetry file** under `iters/`. The
  `<run_dir>/.harness/seed_manifest.json` and `*.aborted-*/`
  directories are the only on-disk additions.
- **Backward compatibility.** A `run_dir` produced by harness
  ≤0.2.0 (no `seed_manifest.json` on disk) cannot be resumed if
  it was seeded — `Workspace.open` raises `ResumeMismatchError`
  on the `seed_manifest` field. This is intentional: it prevents
  silent drift across a version change. Unseeded runs from
  ≤0.2.0 resume cleanly.

### 8.2 References

- Parent spec:
  [plan_exec_loop.md](plan_exec_loop.md), specifically
  [§5.4 Memory model](plan_exec_loop.md#54-memory-model) (defines
  the file tiers resume relies on),
  [§5.5 Plan file protocol](plan_exec_loop.md#55-plan-file-protocol-planmd)
  (the `[x]`/`[ ]` markers that make task-skip free), and
  [§5.7 Telemetry](plan_exec_loop.md#57-telemetry) (the
  reconstruct-from-disk guarantee resume builds on).
- Sibling: [seed_immutability.md](seed_immutability.md). The seed
  check is what forces §5.1 to persist the manifest; resume is
  what forces the persistence to actually be tested.
- Recovery utility used as the read-only reference implementation
  for state reconstruction: `packages/harness/src/harness/telemetry/recovery.py`.
- Motivating failure: `outputs/shop_manuals/example-shop.com/20260426T061928Z-0178ea07/`
  (planner clean, `exec-0001` SIGTERM'd at 600 s timeout).

### 8.3 Out of scope

- **Mid-run plan rewrite.** Resuming with a *different*
  `prompts/planner.md` and asking the harness to merge the
  refined plan with the in-flight `[x]` markers. Not v0.1.
- **Cross-host resume.** A `run_dir` produced on machine A
  resumed on machine B. v0.1 assumes the absolute paths inside
  `trajectory.json` (`tool_result` outputs may embed them) are
  not consumed; if a future caller needs path independence, that
  is a separate spec.
- **Per-task resume.** `--resume-task <id>` to re-run a specific
  task that landed `[x]` but produced bad output. The current
  parser treats `[x]` as terminal; reopening would require
  loosening invariant 4 of `plan_exec_loop §5.5`. Defer until a
  concrete caller asks.
- **Parallel resume.** Two processes resuming the same `run_dir`
  concurrently. v0.1 has no `run_dir` lock; callers are
  responsible for serialising attempts. A `flock`-based guard is
  a candidate for a follow-up spec.
- **Resume of `runtime_error` without `--force-resume`.** Allowed
  only via the override; making it the default would risk
  resuming over a workspace whose plan/seed state is undefined.
