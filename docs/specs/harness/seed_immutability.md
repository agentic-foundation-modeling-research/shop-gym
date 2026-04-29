# Seed Immutability Protocol Check (`packages/harness`)

Status: **Implemented in `harness` 0.2.0** · Version: **0.1**
Owners: ShopGym

> A harness-owned, deterministic, post-iteration check that detects
> mutation, deletion, or extension of files copied from
> `artifact_seed_dir` into `run_dir/artifact/`. Closes the silent
> corruption gap that today lets a drifted-CWD agent overwrite the
> seed with no error signal.

---

## 1. Overview

The plan-exec harness already supports a caller-provided seed
(`PlanExecLoopConfig.artifact_seed_dir`). The harness copies that
directory into `run_dir/artifact/` before the planner runs, and the
parent spec ([plan_exec_loop §5.4](plan_exec_loop.md#54-memory-model))
calls those copied files "stable" — i.e. callers do not write inside
`run_dir` after the run starts and agents are expected to leave the
seed alone.

Today the harness does not enforce that. The caller's `AGENTS.md` is
the only line of defense, and it is advisory. A drifted agent that
writes inside the seeded subtree is silently allowed to corrupt its
own input.

This spec adds one harness-owned protocol check, run after every
iteration, that catches the violation deterministically and aborts the
run with the existing `PROTOCOL_VIOLATION` final status.

---

## 2. Terminology

- **Seed manifest** — a `{posix_relpath: sha256_hex}` fingerprint of
  every regular file copied from `artifact_seed_dir` into
  `run_dir/artifact/` at workspace creation time.
- **Seeded subtree** — the union of top-level entries copied from
  `artifact_seed_dir`. If the seed contains `prefetch/` and
  `templates/`, both subtrees are seeded; everything else under
  `artifact/` is not.
- **Seed violation** — any post-iteration deviation from the manifest
  *within the seeded subtree*: a mutated file, a deleted file, or a
  newly created path. Violations outside the seeded subtree are
  ignored by this check.

---

## 3. Current Status

- Seed copy is implemented:
  `packages/harness/src/harness/workspace.py:140-141` calls
  `_copy_tree_into(config.artifact_seed_dir, ws.artifact_dir)`.
- After the copy, the seeded subtree is treated like any other
  directory under `artifact/`. No fingerprinting, no diff, no
  enforcement.
- `run_protocol_checks`
  (`packages/harness/src/harness/plan/protocol.py`) inspects only
  `plan.md` invariants and runs only after executor iterations
  (`loop.py:233`). The planner phase has no protocol check at all.
- Observed failure: a planner iteration (`shop_arena.explore`,
  `outputs/shop_manuals/example-shop.com/20260426T051155Z-0178ea07/iters/plan/`)
  ran for ~10 minutes and 60 turns, mutated the seeded `prefetch/`
  subtree by `mkdir -p artifact/evidence/_planner/{snapshots,screenshots}`
  + saving Playwright snapshots there, and left `plan.md` empty. The
  harness reported no error; the corruption was discovered only by
  manual inspection.

---

## 4. Desired Status

### 4.1 I/O contract

- After every iteration (planner *and* executor), the harness verifies
  that the seeded subtree under `run_dir/artifact/` is byte-identical
  to its run-start manifest.
- If `config.artifact_seed_dir is None`, the check is a no-op.
- Violations are recorded in
  `iters/<iter_id>/checks/protocol.json` using the existing
  `ProtocolCheckResult.violations: tuple[str, ...]` shape; no schema
  change.
- The first such violation aborts the run with
  `FinalStatus.PROTOCOL_VIOLATION`, mirroring the existing
  plan-protocol abort path.

### 4.2 Success criteria

- Replay regression test reproducing the observed failure (planner
  `mkdir`/write inside the seeded subtree) terminates with
  `final_status == "protocol_violation"` and at least one
  `seed_extended:` violation string in `protocol.json`.
- A run with `artifact_seed_dir=None` is byte-for-byte equivalent to
  today's behavior (no manifest, no extra files, no extra protocol
  output).
- The existing toy + cassette suites continue to pass without
  modification, since none of them mutate seeded paths.

---

## 5. Proposal

### 5.1 Architecture

- A new module `packages/harness/src/harness/seed.py` owns the
  manifest and the check function. It does not depend on `plan/`;
  `plan/protocol.py` continues to own `plan.md`-shaped checks.
- `Workspace.create` builds the manifest immediately after
  `_copy_tree_into` and stores it on the workspace handle.
- The loop runs the seed check after every iteration. Where a
  plan-level `ProtocolCheckResult` already exists (executor), the seed
  violations are merged into the same result so each iteration writes
  exactly one `protocol.json`.

### 5.2 Manifest format

A frozen value type:

```python
@dataclass(frozen=True, slots=True)
class SeedManifest:
    files: Mapping[PurePosixPath, str]   # relpath → sha256 hex
    seeded_roots: frozenset[PurePosixPath]  # top-level entries copied
                                            # from artifact_seed_dir
```

- `files` keys are POSIX relpaths under `run_dir/artifact/`,
  computed at copy time.
- `seeded_roots` is the set of top-level names in `artifact_seed_dir`.
  It bounds the post-iteration scan: only paths whose first segment is
  in `seeded_roots` are inspected.
- Symlinks inside `artifact_seed_dir` are rejected at workspace
  creation. Today's `_copy_tree_into` follows them via
  `shutil.copytree` / `copy2`; the silent expansion is incompatible
  with stable fingerprinting. (See §6 for the alternative considered.)

### 5.3 Diff semantics

Given the manifest `M` and a post-iteration walk `S` over the seeded
subtree:

- `seed_mutated: <relpath>` — relpath in both, sha256 differs.
- `seed_deleted: <relpath>` — relpath in `M`, missing from `S`.
- `seed_extended: <relpath>` — relpath in `S`, not in `M`, and its
  first path segment is in `seeded_roots`.

Strings are stable and grep-friendly so downstream tooling and tests
can match on prefix.

### 5.4 Integration points

- `Workspace.create` — after `_copy_tree_into`, build and store
  `seed_manifest: SeedManifest | None` on the `Workspace`.
- `loop.run_planner` (`loop.py:117-175`) — after
  `snapshot_plan(plan.after.md)`, if `seed_manifest is not None` run
  `check_seed(...)`, write `iters/plan/checks/protocol.json`, and
  abort with `PROTOCOL_VIOLATION` on failure. The planner phase
  currently writes no `protocol.json`; this becomes its first.
- `loop._run_one_executor` (`loop.py:204-256`) — call `check_seed`
  alongside the existing `run_protocol_checks`, union the violation
  tuples into a single `ProtocolCheckResult`, write one `protocol.json`.
  The existing abort wiring (`loop.py:250-253`) handles failure
  unchanged.

### 5.5 Policy decisions

These are spec-level decisions, not config knobs:

a. **Strict by default.** Any addition inside a seeded subtree is a
   violation, not just mutations of existing files. Rationale: matches
   the "stable; immutable during a run" wording in
   [plan_exec_loop §5.4](plan_exec_loop.md#54-memory-model); catches
   the observed bug; cheap to relax later by introducing a per-caller
   flag if a real use case appears.
b. **Scope limited to the seeded subtree.** Paths under `artifact/`
   that are not under any `seeded_root` are not inspected.
   [Plan_exec_loop §5.4](plan_exec_loop.md#54-memory-model) explicitly
   grants agents "full access" to `artifact/`; this check must not
   silently narrow that contract.
c. **No caller-specific naming.** "prefetch" never appears in
   harness code. The check generalizes over `artifact_seed_dir` as
   declared by `PlanExecLoopConfig`.

---

## 6. Alternative

**A. PreToolUse hook intercepting `Write`/`Edit` paths.** Rejected for
v0.1. Requires per-runtime hook plumbing (Claude Code settings, `pi`
config) and overlaps directly with the OpenClaw-style hooks listed as
future work in
[plan_exec_loop §8.2](plan_exec_loop.md#82-future-directions-non-blocking).
Also loses the after-the-fact violation log this proposal produces.

**B. Filesystem-level read-only enforcement** (e.g. `chmod -w` on the
seeded subtree). Rejected: opaque failure surface for the agent (the
write fails with a generic OS error, no harness-shaped violation
string, no entry in `protocol.json`); macOS/Linux ACL differences
make this brittle.

**C. Resolve symlinks during seed copy.** Rejected. Following symlinks
would expand the manifest beyond the literal `artifact_seed_dir` tree,
making "what counts as seed" unclear. Rejecting symlinks at
`Workspace.create` keeps the manifest scope explicit; callers who need
referenced files should copy them into the seed dir.

---

## 7. Milestones

**M1 — Manifest and check function.** `harness/seed.py` with
`SeedManifest`, `snapshot_seed(artifact_dir, seeded_roots)`, and
`check_seed(manifest, artifact_dir, *, iter_id) -> ProtocolCheckResult`.
Unit tests cover: unchanged, mutated, deleted, extended, missing seed
(no-op), symlink-in-seed (rejection at snapshot time).

**M2 — Workspace integration.** `Workspace.create` builds and stores
`seed_manifest`; `Workspace.seed_manifest` property exposed. Symlink
rejection wired into the copy path. Tests cover the new property and
the symlink error.

**M3 — Loop wiring.** Planner and executor both invoke `check_seed`;
planner writes its first `iters/plan/checks/protocol.json`; executor
merges seed violations into the existing `ProtocolCheckResult`.
Replay regression test reproduces the observed bug (drifted CWD →
`mkdir`/write inside seed) and asserts terminal `protocol_violation`.

**M4 — v0.2.0.** Bump harness to `0.2.0` because runs that previously
silently corrupted the seed now abort. CHANGELOG entry, parent-spec
cross-link, README index update.

---

## 8. Appendix

### 8.1 Public surface (informative)

- **Types**: `SeedManifest`.
- **Functions**: `snapshot_seed`, `check_seed`.
- **Workspace surface**: `Workspace.seed_manifest: SeedManifest | None`.
- **No new `FinalStatus`.** Existing `PROTOCOL_VIOLATION` covers all
  seed-violation aborts.
- **No new telemetry file.** Violations land in the existing
  `iters/<iter_id>/checks/protocol.json`.

### 8.2 References

- Parent spec: [plan_exec_loop.md](plan_exec_loop.md), specifically
  [§5.4 Memory model](plan_exec_loop.md#54-memory-model) (defines
  `artifact_seed_dir`) and
  [§5.8 Executor self-check, verifiers, and protocol checks](plan_exec_loop.md#58-executor-self-check-verifiers-and-protocol-checks)
  (the slot this check fills).
- Failure trace motivating the spec: planner iteration `iters/plan/`
  in run dir `outputs/shop_manuals/example-shop.com/20260426T051155Z-0178ea07/`,
  log lines 19 (`cd` into seeded subtree), 104 (`mkdir -p
  artifact/evidence/_planner/...` resolving inside the seed), 110
  (Playwright snapshot saved into the seed). All three writes were
  silently accepted.

### 8.3 Out of scope

- Hooks-style PreToolUse interception of agent tool calls (deferred
  to [§8.2 of the parent spec](plan_exec_loop.md#82-future-directions-non-blocking)).
- Validation of writes *outside* the seeded subtree (e.g. enforcing
  the broader "agents only write under `artifact/parts/` and
  `artifact/evidence/`" rule from the `shop_arena.explore` AGENTS.md). That
  is a caller-domain rule, not a harness invariant; if a future spec
  promotes it, it lives in a separate harness check or in
  caller-side `protocol_check.json` callbacks.
- Per-caller relaxation flags (e.g. "this seed dir is extensible").
  Not introduced until a concrete caller needs it.
