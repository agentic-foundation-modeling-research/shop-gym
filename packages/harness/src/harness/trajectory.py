"""Iteration telemetry value types persisted under ``iters/<iter_id>/``.

Defines the on-disk contract for one executor or planner iteration:

* `TrajectoryStep` (tagged union) and `Trajectory` — normalized telemetry
  emitted by an `AgentRuntime` per iteration, written to
  ``iters/<iter_id>/trajectory.json``.
* `IterationMetadata` — per-iteration sidecar including task attribution,
  written to ``iters/<iter_id>/metadata.json``.
* `ProtocolCheckResult` — outcome of harness-side protocol checks,
  written to ``iters/<exec_id>/checks/protocol.json``.

All types here cross the filesystem boundary, so they are pydantic v2
models that round-trip through JSON. See
`docs/specs/harness/plan_exec_loop.md` sections 5.5, 5.7, and 5.8.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
