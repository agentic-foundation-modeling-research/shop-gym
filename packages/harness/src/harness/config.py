"""Configuration and result types for `run_plan_exec_loop`.

Defines the externally-facing value types a caller passes in and gets
back when invoking the harness:

* `Prompts` — the planner/executor prompt bundle.
* `PlanExecLoopConfig` — full run configuration (workspace, prompts,
  AGENTS.md, optional artifact seed, loop budget).
* `FinalStatus` — terminal state of a run.
* `PlanExecLoopResult` — return value of `run_plan_exec_loop`.

These types cross both the public API boundary and (for `result`) the
filesystem boundary via `run.json`, so they are pydantic v2 models. See
`docs/specs/harness/plan_exec_loop.md` sections 4.1, 5.7, and 8.1.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.types import Task


class Prompts(BaseModel):
    """Caller-supplied prompt bundle for one run.

    The harness writes these verbatim into `run_dir/prompts/` and renders
    them into the planner / executor subprocess invocations without any
    templating. Both fields are required and must be non-empty.

    Attributes:
        planner: Prompt for the single planner iteration.
        execute: Prompt for every executor iteration. The harness
            prepends a small `<<<harness-control>>>` header carrying the
            selected task id at spawn time; this string is the body
            below that header.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    planner: str = Field(min_length=1)
    execute: str = Field(min_length=1)


class PlanExecLoopConfig(BaseModel):
    """Full configuration for one `run_plan_exec_loop` invocation.

    Attributes:
        run_dir: Workspace path the harness will create and own. Must be
            either non-existent or an empty directory at run start; this
            is enforced by `Workspace.create`, not here.
        prompts: Planner + executor prompt bundle.
        agents_md: Caller's project constitution. Written to
            `run_dir/AGENTS.md` before the planner spawns. Must be
            non-empty.
        artifact_seed_dir: Optional directory copied into
            `run_dir/artifact/` before `plan()` runs. If set, must be an
            existing directory.
        max_iters: Maximum number of executor iterations. The planner
            iteration is outside this budget. Must be > 0.
        timeout: Per-iteration wall-clock timeout in seconds. Must be > 0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_dir: Path
    prompts: Prompts
    agents_md: str = Field(min_length=1)
    artifact_seed_dir: Path | None = None
    max_iters: int = Field(gt=0)
    timeout: float = Field(gt=0)

    @field_validator("artifact_seed_dir")
    @classmethod
    def _seed_dir_must_exist(cls, value: Path | None) -> Path | None:
        """Reject a seed dir that does not exist or is not a directory."""
        if value is not None and not value.is_dir():
            raise ValueError(f"artifact_seed_dir does not exist or is not a directory: {value}")
        return value


class FinalStatus(StrEnum):
    """Terminal state of a `run_plan_exec_loop` invocation.

    Values:
        COMPLETED: Loop drained all PENDING tasks within budget.
        BUDGET_EXHAUSTED: `max_iters` reached with PENDING tasks remaining.
        INVALID_PLAN: Plan parser rejected `plan.md` (duplicate ids,
            resurrected `[x]` ids, etc.).
        PROTOCOL_VIOLATION: Executor broke a harness contract (e.g.
            terminated a task other than its selected task).
        TIMEOUT: An iteration exceeded `config.timeout`.
        RUNTIME_ERROR: The runtime raised an unhandled exception.
    """

    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INVALID_PLAN = "invalid_plan"
    PROTOCOL_VIOLATION = "protocol_violation"
    TIMEOUT = "timeout"
    RUNTIME_ERROR = "runtime_error"


class PlanExecLoopResult(BaseModel):
    """Return value of `run_plan_exec_loop` and the deserialized form of `run.json`.

    Attributes:
        run_dir: Absolute path to the run workspace.
        final_status: Terminal `FinalStatus`.
        plan_iter_count: 0 if the planner never produced telemetry, else 1.
        exec_iter_count: Number of executor iterations recorded.
        trajectory_paths: Ordered, run-dir-relative paths to every
            iteration's `trajectory.json`. Planner first, then executors.
        tasks_final: Final parsed `plan.md` task snapshot, in source order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_dir: Path
    final_status: FinalStatus
    plan_iter_count: int = Field(ge=0, le=1)
    exec_iter_count: int = Field(ge=0)
    trajectory_paths: tuple[str, ...] = ()
    tasks_final: tuple[Task, ...] = ()

    @model_validator(mode="after")
    def _trajectory_count_matches_iter_counts(self) -> PlanExecLoopResult:
        """Ensure `trajectory_paths` length agrees with the iteration counts."""
        expected = self.plan_iter_count + self.exec_iter_count
        if len(self.trajectory_paths) != expected:
            raise ValueError(
                f"trajectory_paths length {len(self.trajectory_paths)} does not match "
                f"plan_iter_count + exec_iter_count = {expected}"
            )
        return self

    @field_validator("tasks_final", mode="before")
    @classmethod
    def _coerce_tasks(cls, value: Any) -> Any:
        """Accept lists of dicts (from JSON) and coerce them into `Task` tuples."""
        if not isinstance(value, (list, tuple)):
            return value
        coerced: list[Task] = []
        for item in cast(list[object], value):
            if isinstance(item, Task):
                coerced.append(item)
            elif isinstance(item, dict):
                coerced.append(Task(**cast(dict[str, Any], item)))
            else:
                raise TypeError(f"tasks_final item must be Task or dict, got {type(item)!r}")
        return tuple(coerced)
