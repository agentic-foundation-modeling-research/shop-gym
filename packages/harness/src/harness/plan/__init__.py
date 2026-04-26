"""Plan-domain subpackage: types, parser, and protocol checks for `plan.md`.

Re-exports the public plan-domain API so callers can import a single
canonical path::

    from harness.plan import Task, TaskList, TaskStatus, parse, select_next, diff
    from harness.plan import InvalidPlanError, PlanDiff, run_protocol_checks

The harness public surface (``harness.__all__``) still re-exports `Task`,
`TaskList`, and `TaskStatus` directly for backward compatibility.
"""

from __future__ import annotations

from harness.plan.parser import InvalidPlanError, PlanDiff, diff, parse, select_next
from harness.plan.protocol import run_protocol_checks
from harness.plan.tasks import Task, TaskList, TaskStatus

__all__ = [
    "InvalidPlanError",
    "PlanDiff",
    "Task",
    "TaskList",
    "TaskStatus",
    "diff",
    "parse",
    "run_protocol_checks",
    "select_next",
]
