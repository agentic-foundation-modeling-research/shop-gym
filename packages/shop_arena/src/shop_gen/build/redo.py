"""Append-redo helper for the ``--only gen_<task>`` build-loop CLI flow (T5.7).

Implements spec §5.7.3 — the user-driven escape hatch for "regenerate just
the homepage" without resurrecting any ``[x]`` task. The harness state
machine treats ``[x]`` as terminal (``harness.plan.parser.diff`` rejects
any id that flips ``[x]`` → not-``[x]``); the spec answers that constraint
by **appending a fresh redo task** to ``plan.md`` rather than rewriting the
original ``[x]`` line. Concretely, calling :func:`append_redo_task` against
``runs/build/plan.md`` for a completed task ``gen_homepage``:

1. Reads + parses the snapshot via :func:`harness.plan.parse`.
2. Verifies the base task exists and is ``DONE``.
3. Counts existing ``<base>_redo_<N>`` siblings to compute the next
   suffix.
4. Appends a new ``[ ]`` (PENDING) task line at the end of the
   ``## Tasks`` section — i.e. **after** the mandatory ``visual_fix``
   bullet that the planner pins to last position (planner.md §3 / spec
   §5.7.3).
5. Writes the file back atomically and returns the new task id.

Everything else in the snapshot — the original ``[x]`` markers, the
``## Omitted Areas`` section, prose, blank lines — is preserved
byte-for-byte. The only mutation is the inserted task line.

The function is import-safe and pure-filesystem: no LLM calls, no
network, no subprocess. Callers (the CLI in :mod:`shop_gen.cli`)
combine the returned id with a forced re-run of
``run_build_harness_loop`` (the harness then enters resume mode with
``force=True`` and selects the only remaining PENDING task).

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Final

from harness.plan import TaskList, TaskStatus, parse
from harness.plan.parser import InvalidPlanError

_DEFAULT_PRIORITY: Final[int] = 1
"""Spec §5.7.3 default priority for an appended redo task.

One below the canonical priority of ``visual_fix`` (planner.md §5,
priority 2). On a completed run every other task is ``[x]``, so
:func:`harness.plan.select_next` picks the redo task regardless of
the tie — the priority value is recorded literally for forward
compatibility with future selection refinements.
"""

_TASKS_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^##\s+Tasks\s*$")
"""Mirrors ``harness.plan.parser._TASKS_HEADING_RE``."""

_OTHER_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^##\s+\S")
"""Mirrors ``harness.plan.parser._OTHER_HEADING_RE``."""

_TASK_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^-\s+\[(?P<marker>.)\]\s+(?P<id>\S+)\s*(?P<rest>.*)$",
)
"""Mirrors ``harness.plan.parser._TASK_LINE_RE``."""


class RedoError(Exception):
    """Raised when an append-redo request cannot be satisfied.

    The CLI maps this to ``EXIT_RUNTIME``; structural ``plan.md`` errors
    surface :class:`harness.plan.parser.InvalidPlanError` instead, which
    the CLI maps separately so users can tell "your plan.md is corrupted"
    apart from "you asked to redo a task that doesn't exist".
    """


def append_redo_task(
    plan_path: Path,
    base_task_id: str,
    *,
    reason: str | None = None,
    priority: int = _DEFAULT_PRIORITY,
) -> str:
    """Append a ``<base>_redo_<N>`` PENDING task to ``plan.md``.

    Args:
        plan_path: Path to ``runs/build/plan.md`` (or any structurally
            valid harness plan snapshot).
        base_task_id: Id of the completed task to redo (e.g.
            ``gen_homepage``). Must already be present in the snapshot
            with status ``DONE``.
        reason: Optional human-supplied reason appended to the new task's
            brief. The brief always points back to ``base_task_id`` so
            the executor can locate the original task's iteration
            history; ``reason`` is appended after a colon when supplied.
        priority: Priority value for the new task. Defaults to
            :data:`_DEFAULT_PRIORITY` (one below ``visual_fix``); higher
            values override the selection tie when needed.

    Returns:
        The newly appended task id (``<base>_redo_<N>``).

    Raises:
        FileNotFoundError: ``plan_path`` does not exist.
        harness.plan.parser.InvalidPlanError: ``plan.md`` violates the
            harness parser invariants (caller bug or corrupted run dir).
        RedoError: ``base_task_id`` is unknown to the snapshot, or its
            current status is not ``DONE``.
    """
    text = plan_path.read_text(encoding="utf-8")
    plan = parse(text)

    base_task = plan.by_id(base_task_id)
    if base_task is None:
        raise RedoError(
            f"cannot redo {base_task_id!r}: not present in {plan_path}",
        )
    if base_task.status is not TaskStatus.DONE:
        raise RedoError(
            f"cannot redo {base_task_id!r}: status is {base_task.status.value!r} "
            "(only DONE tasks can be redone — pending / in-progress / blocked tasks "
            "are still owned by the harness loop)",
        )

    suffix = _next_redo_suffix(plan, base_task_id)
    new_id = f"{base_task_id}_redo_{suffix}"

    note = _build_note(base_task_id, reason)
    new_line = f"- [ ] {new_id} [priority: {priority}] — {note}"

    new_text = _insert_at_tasks_section_end(text, new_line)
    _atomic_write(plan_path, new_text)
    return new_id


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _next_redo_suffix(plan: TaskList, base_task_id: str) -> int:
    """Return the next ``<base>_redo_<N>`` suffix not yet present in ``plan``."""
    pat = re.compile(rf"^{re.escape(base_task_id)}_redo_(\d+)$")
    max_n = 0
    for task in plan.tasks:
        m = pat.match(task.id)
        if m is None:
            continue
        n = int(m.group(1))
        max_n = max(max_n, n)
    return max_n + 1


def _build_note(base_task_id: str, reason: str | None) -> str:
    """Compose the ``— note`` trailer for a redo task line."""
    note = f"redo of {base_task_id}"
    cleaned = reason.strip() if reason is not None else ""
    if cleaned:
        note = f"{note}: {cleaned}"
    return note


def _insert_at_tasks_section_end(text: str, new_line: str) -> str:
    """Insert ``new_line`` after the last task bullet in the ``## Tasks`` section.

    Preserves the surrounding structure byte-for-byte: prose, blank lines,
    other ``##`` sections, and the trailing newline (if any) are
    untouched. The new line is inserted after the last existing task
    bullet inside the ``## Tasks`` body, or immediately after the
    ``## Tasks`` heading when no bullets exist yet.
    """
    lines = text.splitlines()
    in_tasks = False
    saw_tasks_heading = False
    last_task_idx: int | None = None
    tasks_section_end_idx: int | None = None
    tasks_heading_idx: int | None = None

    for i, line in enumerate(lines):
        if _TASKS_HEADING_RE.match(line):
            in_tasks = True
            saw_tasks_heading = True
            tasks_heading_idx = i
            continue
        if in_tasks and _OTHER_HEADING_RE.match(line):
            tasks_section_end_idx = i
            in_tasks = False
            continue
        if in_tasks and _TASK_LINE_RE.match(line):
            last_task_idx = i

    if not saw_tasks_heading:
        # Should never happen — `parse` would have raised InvalidPlanError.
        raise InvalidPlanError("plan.md is missing the '## Tasks' section")

    if last_task_idx is not None:
        insert_at = last_task_idx + 1
    else:
        # No bullets in ## Tasks yet — drop the new line right after
        # the heading. The harness writes ``## Tasks\n`` as a stub on
        # workspace creation; the redo flow against a populated plan
        # never hits this branch in practice.
        assert tasks_heading_idx is not None  # guaranteed by saw_tasks_heading
        insert_at = tasks_heading_idx + 1

    new_lines = [*lines[:insert_at], new_line, *lines[insert_at:]]
    result = "\n".join(new_lines)
    if text.endswith("\n"):
        result += "\n"
    # Suppress unused-warning when the section terminator is absent (EOF).
    del tasks_section_end_idx
    return result


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via tmp-file + rename.

    Mirrors the pattern :mod:`shop_gen.steps.state` uses: a half-written
    ``plan.md`` leaves the harness in an unrecoverable state, so the
    caller never sees a partial file even on a crash mid-write.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


__all__ = [
    "RedoError",
    "append_redo_task",
]
