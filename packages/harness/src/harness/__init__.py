"""harness: plan + exec orchestration engine for LLM agents.

Runtime-agnostic. Owns process lifecycle, a workspace state machine,
and normalized telemetry. Owns no prompts, no tools, no domain knowledge.

The names re-exported below are the public v0.1 surface defined in
`docs/specs/harness/plan_exec_loop.md` §8.1. Anything not listed here
is internal and may change without notice.
"""

from __future__ import annotations

from harness.config import PlanExecLoopConfig, PlanExecLoopResult, Prompts
from harness.loop import run_plan_exec_loop
from harness.plan.tasks import Task, TaskList, TaskStatus
from harness.runtimes import AgentRuntime, get_runtime
from harness.trajectory import (
    IterationMetadata,
    ProtocolCheckResult,
    Trajectory,
    TrajectoryStep,
)

__all__ = [
    "AgentRuntime",
    "IterationMetadata",
    "PlanExecLoopConfig",
    "PlanExecLoopResult",
    "Prompts",
    "ProtocolCheckResult",
    "Task",
    "TaskList",
    "TaskStatus",
    "Trajectory",
    "TrajectoryStep",
    "get_runtime",
    "run_plan_exec_loop",
]

__version__ = "0.2.0"
