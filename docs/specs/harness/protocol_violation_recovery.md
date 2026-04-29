# Protocol-Violation Recovery (`packages/harness`)

Status: **Implemented** · Version: **0.1**
Owners: ShopGym

> Converts an executor-phase protocol violation from a run-terminal
> failure into a per-task BLOCKED-and-continue recovery, so a single
> badly-behaved iteration does not drop the rest of the canonical
> task list.

---

## 1. Overview

`run_protocol_checks`
(`packages/harness/src/harness/plan/protocol.py`) inspects the
post-iteration `plan.md` snapshot and reports five classes of
violation: duplicate task ids, selected task not terminal,
DONE-task resurrection, non-selected newly terminal, and added task
not PENDING. Today any violation maps to ``FinalStatus.PROTOCOL_VIOLATION``
and `run_plan_exec_loop` returns immediately
(`packages/harness/src/harness/loop.py:472-475`).

The canonical example from the recent ``mock_cookware`` build:
``gen_product`` exec-0009 ran for 8 minutes, exhausted its turn budget
mid-debug, and exited cleanly without flipping its checkbox. Protocol
caught the *selected_terminal* violation. The harness terminated the
run; ``gen_cart_search``, ``gen_info_pages``, and ``visual_fix`` were
never attempted, and the build pipeline jumped to final_eval with a
mostly-untouched Hydrogen tree.

This spec mirrors the existing TIMEOUT recovery: when a single
executor iteration trips protocol, the harness restores ``plan.md``
to its pre-iteration state, force-marks the selected task ``[!]``
BLOCKED with a ``protocol_violation:`` note, adds the task to a
runner-local skip set, and continues the loop. Other tasks proceed
normally.

The planner phase keeps its terminal protocol_violation behaviour:
a planner that fails protocol cannot be recovered without
re-planning, and resuming an unrecoverable plan_dir is a manual
operator decision.

---

## 2. Terminology

- **Skipped task** — a task id the in-flight loop refuses to select
  again (TIMEOUT or protocol violation). Skip is runner-local, not
  persisted; a future resume retries the task.
- **Force-block** — the harness rewriting a task line in ``plan.md``
  to ``[!] <id>`` BLOCKED with a synthesized note. Used only as part
  of protocol-violation recovery.
- **Plan restoration** — copying ``plan.before.md`` (snapshot taken
  before the executor ran) back to ``plan.md`` to undo any plan
  mutation the executor performed.

---

## 3. Current Status

- Executor-phase recovery is implemented in
  `packages/harness/src/harness/loop.py`:
  - TIMEOUT quarantines the partial iter dir to
    `iters/<id>.aborted-<N>/`, adds the task id to the in-flight skip
    set, leaves the task PENDING in `plan.md`, latches TIMEOUT
    precedence, and continues.
  - PROTOCOL_VIOLATION writes `checks/protocol.json`, restores
    `plan.md` from `plan.before.md`, force-marks the selected task
    `[!]` BLOCKED with a `protocol_violation: ...` note, adds it to
    the skip set, rewrites `run.json`, and continues with the next
    selectable task.
  - The helper `_force_block_selected_task` preserves an existing
    `[priority: N]` tag when rewriting the task line.
- Planner-phase protocol violations remain terminal because there is
  no valid task list to recover.
- The append-only `telemetry.recovery.reconstruct(run_dir)` path is
  still conservative: if it sees any failed executor
  `checks/protocol.json`, it reconstructs `FinalStatus.PROTOCOL_VIOLATION`
  even though the live loop may have force-blocked that task and
  completed. Treat `run.json` as the live-loop summary for recovered
  attempts.
- Tests cover executor protocol violation -> BLOCKED + continue, and
  keep the planner-phase terminal behavior intact.

---

## 4. Desired Status

### 4.1 I/O contract

After this change, an executor-phase protocol violation:

1. Logs a warning naming the iteration, task, and violation set.
2. Writes ``checks/protocol.json`` with the violation tuple
   (unchanged from today).
3. Restores ``plan.md`` to the byte content of
   ``iters/<exec_id>/plan.before.md``.
4. Force-marks the selected task ``[!]`` BLOCKED with a note
   ``protocol_violation: <comma-joined violation reasons>``.
   Existing ``(retry N/3)`` annotation is preserved when present.
5. Re-snapshots the now-corrected ``plan.md`` to
   ``iters/<exec_id>/plan.after.md`` so the diff is honest about the
   harness-applied correction.
6. Adds the task id to a runner-local skip set.
7. Returns ``True`` so the executor loop re-selects.

The terminal `FinalStatus` for a run that experiences only protocol
violations remains ``COMPLETED`` (or ``BUDGET_EXHAUSTED`` if budget
ran out) — the BLOCKED tasks count as terminal in the plan-progress
sense. Mixed runs (e.g. one protocol violation + one timeout) keep
the existing TIMEOUT precedence.

The planner-phase protocol_violation termination at
`loop.py:287` is unchanged.

### 4.2 Success criteria

- A single executor-phase protocol violation does not abort the run.
- The forced-BLOCKED task does not get re-selected within the same
  attempt.
- ``plan.md`` after recovery is parseable; downstream verifiers and
  the next iteration's `before` snapshot read it cleanly.
- `checks/protocol.json` for the offending iteration still records
  the original violation set.
- A future resume against the same `run_dir` *can* retry the BLOCKED
  task only if the operator manually flips its status back to
  PENDING — not auto-retried, by design (the agent demonstrably
  could not finish it).

---

## 5. Proposal

### 5.1 Architecture

The change is local to `_run_one_executor` in
`packages/harness/src/harness/loop.py`. No change to
`harness/plan/protocol.py` (it still computes the violation set), no
change to `harness/plan/parser.py` (the rewrite reuses the existing
parser to round-trip ``plan.md``), no change to `Workspace`.

Two new helpers in `loop.py`:

```python
def _restore_plan_from_before(workspace: Workspace, before_path: Path) -> None:
    """Copy plan.before.md back over plan.md (atomic write)."""

def _force_block_selected_task(
    plan_path: Path,
    *,
    selected_task_id: str,
    violation_reasons: tuple[str, ...],
) -> None:
    """Rewrite the selected task line in plan.md to [!] BLOCKED.

    Preserves any prior `(retry N/3)` annotation. Uses
    `harness.plan.parse` to read the current snapshot and a
    deterministic line rewrite to update it; falls back to a
    minimal valid `## Tasks` plan when parsing fails (the loop's
    next iteration parses fresh).
    """
```

### 5.2 Loop hook

Replace the four-line PROTOCOL_VIOLATION terminal branch:

```python
if not protocol_result.passed:
    _log.warning(
        "executor iteration %s on task=%s violated protocol: %s; "
        "force-blocking and continuing",
        exec_id, selected.id, list(protocol_result.violations),
    )
    _restore_plan_from_before(self._workspace, exec_dir / _PLAN_BEFORE_FILENAME)
    _force_block_selected_task(
        self._workspace.plan_md,
        selected_task_id=selected.id,
        violation_reasons=protocol_result.violations,
    )
    self._workspace.snapshot_plan(exec_dir / _PLAN_AFTER_FILENAME)
    self._skipped_task_ids.add(selected.id)
    self._rewrite_run_summary()
    return True
```

### 5.3 Skip set

Rename `self._timed_out_task_ids` → `self._skipped_task_ids` and
update the single TIMEOUT call site to add to the same set. The
`_select_next_skipping(tasks, skip=...)` helper keeps the same
contract and reads from the unified set.

`self._had_timeout` stays the way it is — it solely drives the
TIMEOUT precedence rule and protocol-violation recovery does not
participate.

### 5.4 Verifier ordering

`dispatch_verifiers` runs before the protocol check today
(`loop.py:459-470`). Keep that ordering. Verifier feedback for the
violating iteration is still written to ``feedback.md`` and surfaces
in the next iteration's prompt context — useful when a later task
(e.g. ``visual_fix``) wants to inspect why a sibling task was
force-blocked.

### 5.5 Resume policy

`_REFUSAL_STATUSES` keeps `FinalStatus.PROTOCOL_VIOLATION` (planner
phase still triggers it). A run whose only protocol issues happened
during the executor phase will report `COMPLETED` /
`BUDGET_EXHAUSTED` / `TIMEOUT` and resume normally. This is
consistent with the spec's stance that executor-phase protocol
violations are now per-task failures, not run-level catastrophes.

---

## 6. Alternative

**Auto-retry the violating task.** Reject. The agent demonstrably
could not finish in one shot — auto-retrying without changing the
prompt or the agent state is unlikely to help, and it consumes the
fixed iteration budget. The 3-retry verifier-failure path is the
right place for retries, gated by *verifier* signal, not protocol
signal.

**Mark the task PENDING (like TIMEOUT).** Reject. TIMEOUT semantics
are "the agent ran out of wall-clock; a future resume might
succeed". Protocol violation semantics are "the agent demonstrably
broke the plan-edit contract". The PENDING status would let the
next iteration re-select the same task in the same attempt and
likely re-trigger the same violation. BLOCKED is the correct
runner-local terminal state.

**Drop protocol checks entirely.** Reject. They catch real plan
corruption (resurrected DONE tasks, runaway re-planning) that the
executor prompt's edit contract relies on. Recovering per-task is
the right granularity — the check still matters.

---

## 7. Milestones

- **M1 — Spec sign-off.** Done.
- **M2 — Implementation.** Done.
  - Two helpers + the loop hook in `harness/loop.py`.
  - Skip set rename.
- **M3 — Tests.** Done.
  - New protocol-violation BLOCKED-and-continue test in
    `tests/test_loop.py`.
  - Existing planner-phase protocol_violation test stays green.
- **M4 — End-to-end verification.** Done via replay/e2e loop tests that
  force executor protocol violations and confirm recovery.

---

## 8. Appendix

### 8.1 Public surface (informative)

No public-API changes. `FinalStatus.PROTOCOL_VIOLATION` stays in the
enum because the planner branch still emits it.

### 8.2 References

- `docs/specs/harness/plan_exec_loop.md` §5.5, §5.8.
- `packages/harness/src/harness/loop.py:403-417` — TIMEOUT
  recovery (the model this spec follows).
- `packages/harness/src/harness/plan/protocol.py` — violation set.

### 8.3 Out of scope

- Any change to the planner-phase protocol_violation behaviour.
- Any change to the verifier feedback rendering.
- Any change to `Workspace` lifecycle, seed-immutability check, or
  resume-mode scanning.
