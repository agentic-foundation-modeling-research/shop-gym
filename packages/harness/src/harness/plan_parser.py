"""Parser and helpers for the `plan.md` snapshot format (spec §5.5).

The parser enforces the structural invariants the harness relies on:

* a single top-level `## Tasks` section,
* one task per top-level GFM checkbox item,
* an id matching ``[a-z0-9_]+`` that is unique within a snapshot,
* a status marker drawn from `{[ ], [~], [x], [!]}`,
* an optional ``[priority: N]`` tag (default 0, higher wins) and an
  optional ``— note`` trailer.

Two helpers operate on the parsed `TaskList`:

* `select_next` picks the highest-priority PENDING task (source order
  breaks ties),
* `diff` summarises the executor-visible state change between two
  snapshots and rejects resurrected `[x]` ids.

All structural failures raise `InvalidPlanError`. The harness maps that
to `FinalStatus.INVALID_PLAN`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from harness.types import Task, TaskList, TaskStatus


class InvalidPlanError(Exception):
    """Raised when `plan.md` violates a parser invariant or `diff` rule."""


_STATUS_BY_MARKER: dict[str, TaskStatus] = {
    " ": TaskStatus.PENDING,
    "~": TaskStatus.IN_PROGRESS,
    "x": TaskStatus.DONE,
    "!": TaskStatus.BLOCKED,
}

_TASKS_HEADING_RE = re.compile(r"^##\s+Tasks\s*$")
_OTHER_HEADING_RE = re.compile(r"^##\s+\S")
_TASK_LINE_RE = re.compile(r"^-\s+\[(?P<marker>.)\]\s+(?P<id>\S+)\s*(?P<rest>.*)$")
_ID_RE = re.compile(r"^[a-z0-9_]+$")
_PRIORITY_RE = re.compile(r"\[priority:\s*(-?\d+)\]")
_NOTE_PREFIX = "—"


@dataclass(frozen=True, slots=True)
class PlanDiff:
    """Summary of the state change between two `plan.md` snapshots.

    Attributes:
        completed_task_ids: Ids that transitioned to `DONE` in `after`.
        blocked_task_ids: Ids that transitioned to `BLOCKED` in `after`.
        added_task_ids: Ids present in `after` but absent from `before`,
            in `after` source order.
    """

    completed_task_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    added_task_ids: tuple[str, ...]


def parse(text: str) -> TaskList:
    """Parse a `plan.md` snapshot into a `TaskList`.

    Args:
        text: Full `plan.md` contents.

    Returns:
        Tasks in source order.

    Raises:
        InvalidPlanError: On any structural violation listed in spec §5.5.
    """
    section_lines = _extract_tasks_section(text.splitlines())
    tasks: list[Task] = []
    seen: set[str] = set()
    for raw in section_lines:
        if not raw.startswith("-"):
            # blank lines, prose, sub-list items — all ignored
            continue
        match = _TASK_LINE_RE.match(raw)
        if match is None:
            raise InvalidPlanError(f"malformed task line: {raw!r}")
        marker = match.group("marker")
        status = _STATUS_BY_MARKER.get(marker)
        if status is None:
            raise InvalidPlanError(f"unknown status marker [{marker}] in line: {raw!r}")
        ident: str = match.group("id")
        if _ID_RE.match(ident) is None:
            raise InvalidPlanError(f"invalid task id {ident!r} in line: {raw!r}")
        if ident in seen:
            raise InvalidPlanError(f"duplicate task id: {ident!r}")
        seen.add(ident)
        priority, note = _parse_rest(match.group("rest"))
        tasks.append(Task(id=ident, status=status, priority=priority, note=note))
    return TaskList(tasks=tuple(tasks))


def select_next(tasks: TaskList) -> Task | None:
    """Return the highest-priority PENDING task, or `None` if none remain.

    Ties on `priority` are broken by source order (the earlier task wins).
    """
    best: Task | None = None
    for task in tasks.tasks:
        if task.status is not TaskStatus.PENDING:
            continue
        if best is None or task.priority > best.priority:
            best = task
    return best


def diff(before: TaskList, after: TaskList) -> PlanDiff:
    """Diff two parsed snapshots and reject resurrected `[x]` ids.

    Args:
        before: Snapshot taken before an iteration.
        after: Snapshot taken after the same iteration.

    Returns:
        A `PlanDiff` summarising the transition.

    Raises:
        InvalidPlanError: If any id that was `DONE` in `before` is missing
            or non-`DONE` in `after`.
    """
    before_by_id = {t.id: t for t in before.tasks}
    after_by_id = {t.id: t for t in after.tasks}

    resurrected: list[str] = []
    for ident, prev in before_by_id.items():
        if prev.status is not TaskStatus.DONE:
            continue
        nxt = after_by_id.get(ident)
        if nxt is None or nxt.status is not TaskStatus.DONE:
            resurrected.append(ident)
    if resurrected:
        raise InvalidPlanError(f"resurrected [x] task ids: {sorted(resurrected)!r}")

    completed: list[str] = []
    blocked: list[str] = []
    added: list[str] = []
    for task in after.tasks:
        prev = before_by_id.get(task.id)
        if prev is None:
            added.append(task.id)
            continue
        if task.status is TaskStatus.DONE and prev.status is not TaskStatus.DONE:
            completed.append(task.id)
        elif task.status is TaskStatus.BLOCKED and prev.status is not TaskStatus.BLOCKED:
            blocked.append(task.id)
    return PlanDiff(
        completed_task_ids=tuple(completed),
        blocked_task_ids=tuple(blocked),
        added_task_ids=tuple(added),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract_tasks_section(lines: list[str]) -> list[str]:
    """Return the body lines under the single `## Tasks` heading."""
    in_section = False
    saw_section = False
    out: list[str] = []
    for line in lines:
        if _TASKS_HEADING_RE.match(line):
            if saw_section:
                raise InvalidPlanError("multiple '## Tasks' sections in plan.md")
            in_section = True
            saw_section = True
            continue
        if in_section and _OTHER_HEADING_RE.match(line):
            in_section = False
            continue
        if in_section:
            out.append(line)
    if not saw_section:
        raise InvalidPlanError("plan.md is missing the '## Tasks' section")
    return out


def _parse_rest(rest: str) -> tuple[int, str | None]:
    """Extract `[priority: N]` and the optional `— note` trailer."""
    rest = rest.strip()
    priority = 0
    pri_match = _PRIORITY_RE.search(rest)
    if pri_match is not None:
        priority = int(pri_match.group(1))
        rest = (rest[: pri_match.start()] + rest[pri_match.end() :]).strip()
    if not rest:
        return priority, None
    if not rest.startswith(_NOTE_PREFIX):
        raise InvalidPlanError(f"unexpected trailing content {rest!r} on task line")
    note = rest[len(_NOTE_PREFIX) :].strip()
    return priority, note or None
