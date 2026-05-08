"""Shared toy-scenario helpers for live-CLI smoke tests (impl plan T3.4).

Smoke tests drive a real CLI runtime through the same scenario the
per-runtime ``toy_homepage_<runtime>`` cassettes encode (impl plan
T3.3): create a two-task plan, then execute each task in priority
order. This module is private (leading underscore) so pytest does not
collect it as a test module; the public smoke tests in this package
and the recording script under ``scripts/`` import from it.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Final

from harness.config import FinalStatus, PlanExecLoopConfig, PlanExecLoopResult, Prompts
from harness.loop import run_plan_exec_loop
from harness.runtimes.base import AgentRuntime
from harness.trajectory import Trajectory

# Expected terminal task list (ids and statuses) for the toy scenario.
EXPECTED_TASK_IDS: Final[tuple[str, ...]] = ("homepage", "product_detail")
EXPECTED_EXEC_IDS: Final[tuple[str, ...]] = ("exec-0001", "exec-0002")

# Cassette step kinds we require the live run to also produce. Anything
# the hand-authored cassette emits, a faithful CLI run must also emit at
# least once across the same iteration.
_REQUIRED_KINDS_BY_ITER: Final[dict[str, frozenset[str]]] = {
    "plan": frozenset({"message"}),
    "exec-0001": frozenset({"tool_call", "tool_result", "message"}),
    "exec-0002": frozenset({"tool_call", "tool_result", "message"}),
}


_PLANNER_PROMPT: Final[str] = """\
You are the planner for a tiny smoke-test scenario. Write a fresh
`plan.md` in the current working directory with EXACTLY this content,
then exit without doing any task work:

# Plan

## Tasks
- [ ] homepage          [priority: 2]
- [ ] product_detail    [priority: 1]

Do not create or modify any other files. Do not mark any task done.
"""

_EXECUTE_PROMPT: Final[str] = """\
You are the executor for one iteration of a tiny smoke-test scenario.

The harness control header above this prompt names `selected_task_id`;
that is the ONLY task you may modify. Read `plan.md`, then:

1. Flip the selected task's checkbox from `[ ]` to `[~]`.
2. Create `artifact/<selected_task_id>.md` with a one-line description
   of the surface (e.g. "homepage: hero, nav, footer").
3. Self-check: confirm the artifact file exists and the only status
   change is on the selected task.
4. Flip the selected task's checkbox from `[~]` to `[x]`.
5. Exit.

Do not modify any other task's status. Do not add new tasks.
"""

AGENTS_MD: Final[str] = """\
# AGENTS

This is a smoke-test workspace for the harness. The plan file is
`plan.md`; the deliverable directory is `artifact/`. Every iteration
should read `AGENTS.md` and `plan.md` first, then act per the prompt.
"""


def build_config(run_dir: Path, *, timeout: float) -> PlanExecLoopConfig:
    """Return the toy-scenario `PlanExecLoopConfig` rooted at ``run_dir``."""
    return PlanExecLoopConfig(
        run_dir=run_dir,
        prompts=Prompts(planner=_PLANNER_PROMPT, execute=_EXECUTE_PROMPT),
        agents_md=AGENTS_MD,
        max_iters=4,
        timeout=timeout,
    )


def assert_toy_run_succeeded(result: PlanExecLoopResult) -> None:
    """Assert the live run terminated cleanly with both toy tasks done."""
    assert result.final_status is FinalStatus.COMPLETED, (
        f"expected COMPLETED, got {result.final_status} "
        f"(plan={result.plan_iter_count}, exec={result.exec_iter_count})"
    )
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == len(EXPECTED_EXEC_IDS)
    final_ids = tuple(t.id for t in result.tasks_final)
    assert final_ids == EXPECTED_TASK_IDS, f"expected tasks {EXPECTED_TASK_IDS}, got {final_ids}"
    assert all(t.status.value == "done" for t in result.tasks_final), (
        "all toy tasks must be marked done after a clean smoke run"
    )


def assert_step_kinds_within_tolerance(run_dir: Path) -> None:
    """Assert each iteration produced the step kinds the cassette requires.

    Real runs are noisier than the hand-authored cassette: they typically
    emit extra ``thought`` blocks, retry messages, or read-only tool
    calls. The tolerance therefore checks one direction only — every
    step kind present in the cassette must also appear at least once in
    the live trajectory for the same iteration.
    """
    for iter_id, required in _REQUIRED_KINDS_BY_ITER.items():
        trajectory_path = run_dir / "iters" / iter_id / "trajectory.json"
        assert trajectory_path.is_file(), f"missing trajectory.json for {iter_id}"
        trajectory = Trajectory.model_validate(
            json.loads(trajectory_path.read_text(encoding="utf-8"))
        )
        kinds = Counter(step.kind for step in trajectory.steps)
        missing = sorted(k for k in required if kinds[k] == 0)
        assert not missing, (
            f"{iter_id}: missing required step kinds {missing}; observed kinds={dict(kinds)}"
        )


def run_toy_scenario(
    runtime: AgentRuntime,
    *,
    run_dir: Path,
    timeout: float,
) -> PlanExecLoopResult:
    """Execute the toy scenario end-to-end against ``runtime``."""
    config = build_config(run_dir, timeout=timeout)
    return run_plan_exec_loop(config, runtime)
