"""Tests for `harness.plan.parser`.

Covers happy-path parsing, every §5.5 invariant violation, priority
ordering for `select_next`, and resurrection detection in `diff`.
"""

from __future__ import annotations

import pytest

from harness.plan.parser import InvalidPlanError, PlanDiff, diff, parse, select_next
from harness.plan.tasks import Task, TaskList, TaskStatus

# ---------------------------------------------------------------------------
# parse — happy path
# ---------------------------------------------------------------------------


def test_parse_returns_tasks_in_source_order_with_all_status_markers() -> None:
    text = (
        "# Plan\n"
        "\n"
        "## Tasks\n"
        "- [x] homepage — covered hero, nav, footer\n"
        "- [~] product_detail   [priority: 3]\n"
        "- [ ] collection       [priority: 2]\n"
        "- [!] checkout — auth wall, cannot complete\n"
    )
    tl = parse(text)
    assert tl.tasks == (
        Task(
            id="homepage",
            status=TaskStatus.DONE,
            priority=0,
            note="covered hero, nav, footer",
        ),
        Task(id="product_detail", status=TaskStatus.IN_PROGRESS, priority=3),
        Task(id="collection", status=TaskStatus.PENDING, priority=2),
        Task(
            id="checkout",
            status=TaskStatus.BLOCKED,
            priority=0,
            note="auth wall, cannot complete",
        ),
    )


def test_parse_handles_priority_and_note_together() -> None:
    text = "## Tasks\n- [ ] foo [priority: 5] — needs login\n"
    tl = parse(text)
    assert tl.tasks == (Task(id="foo", status=TaskStatus.PENDING, priority=5, note="needs login"),)


def test_parse_defaults_priority_to_zero_and_note_to_none() -> None:
    text = "## Tasks\n- [ ] homepage\n"
    tl = parse(text)
    assert tl.tasks == (Task(id="homepage", status=TaskStatus.PENDING),)


def test_parse_supports_negative_priority() -> None:
    expected = -2
    text = f"## Tasks\n- [ ] x [priority: {expected}]\n"
    assert parse(text).tasks[0].priority == expected


def test_parse_ignores_blank_lines_and_prose_in_tasks_section() -> None:
    text = "## Tasks\n\nSome prose the planner left here.\n- [ ] homepage\n"
    tl = parse(text)
    assert tl.tasks == (Task(id="homepage", status=TaskStatus.PENDING),)


def test_parse_stops_at_next_heading() -> None:
    text = "## Tasks\n- [ ] homepage\n\n## Notes\n- [ ] not_a_task\n"
    tl = parse(text)
    assert tuple(t.id for t in tl.tasks) == ("homepage",)


def test_parse_empty_tasks_section_returns_empty_list() -> None:
    text = "## Tasks\n"
    assert parse(text).tasks == ()


# ---------------------------------------------------------------------------
# parse — invariant violations
# ---------------------------------------------------------------------------


def test_parse_rejects_missing_tasks_section() -> None:
    with pytest.raises(InvalidPlanError, match="missing the '## Tasks' section"):
        parse("# Plan\n\nNo tasks heading here.\n")


def test_parse_rejects_duplicate_tasks_section() -> None:
    text = "## Tasks\n- [ ] a\n## Tasks\n- [ ] b\n"
    with pytest.raises(InvalidPlanError, match="multiple '## Tasks' sections"):
        parse(text)


def test_parse_rejects_unknown_status_marker() -> None:
    text = "## Tasks\n- [?] homepage\n"
    with pytest.raises(InvalidPlanError, match="unknown status marker"):
        parse(text)


def test_parse_rejects_invalid_id_uppercase() -> None:
    text = "## Tasks\n- [ ] Homepage\n"
    with pytest.raises(InvalidPlanError, match="invalid task id"):
        parse(text)


def test_parse_rejects_invalid_id_with_dash() -> None:
    text = "## Tasks\n- [ ] home-page\n"
    with pytest.raises(InvalidPlanError, match="invalid task id"):
        parse(text)


def test_parse_rejects_duplicate_ids() -> None:
    text = "## Tasks\n- [ ] homepage\n- [x] homepage\n"
    with pytest.raises(InvalidPlanError, match="duplicate task id"):
        parse(text)


def test_parse_rejects_malformed_task_line() -> None:
    text = "## Tasks\n- not a checkbox\n"
    with pytest.raises(InvalidPlanError, match="malformed task line"):
        parse(text)


def test_parse_rejects_trailing_garbage_after_id() -> None:
    text = "## Tasks\n- [ ] homepage extra words\n"
    with pytest.raises(InvalidPlanError, match="unexpected trailing content"):
        parse(text)


# ---------------------------------------------------------------------------
# select_next — priority + tie-break ordering
# ---------------------------------------------------------------------------


def test_select_next_returns_none_when_no_retryable() -> None:
    tl = TaskList(
        tasks=(
            Task(id="a", status=TaskStatus.DONE),
            Task(id="b", status=TaskStatus.BLOCKED),
        )
    )
    assert select_next(tl) is None


def test_select_next_picks_in_progress_for_retry() -> None:
    """Verifier-rewritten `[~]` tasks are retryable (verifiers.md §5.4)."""
    tl = TaskList(
        tasks=(
            Task(id="a", status=TaskStatus.DONE),
            Task(id="b", status=TaskStatus.IN_PROGRESS),
        )
    )
    chosen = select_next(tl)
    assert chosen is not None
    assert chosen.id == "b"


def test_select_next_returns_highest_priority_pending() -> None:
    tl = TaskList(
        tasks=(
            Task(id="a", status=TaskStatus.PENDING, priority=0),
            Task(id="b", status=TaskStatus.PENDING, priority=5),
            Task(id="c", status=TaskStatus.PENDING, priority=2),
        )
    )
    chosen = select_next(tl)
    assert chosen is not None
    assert chosen.id == "b"


def test_select_next_breaks_priority_ties_by_source_order() -> None:
    tl = TaskList(
        tasks=(
            Task(id="first", status=TaskStatus.PENDING, priority=3),
            Task(id="second", status=TaskStatus.PENDING, priority=3),
        )
    )
    chosen = select_next(tl)
    assert chosen is not None
    assert chosen.id == "first"


def test_select_next_skips_non_pending_even_at_higher_priority() -> None:
    tl = TaskList(
        tasks=(
            Task(id="done_high", status=TaskStatus.DONE, priority=99),
            Task(id="pending_low", status=TaskStatus.PENDING, priority=1),
        )
    )
    chosen = select_next(tl)
    assert chosen is not None
    assert chosen.id == "pending_low"


# ---------------------------------------------------------------------------
# diff — transitions and resurrection
# ---------------------------------------------------------------------------


def _tl(*tasks: Task) -> TaskList:
    return TaskList(tasks=tasks)


def test_diff_reports_completed_blocked_and_added() -> None:
    before = _tl(
        Task(id="a", status=TaskStatus.PENDING),
        Task(id="b", status=TaskStatus.IN_PROGRESS),
        Task(id="c", status=TaskStatus.PENDING),
    )
    after = _tl(
        Task(id="a", status=TaskStatus.DONE),
        Task(id="b", status=TaskStatus.BLOCKED),
        Task(id="c", status=TaskStatus.PENDING),
        Task(id="new_task", status=TaskStatus.PENDING),
    )
    assert diff(before, after) == PlanDiff(
        completed_task_ids=("a",),
        blocked_task_ids=("b",),
        added_task_ids=("new_task",),
    )


def test_diff_returns_empty_for_unchanged_snapshots() -> None:
    tl = _tl(Task(id="a", status=TaskStatus.PENDING))
    assert diff(tl, tl) == PlanDiff(
        completed_task_ids=(),
        blocked_task_ids=(),
        added_task_ids=(),
    )


def test_diff_does_not_re_report_already_done_task() -> None:
    before = _tl(Task(id="a", status=TaskStatus.DONE))
    after = _tl(Task(id="a", status=TaskStatus.DONE))
    assert diff(before, after).completed_task_ids == ()


def test_diff_rejects_resurrected_done_task() -> None:
    before = _tl(Task(id="homepage", status=TaskStatus.DONE))
    after = _tl(Task(id="homepage", status=TaskStatus.PENDING))
    with pytest.raises(InvalidPlanError, match="resurrected"):
        diff(before, after)


def test_diff_rejects_deleted_done_task() -> None:
    before = _tl(Task(id="homepage", status=TaskStatus.DONE))
    after = _tl()
    with pytest.raises(InvalidPlanError, match="resurrected"):
        diff(before, after)
