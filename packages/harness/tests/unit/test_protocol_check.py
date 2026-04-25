"""Tests for `harness.protocol_check`.

One test per violation listed in spec §5.8, plus a clean-pass case.
"""

from __future__ import annotations

from harness.protocol_check import run_protocol_checks
from harness.types import Task, TaskList, TaskStatus


def _tl(*tasks: Task) -> TaskList:
    return TaskList(tasks=tasks)


_ITER_ID = "exec-0001"


def test_clean_pass_when_only_selected_task_marked_done() -> None:
    before = _tl(
        Task(id="homepage", status=TaskStatus.PENDING),
        Task(id="checkout", status=TaskStatus.PENDING),
    )
    after = _tl(
        Task(id="homepage", status=TaskStatus.DONE, note="covered hero"),
        Task(id="checkout", status=TaskStatus.PENDING),
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is True
    assert result.violations == ()
    assert result.iter_id == _ITER_ID


def test_clean_pass_when_selected_task_marked_blocked_with_added_pending() -> None:
    before = _tl(Task(id="checkout", status=TaskStatus.PENDING))
    after = _tl(
        Task(id="checkout", status=TaskStatus.BLOCKED, note="auth wall"),
        Task(id="login", status=TaskStatus.PENDING),
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="checkout",
    )
    assert result.passed is True
    assert result.violations == ()


def test_violation_when_selected_task_missing_in_after() -> None:
    before = _tl(Task(id="homepage", status=TaskStatus.PENDING))
    after = _tl()
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is False
    assert any("missing from after snapshot" in v for v in result.violations)


def test_violation_when_selected_task_not_terminal() -> None:
    before = _tl(Task(id="homepage", status=TaskStatus.PENDING))
    after = _tl(Task(id="homepage", status=TaskStatus.IN_PROGRESS))
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is False
    assert any("is not terminal" in v for v in result.violations)


def test_violation_when_non_selected_task_newly_marked_done() -> None:
    before = _tl(
        Task(id="homepage", status=TaskStatus.PENDING),
        Task(id="checkout", status=TaskStatus.PENDING),
    )
    after = _tl(
        Task(id="homepage", status=TaskStatus.DONE),
        Task(id="checkout", status=TaskStatus.DONE),
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is False
    assert any("non-selected tasks newly marked terminal" in v for v in result.violations)
    assert any("'checkout'" in v for v in result.violations)


def test_violation_when_non_selected_task_newly_marked_blocked() -> None:
    before = _tl(
        Task(id="homepage", status=TaskStatus.PENDING),
        Task(id="checkout", status=TaskStatus.PENDING),
    )
    after = _tl(
        Task(id="homepage", status=TaskStatus.DONE),
        Task(id="checkout", status=TaskStatus.BLOCKED),
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is False
    assert any("non-selected tasks newly marked terminal" in v for v in result.violations)


def test_violation_when_added_task_is_not_pending() -> None:
    before = _tl(Task(id="homepage", status=TaskStatus.PENDING))
    after = _tl(
        Task(id="homepage", status=TaskStatus.DONE),
        Task(id="bonus", status=TaskStatus.IN_PROGRESS),
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is False
    assert any("newly added tasks are not PENDING" in v for v in result.violations)
    assert any("'bonus'" in v for v in result.violations)


def test_violation_when_done_task_is_resurrected() -> None:
    before = _tl(
        Task(id="homepage", status=TaskStatus.DONE),
        Task(id="checkout", status=TaskStatus.PENDING),
    )
    after = _tl(
        Task(id="homepage", status=TaskStatus.PENDING),
        Task(id="checkout", status=TaskStatus.DONE),
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="checkout",
    )
    assert result.passed is False
    assert any("resurrected [x] task ids" in v for v in result.violations)


def test_violation_when_done_task_is_deleted() -> None:
    before = _tl(
        Task(id="homepage", status=TaskStatus.DONE),
        Task(id="checkout", status=TaskStatus.PENDING),
    )
    after = _tl(Task(id="checkout", status=TaskStatus.DONE))
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="checkout",
    )
    assert result.passed is False
    assert any("resurrected [x] task ids" in v for v in result.violations)


def test_violation_when_after_snapshot_has_duplicate_ids() -> None:
    before = _tl(Task(id="homepage", status=TaskStatus.PENDING))
    # Construct an `after` TaskList directly (parser would normally reject this);
    # protocol_check is defensive against callers that bypass the parser.
    after = TaskList(
        tasks=(
            Task(id="homepage", status=TaskStatus.DONE),
            Task(id="homepage", status=TaskStatus.PENDING),
        )
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is False
    assert any("duplicate task ids" in v for v in result.violations)


def test_violations_are_aggregated_not_short_circuited() -> None:
    before = _tl(
        Task(id="homepage", status=TaskStatus.PENDING),
        Task(id="checkout", status=TaskStatus.PENDING),
    )
    after = _tl(
        # selected is non-terminal
        Task(id="homepage", status=TaskStatus.IN_PROGRESS),
        # non-selected newly terminal
        Task(id="checkout", status=TaskStatus.DONE),
        # added but not pending
        Task(id="bonus", status=TaskStatus.BLOCKED),
    )
    result = run_protocol_checks(
        iter_id=_ITER_ID,
        before=before,
        after=after,
        selected_task_id="homepage",
    )
    assert result.passed is False
    # All three independent invariants violated: selected non-terminal,
    # non-selected newly terminal, and added task non-pending.
    expected_violation_count = 3
    assert len(result.violations) >= expected_violation_count
