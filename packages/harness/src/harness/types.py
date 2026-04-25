"""Core typed data primitives for the plan + exec harness.

Defines the value types every other module in `harness` operates on:

* `TaskStatus`, `Task`, `TaskList` — the domain of `plan.md`.
* `TrajectoryStep` (tagged union) and `Trajectory` — normalized telemetry
  emitted by an `AgentRuntime` per iteration.
* `IterationMetadata` — per-iteration sidecar including task attribution.
* `ProtocolCheckResult` — outcome of harness-side protocol checks.

Internal value types use frozen dataclasses; types that cross the
filesystem boundary (telemetry on disk) are pydantic v2 models so they
round-trip through JSON. See `docs/specs/harness/plan_exec_loop.md`
sections 5.5, 5.7, 5.8, and 8.1.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


# ---------------------------------------------------------------------------
# Trajectory: tagged-union of step kinds + the per-iteration container.
# ---------------------------------------------------------------------------


class _StepBase(BaseModel):
    """Base config for every trajectory step variant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: dt.datetime


class ThoughtStep(_StepBase):
    """Internal reasoning emitted by the agent."""

    kind: Literal["thought"] = "thought"
    text: str


class MessageStep(_StepBase):
    """A user/assistant/system message turn produced inside the iteration."""

    kind: Literal["message"] = "message"
    role: Literal["user", "assistant", "system"]
    text: str


class ToolCallStep(_StepBase):
    """A tool invocation issued by the agent."""

    kind: Literal["tool_call"] = "tool_call"
    call_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultStep(_StepBase):
    """The result returned for a previous `ToolCallStep`."""

    kind: Literal["tool_result"] = "tool_result"
    call_id: str
    output: str
    is_error: bool = False


class ScreenshotStep(_StepBase):
    """A screenshot captured during the iteration.

    `path` is relative to the iteration directory (`iters/<iter_id>/`).
    """

    kind: Literal["screenshot"] = "screenshot"
    path: str


class ErrorStep(_StepBase):
    """A runtime-level error surfaced inside the iteration."""

    kind: Literal["error"] = "error"
    message: str


TrajectoryStep = Annotated[
    ThoughtStep | MessageStep | ToolCallStep | ToolResultStep | ScreenshotStep | ErrorStep,
    Field(discriminator="kind"),
]
"""Discriminated union of every supported trajectory step kind."""


class Trajectory(BaseModel):
    """Normalized telemetry for a single iteration.

    One `Trajectory` is written per iteration to
    `iters/<iter_id>/trajectory.json`. Files are immutable once written.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    iter_id: str
    runtime: str
    started_at: dt.datetime
    ended_at: dt.datetime
    exit_code: int
    prompt_sha256: str
    steps: tuple[TrajectoryStep, ...] = ()


# ---------------------------------------------------------------------------
# Iteration sidecars.
# ---------------------------------------------------------------------------


class IterationMetadata(BaseModel):
    """Per-iteration metadata sidecar at `iters/<iter_id>/metadata.json`.

    Planner iterations leave `selected_task_id` as `None` and the task-id
    tuples empty. Executor iterations populate them per the harness
    contract in spec §5.5.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    iter_id: str
    iter_kind: Literal["plan", "exec"]
    runtime: str
    started_at: dt.datetime
    ended_at: dt.datetime
    selected_task_id: str | None = None
    completed_task_ids: tuple[str, ...] = ()
    blocked_task_ids: tuple[str, ...] = ()
    added_task_ids: tuple[str, ...] = ()


class ProtocolCheckResult(BaseModel):
    """Outcome of harness-side deterministic protocol checks (spec §5.8).

    Written to `iters/<exec_id>/checks/protocol.json` after every executor
    iteration. `passed` is true iff `violations` is empty.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    iter_id: str
    passed: bool
    violations: tuple[str, ...] = ()
