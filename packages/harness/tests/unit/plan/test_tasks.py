"""Tests for `harness.plan.tasks` value types."""

from __future__ import annotations

import pytest

from harness.plan.tasks import Task, TaskList, TaskStatus


def test_task_is_frozen_and_hashable() -> None:
    task = Task(id="homepage", status=TaskStatus.PENDING)
    # frozen dataclasses with slots raise FrozenInstanceError on assignment
    with pytest.raises(AttributeError):
        task.priority = 5  # type: ignore[misc]
    # frozen dataclasses with slots are hashable
    assert hash(task) == hash(Task(id="homepage", status=TaskStatus.PENDING))


def test_task_list_by_id_returns_match() -> None:
    a = Task(id="a", status=TaskStatus.PENDING)
    b = Task(id="b", status=TaskStatus.DONE)
    tl = TaskList(tasks=(a, b))
    assert tl.by_id("a") is a
    assert tl.by_id("missing") is None


def test_task_list_with_status_preserves_order() -> None:
    a = Task(id="a", status=TaskStatus.PENDING, priority=1)
    b = Task(id="b", status=TaskStatus.DONE)
    c = Task(id="c", status=TaskStatus.PENDING, priority=3)
    tl = TaskList(tasks=(a, b, c))
    assert tl.with_status(TaskStatus.PENDING) == (a, c)
