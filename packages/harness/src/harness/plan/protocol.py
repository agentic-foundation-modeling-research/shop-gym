"""Deterministic harness-side protocol checks (spec §5.8).

Run after every executor iteration to enforce the harness contract on
the post-iteration `plan.md` snapshot. These are guardrails, not
domain-quality grading; they produce a `ProtocolCheckResult` describing
any violations rather than raising.

The checks covered here:

* the ``selected_task_id`` is present in the post-iteration snapshot,
* the selected task is terminal (``DONE`` or ``BLOCKED``) in `after`,
* no *other* task transitioned to a terminal status during the iteration,
* every newly added task has status ``PENDING``,
* no previously ``DONE`` task was resurrected (defensive — the parser-
  level `diff` already raises on this, but we re-check to keep this
  function's invariants self-contained),
* task ids in `after` remain unique (defensive — the parser already
  enforces uniqueness on read).

Plan-file *parseability* and the parser-level uniqueness invariant are
enforced before this function is called: the loop parses both snapshots
and maps `InvalidPlanError` to ``FinalStatus.INVALID_PLAN``. A non-
passing `ProtocolCheckResult` maps to ``FinalStatus.PROTOCOL_VIOLATION``.

See `docs/specs/harness/plan_exec_loop.md` §5.5 + §5.8.
"""

from __future__ import annotations

from collections import Counter

from harness.plan.tasks import Task, TaskList, TaskStatus
from harness.trajectory import ProtocolCheckResult

_TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.DONE, TaskStatus.BLOCKED})


def run_protocol_checks(
    *,
    iter_id: str,
    before: TaskList,
    after: TaskList,
    selected_task_id: str,
) -> ProtocolCheckResult:
    """Validate the executor contract against pre/post `plan.md` snapshots.

    Args:
        iter_id: Iteration id this result is attributed to (e.g. ``exec-0001``).
        before: Parsed `plan.md` snapshot taken before the executor ran.
        after: Parsed `plan.md` snapshot taken after the executor exited.
        selected_task_id: The task id the harness selected for this iteration.

    Returns:
        A `ProtocolCheckResult` whose ``passed`` is true iff no violations
        were detected. Violation messages are stable, deterministic strings
        suitable for embedding in `iters/<exec_id>/checks/protocol.json`.
    """
    before_by_id = {t.id: t for t in before.tasks}
    after_by_id = {t.id: t for t in after.tasks}
    violations: list[str] = []
    violations.extend(_check_unique_ids(after))
    violations.extend(_check_selected_terminal(selected_task_id, after_by_id))
    violations.extend(_check_no_resurrection(before_by_id, after_by_id))
    violations.extend(
        _check_only_selected_newly_terminal(selected_task_id, before_by_id, after.tasks)
    )
    violations.extend(_check_added_tasks_pending(before_by_id, after.tasks))
    return ProtocolCheckResult(
        iter_id=iter_id,
        passed=not violations,
        violations=tuple(violations),
    )


def _check_unique_ids(after: TaskList) -> list[str]:
    """Defensive: parser already enforces id uniqueness, but recheck."""
    duplicates = sorted(
        ident for ident, count in Counter(t.id for t in after.tasks).items() if count > 1
    )
    if not duplicates:
        return []
    return [f"duplicate task ids in after snapshot: {duplicates!r}"]


def _check_selected_terminal(selected_task_id: str, after_by_id: dict[str, Task]) -> list[str]:
    """Selected task must be present and terminal in `after`."""
    selected_after = after_by_id.get(selected_task_id)
    if selected_after is None:
        return [f"selected task {selected_task_id!r} is missing from after snapshot"]
    if selected_after.status not in _TERMINAL_STATUSES:
        return [
            f"selected task {selected_task_id!r} is not terminal in after snapshot "
            f"(status={selected_after.status.value!r})"
        ]
    return []


def _check_no_resurrection(
    before_by_id: dict[str, Task], after_by_id: dict[str, Task]
) -> list[str]:
    """Previously-DONE tasks must remain DONE in `after`."""
    resurrected: list[str] = []
    for ident, prev in before_by_id.items():
        if prev.status is not TaskStatus.DONE:
            continue
        nxt = after_by_id.get(ident)
        if nxt is None or nxt.status is not TaskStatus.DONE:
            resurrected.append(ident)
    if not resurrected:
        return []
    return [f"resurrected [x] task ids: {sorted(resurrected)!r}"]


def _check_only_selected_newly_terminal(
    selected_task_id: str,
    before_by_id: dict[str, Task],
    after_tasks: tuple[Task, ...],
) -> list[str]:
    """Only the selected task may transition to a terminal status."""
    others: list[str] = []
    for task in after_tasks:
        if task.id == selected_task_id:
            continue
        if task.status not in _TERMINAL_STATUSES:
            continue
        prev = before_by_id.get(task.id)
        if prev is not None and prev.status in _TERMINAL_STATUSES:
            continue
        others.append(task.id)
    if not others:
        return []
    return [f"non-selected tasks newly marked terminal: {sorted(others)!r}"]


def _check_added_tasks_pending(
    before_by_id: dict[str, Task], after_tasks: tuple[Task, ...]
) -> list[str]:
    """Newly added tasks must have PENDING status."""
    added_non_pending = [
        task.id
        for task in after_tasks
        if task.id not in before_by_id and task.status is not TaskStatus.PENDING
    ]
    if not added_non_pending:
        return []
    return [f"newly added tasks are not PENDING: {sorted(added_non_pending)!r}"]
