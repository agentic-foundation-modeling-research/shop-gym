"""End-to-end terminal-status tests for `run_plan_exec_loop` (T2.7).

Drives the loop with handcrafted bad cassettes (and two tiny failing
runtimes for the runtime-side errors) so every `FinalStatus` other than
`COMPLETED` is reachable from at least one test. Cassette construction
uses `ReplayRuntime` against per-test scratch scenarios so each scenario
stays self-contained and the canonical `tests/cassettes/` tree is left
untouched.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Final

from harness.config import FinalStatus, PlanExecLoopConfig, Prompts
from harness.loop import run_plan_exec_loop
from harness.runtimes.base import RuntimeIterationResult
from harness.runtimes.replay import ReplayRuntime
from harness.trajectory import Trajectory

_TS: Final[dt.datetime] = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
_PROMPT_SHA_PLACEHOLDER: Final[str] = "0" * 64


def _trajectory(iter_id: str) -> Trajectory:
    """Build a minimal `Trajectory` for cassette fixtures."""
    return Trajectory(
        iter_id=iter_id,
        runtime="replay",
        started_at=_TS,
        ended_at=_TS,
        exit_code=0,
        prompt_sha256=_PROMPT_SHA_PLACEHOLDER,
    )


def _write_cassette(
    scenario_dir: Path,
    iter_id: str,
    *,
    plan_md: str,
) -> None:
    """Materialise a minimal cassette: trajectory + `workspace_after/plan.md`."""
    cassette_dir = scenario_dir / iter_id
    cassette_dir.mkdir(parents=True)
    (cassette_dir / "trajectory.json").write_text(
        json.dumps(_trajectory(iter_id).model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    overlay = cassette_dir / "workspace_after"
    overlay.mkdir()
    (overlay / "plan.md").write_text(plan_md, encoding="utf-8")


def _config(tmp_path: Path, *, max_iters: int = 5) -> PlanExecLoopConfig:
    """Build a `PlanExecLoopConfig` rooted at `tmp_path/run`."""
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="planner-prompt", execute="execute-prompt"),
        agents_md="# AGENTS\n",
        max_iters=max_iters,
        timeout=30.0,
    )


# ---------------------------------------------------------------------------
# Plan-driven terminal statuses
# ---------------------------------------------------------------------------


def test_invalid_plan_when_planner_emits_duplicate_ids(tmp_path: Path) -> None:
    """Planner output with duplicate task ids → `FinalStatus.INVALID_PLAN`."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md=(
            "# Plan\n\n## Tasks\n- [ ] homepage   [priority: 2]\n- [ ] homepage   [priority: 1]\n"
        ),
    )

    runtime = ReplayRuntime(scenario_dir)
    result = run_plan_exec_loop(_config(tmp_path), runtime)

    assert result.final_status is FinalStatus.INVALID_PLAN
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == 0
    # Telemetry for the planner iteration is still persisted before the
    # state-machine abort: the `plan/` directory must exist with its
    # trajectory recorded.
    assert (result.run_dir / "iters" / "plan" / "trajectory.json").is_file()


def test_executor_protocol_violation_blocks_task_and_continues(tmp_path: Path) -> None:
    """Executor protocol violation → BLOCKED + skip set, loop continues.

    Spec ``docs/specs/harness/protocol_violation_recovery.md``: an
    executor-phase protocol violation is no longer terminal. The selected
    task is forcibly marked ``[!]`` BLOCKED, added to the skip set, and
    the loop picks the next-priority pending task.
    """
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md=(
            "# Plan\n\n"
            "## Tasks\n"
            "- [ ] homepage         [priority: 2]\n"
            "- [ ] product_detail   [priority: 1]\n"
        ),
    )
    # Selected task is `homepage` (highest priority), but this cassette
    # marks both tasks `[x]` — the protocol check catches the unrelated
    # transition on `product_detail`. Recovery must: mark `homepage` `[!]`,
    # restore the plan, then run exec-0002 against `product_detail`.
    _write_cassette(
        scenario_dir,
        "exec-0001",
        plan_md=(
            "# Plan\n\n"
            "## Tasks\n"
            "- [x] homepage         [priority: 2]\n"
            "- [x] product_detail   [priority: 1]\n"
        ),
    )
    _write_cassette(
        scenario_dir,
        "exec-0002",
        plan_md=(
            "# Plan\n\n"
            "## Tasks\n"
            "- [!] homepage         [priority: 2] — protocol_violation: selected_terminal\n"
            "- [x] product_detail   [priority: 1]\n"
        ),
    )

    runtime = ReplayRuntime(scenario_dir)
    result = run_plan_exec_loop(_config(tmp_path), runtime)

    # Run reaches COMPLETED — every remaining PENDING task drained, the
    # BLOCKED task counts as terminal.
    assert result.final_status is FinalStatus.COMPLETED
    assert result.exec_iter_count == 2  # noqa: PLR2004 — exec-0001 (violation) + exec-0002

    # The first iteration's protocol.json still records the violation.
    protocol_path = result.run_dir / "iters" / "exec-0001" / "checks" / "protocol.json"
    assert protocol_path.is_file()
    payload = json.loads(protocol_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("product_detail" in v for v in payload["violations"])

    # The live plan.md after recovery shows `homepage` BLOCKED with a
    # ``protocol_violation`` note.
    final_plan = (result.run_dir / "plan.md").read_text(encoding="utf-8")
    assert "[!] homepage" in final_plan
    assert "protocol_violation" in final_plan


def test_budget_exhausted_when_pending_tasks_remain(tmp_path: Path) -> None:
    """`max_iters=1` with two PENDING tasks → `FinalStatus.BUDGET_EXHAUSTED`."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md=(
            "# Plan\n\n"
            "## Tasks\n"
            "- [ ] homepage         [priority: 2]\n"
            "- [ ] product_detail   [priority: 1]\n"
        ),
    )
    _write_cassette(
        scenario_dir,
        "exec-0001",
        plan_md=(
            "# Plan\n\n"
            "## Tasks\n"
            "- [x] homepage         [priority: 2]\n"
            "- [ ] product_detail   [priority: 1]\n"
        ),
    )

    runtime = ReplayRuntime(scenario_dir)
    result = run_plan_exec_loop(_config(tmp_path, max_iters=1), runtime)

    assert result.final_status is FinalStatus.BUDGET_EXHAUSTED
    assert result.exec_iter_count == 1
    final_ids_to_status = {t.id: t.status.value for t in result.tasks_final}
    assert final_ids_to_status == {"homepage": "done", "product_detail": "pending"}


# ---------------------------------------------------------------------------
# Runtime-driven terminal statuses
# ---------------------------------------------------------------------------


class _RaisingRuntime:
    """Tiny `AgentRuntime` that raises a fixed exception on first invocation.

    Used to drive the harness's exception-mapping branches in `loop.py`
    without standing up a full subprocess. Records the call count so tests
    can assert the harness aborted on the planner iteration rather than
    silently retrying.
    """

    def __init__(self, error: BaseException) -> None:
        """Initialise with the exception to raise on `run_iteration`."""
        self._error = error
        self.call_count = 0

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Increment the call counter and re-raise the configured exception."""
        del run_dir, iter_dir, prompt, timeout
        self.call_count += 1
        raise self._error


def test_timeout_when_runtime_raises_timeout_expired(tmp_path: Path) -> None:
    """`subprocess.TimeoutExpired` bubbling out of the runtime → `FinalStatus.TIMEOUT`."""
    runtime = _RaisingRuntime(subprocess.TimeoutExpired(cmd="agent", timeout=1.0))

    result = run_plan_exec_loop(_config(tmp_path), runtime)

    assert result.final_status is FinalStatus.TIMEOUT
    assert result.plan_iter_count == 0
    assert result.exec_iter_count == 0
    assert result.trajectory_paths == ()
    assert runtime.call_count == 1


def test_runtime_error_when_runtime_raises_unhandled_exception(tmp_path: Path) -> None:
    """Any other exception from the runtime → `FinalStatus.RUNTIME_ERROR`."""
    runtime = _RaisingRuntime(RuntimeError("LLM unavailable"))

    result = run_plan_exec_loop(_config(tmp_path), runtime)

    assert result.final_status is FinalStatus.RUNTIME_ERROR
    assert result.plan_iter_count == 0
    assert result.exec_iter_count == 0
    assert result.trajectory_paths == ()
    assert runtime.call_count == 1
