# Protocol-Violation Recovery — Implementation Plan

Spec: [`docs/specs/harness/protocol_violation_recovery.md`](../specs/harness/protocol_violation_recovery.md)

---

## 1. Overview

Implements the executor-phase protocol-violation BLOCKED-and-continue
recovery. All work lives in `packages/harness`.

---

## 2. Terminology

Match the spec.

---

## 3. Current Status

See spec §3.

---

## 4. Desired Status

See spec §4.

---

## 5. Proposal

### 5.1 Edits in `packages/harness/src/harness/loop.py`

1. Rename `self._timed_out_task_ids: set[str]` → `self._skipped_task_ids: set[str]`.
   Update the single `_select_next_skipping(... skip=self._timed_out_task_ids)`
   call site (and the docstring it lives under).

2. Update the TIMEOUT branch:
   - Replace `self._timed_out_task_ids.add(selected.id)` with
     `self._skipped_task_ids.add(selected.id)`.

3. Replace the protocol-violation terminal branch
   (lines ~472-475) with the recovery sequence below.

```python
if not protocol_result.passed:
    _log.warning(
        "executor iteration %s on task=%s violated protocol: %s; "
        "force-blocking and continuing",
        exec_id,
        selected.id,
        list(protocol_result.violations),
    )
    _restore_plan_from_before(
        self._workspace,
        exec_dir / _PLAN_BEFORE_FILENAME,
    )
    _force_block_selected_task(
        self._workspace.plan_md,
        selected_task_id=selected.id,
        violation_reasons=protocol_result.violations,
    )
    # Re-snapshot so plan.after.md reflects what's actually on disk.
    self._workspace.snapshot_plan(exec_dir / _PLAN_AFTER_FILENAME)
    self._skipped_task_ids.add(selected.id)
    self._rewrite_run_summary()
    return True
```

4. Add the two private helpers near the bottom of the module (next to
   the existing `_quarantine_iter_dir` helper):

```python
def _restore_plan_from_before(workspace: Workspace, before_path: Path) -> None:
    """Atomically copy `plan.before.md` back over `plan.md`.

    Uses a tmp-file + os.replace pattern so a crash mid-write leaves
    the prior plan.md in place. When `before_path` is missing or empty
    (e.g. the very first executor iteration), writes the empty stub
    `# Plan\n\n## Tasks\n` so the parser does not raise.
    """

def _force_block_selected_task(
    plan_path: Path,
    *,
    selected_task_id: str,
    violation_reasons: tuple[str, ...],
) -> None:
    """Rewrite the line for `selected_task_id` in `plan.md` to [!] BLOCKED.

    Reuses `harness.plan.parser.parse` to confirm the snapshot is
    well-formed, then performs a deterministic line-by-line rewrite
    to flip the marker. The existing `(retry N/3)` annotation in the
    note is preserved if present; the violation reasons are appended
    to the note as ` protocol_violation: <reason1, reason2>`.

    On parse failure (e.g. plan.md is corrupt for some reason that
    bypassed the planner protocol check), writes the empty stub —
    the next iteration re-plans cleanly.
    """
```

`_force_block_selected_task` implementation outline:

- Read `plan_path` text. Try `parse(text)`; on `InvalidPlanError`,
  write `_EMPTY_PLAN_MD` (already defined in `shop_gen.build.loop`;
  copy or re-derive at the harness level: `# Plan\n\n## Tasks\n`).
- Walk lines; find the bullet whose id matches `selected_task_id`
  (regex: `^- \[(.)] (\S+)( \[priority: \d+\])?( — .*)?$`).
- Build the new line: `- [!] <id>[priority]<note + " protocol_violation: <reasons>">`.
- Atomic write back.

A purely text-level rewrite (no AST manipulation) keeps the
implementation small and avoids re-emitting the file's surrounding
prose, blank lines, or trailing newline shape.

### 5.2 Test coverage

`packages/harness/tests/test_loop.py` (new test):

```python
def test_protocol_violation_force_blocks_and_continues(...):
    """Selected task that exits without [x]/[!] is force-blocked.

    Use ReplayRuntime with a recorded plan that:
    - planner produces 3 PENDING tasks (tA, tB, tC).
    - exec-1 selects tA, leaves it PENDING (protocol violation).
    - exec-2 selects tB, marks [x].
    - exec-3 selects tC, marks [x].

    Expectations:
    - run.json final_status == "completed"
    - plan.md has tA == [!] BLOCKED with protocol_violation note,
      tB / tC == DONE.
    - iters/exec-0001/checks/protocol.json contains the violation.
    - The exec_iter_count is 3 (no quarantine).
    """
```

Existing terminal-protocol-violation tests scoped to the planner phase
should keep passing — only the executor branch changed.

### 5.3 No spec change to FinalStatus

`FinalStatus.PROTOCOL_VIOLATION` stays in the enum and is still emitted
by the planner branch (`run_planner` line 287). Tests asserting that
behaviour stay valid.

---

## 6. Alternative

See spec §6.

---

## 7. Milestones

| ID | Description | Files |
|----|-------------|-------|
| H1 | Rename skip set, update TIMEOUT branch | `harness/loop.py` |
| H2 | Add `_restore_plan_from_before` + `_force_block_selected_task` helpers | `harness/loop.py` |
| H3 | Wire the recovery branch into `_run_one_executor` | `harness/loop.py` |
| H4 | New protocol-violation recovery test | `tests/test_loop.py` |
| H5 | End-to-end verification on `mock_cookware` | (manual) |

---

## 8. Appendix

### 8.1 Verification

```
uv run pytest packages/harness/tests/test_loop.py -k "protocol or timeout"
uv run pyright packages/harness
uv run ruff check packages/harness
```

### 8.2 References

Same as the spec.
