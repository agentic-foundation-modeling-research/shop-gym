"""Mandatory ``consolidate`` task contract for the build harness loop (T5.8).

Spec contract (`docs/specs/shop_arena/shop_gen.md` §5.5.4): the planner is
*required* to emit a ``consolidate`` task as the lowest-priority bullet of
``plan.md``. The task drives a cross-ownership cleanup pass after every
``gen_*`` task — verifier failures that bleed across tasks, shared-component
drift, design-token drift, broken inter-page links, deferred verifier
feedback. ``planner.md`` documents the rule explicitly (§2: "the orchestrator
appends it deterministically if you omit it"); this module is the
deterministic fallback.

The function :func:`ensure_consolidate_task` is a pure-filesystem helper:

1. Reads + parses ``plan.md`` via :func:`harness.plan.parse`.
2. If a task with id ``consolidate`` is already present (any status),
   returns ``None`` — the planner did its job.
3. Otherwise appends a canonical ``[ ]`` (PENDING) bullet at the end of
   the ``## Tasks`` section, using priority ``1`` and the canonical brief
   from ``planner.md`` §2 verbatim.
4. Writes the file back atomically and returns the task id
   (``"consolidate"``).

Everything else in the snapshot — the original task lines, the
``## Omitted Areas`` section, prose, blank lines, the trailing newline —
is preserved byte-for-byte. The only mutation is the inserted task line.

The function is import-safe and pure-filesystem: no LLM calls, no
network, no subprocess. The build-loop driver (T5.6) calls it after the
planner iteration writes ``plan.md`` so the executor loop selects
``consolidate`` last regardless of what the planner emitted.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Final

from harness.plan import parse
from harness.plan.parser import InvalidPlanError

CONSOLIDATE_TASK_ID: Final[str] = "consolidate"
"""Canonical id of the mandatory cross-ownership cleanup task (spec §5.5.4)."""

CONSOLIDATE_PRIORITY: Final[int] = 1
"""Canonical priority of the consolidate task (planner.md §2 / spec §5.5.4).

Lowest among the canonical task block: every other task wins ties so
``consolidate`` is dispatched after the gen_* tasks complete.
"""

CONSOLIDATE_BRIEF: Final[str] = (
    "REQUIRED final task; cross-task cleanup (shared-component drift, "
    "design-token drift, broken links, deferred verifier feedback)"
)
"""Default brief text. Matches the canonical bullet shipped in ``planner.md`` §2."""

_TASKS_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^##\s+Tasks\s*$")
"""Mirrors ``harness.plan.parser._TASKS_HEADING_RE``."""

_OTHER_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^##\s+\S")
"""Mirrors ``harness.plan.parser._OTHER_HEADING_RE``."""

_TASK_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^-\s+\[(?P<marker>.)\]\s+(?P<id>\S+)\s*(?P<rest>.*)$",
)
"""Mirrors ``harness.plan.parser._TASK_LINE_RE``."""


def ensure_consolidate_task(plan_path: Path) -> str | None:
    """Append a default ``consolidate`` task to ``plan.md`` if the planner omitted it.

    The orchestrator-side enforcement of spec §5.5.4: every build-loop
    plan must contain a ``consolidate`` task, even when the planner
    forgets to emit one. Calling this helper after the planner writes
    ``plan.md`` guarantees the contract before the executor loop selects
    its first task.

    Args:
        plan_path: Path to ``runs/build/plan.md`` (or any structurally
            valid harness plan snapshot).

    Returns:
        ``None`` when the snapshot already contains a task with id
        ``consolidate`` (any status — the planner satisfied the
        contract). Otherwise the appended task id (always
        :data:`CONSOLIDATE_TASK_ID`).

    Raises:
        FileNotFoundError: ``plan_path`` does not exist.
        harness.plan.parser.InvalidPlanError: ``plan.md`` violates the
            harness parser invariants (caller bug or corrupted run dir).
    """
    text = plan_path.read_text(encoding="utf-8")
    plan = parse(text)

    if plan.by_id(CONSOLIDATE_TASK_ID) is not None:
        return None

    new_line = (
        f"- [ ] {CONSOLIDATE_TASK_ID} [priority: {CONSOLIDATE_PRIORITY}] — {CONSOLIDATE_BRIEF}"
    )
    new_text = _insert_at_tasks_section_end(text, new_line)
    _atomic_write(plan_path, new_text)
    return CONSOLIDATE_TASK_ID


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


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
    tasks_heading_idx: int | None = None

    for i, line in enumerate(lines):
        if _TASKS_HEADING_RE.match(line):
            in_tasks = True
            saw_tasks_heading = True
            tasks_heading_idx = i
            continue
        if in_tasks and _OTHER_HEADING_RE.match(line):
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
        # workspace creation; the consolidate fallback against a
        # populated plan never hits this branch in practice.
        assert tasks_heading_idx is not None  # guaranteed by saw_tasks_heading
        insert_at = tasks_heading_idx + 1

    new_lines = [*lines[:insert_at], new_line, *lines[insert_at:]]
    result = "\n".join(new_lines)
    if text.endswith("\n"):
        result += "\n"
    return result


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via tmp-file + rename.

    Mirrors the pattern :mod:`shop_gen.steps.state` and
    :mod:`shop_gen.build.redo` use: a half-written ``plan.md`` leaves
    the harness in an unrecoverable state, so the caller never sees a
    partial file even on a crash mid-write.
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
    "CONSOLIDATE_BRIEF",
    "CONSOLIDATE_PRIORITY",
    "CONSOLIDATE_TASK_ID",
    "ensure_consolidate_task",
]
