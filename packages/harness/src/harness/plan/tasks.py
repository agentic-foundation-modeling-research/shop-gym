"""Plan-domain primitives parsed out of `plan.md` (spec §5.5).

Defines the typed view every other plan-domain module operates on:

* `TaskStatus` — the four GFM checkbox markers used by the harness.
* `Task` — one row of the `## Tasks` section.
* `TaskList` — ordered, immutable view of the tasks in one snapshot.

Internal value types use frozen dataclasses; nothing here crosses the
filesystem boundary, so pydantic v2 is not needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    """Status marker for a task in `plan.md`.

    Values match the GFM checkbox marker tokens defined by the spec:
    ``[ ]`` PENDING, ``[~]`` IN_PROGRESS, ``[x]`` DONE, ``[!]`` BLOCKED.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Task:
    """One row of the `## Tasks` section of `plan.md`.

    Attributes:
        id: Unique task identifier matching ``[a-z0-9_]+``.
        status: Current `TaskStatus`.
        priority: Selection weight, higher wins. Defaults to 0.
        note: Optional free-form trailing note (the part after `— `).
    """

    id: str
    status: TaskStatus
    priority: int = 0
    note: str | None = None


@dataclass(frozen=True, slots=True)
class TaskList:
    """Ordered, immutable view of the tasks parsed from a `plan.md` snapshot.

    Order matches source order. Use the helpers below to filter or look up
    by id without mutating the tuple.
    """

    tasks: tuple[Task, ...]

    def by_id(self, task_id: str) -> Task | None:
        """Return the task with the given id, or `None` if not found."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def with_status(self, status: TaskStatus) -> tuple[Task, ...]:
        """Return tasks matching `status`, preserving source order."""
        return tuple(t for t in self.tasks if t.status is status)
