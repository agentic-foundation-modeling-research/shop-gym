"""Signature smoke-tests for `harness.loop.run_plan_exec_loop` (T2.4 check).

The full end-to-end behaviour of the loop is exercised by the e2e
suites in T2.6 + T2.7. These tests pin down the public surface
(spec §8.1) and walk through the loop with a stub `AgentRuntime` so a
break in the iteration plumbing is caught without a cassette dependency.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from harness.config import FinalStatus, PlanExecLoopConfig, Prompts
from harness.loop import run_plan_exec_loop
from harness.runtimes.base import AgentRuntime, RuntimeIterationResult
from harness.trajectory import Trajectory

_TS = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)


class _StubRuntime:
    """Minimal `AgentRuntime` that scripts each iteration via a mutator callback."""

    def __init__(
        self,
        scripts: list[Callable[[Path, Path, str], None]],
        runtime_name: str = "stub",
    ) -> None:
        self._scripts = list(scripts)
        self._runtime_name = runtime_name
        self.calls: list[tuple[Path, Path, str, float]] = []

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        self.calls.append((run_dir, iter_dir, prompt, timeout))
        if not self._scripts:
            raise AssertionError("stub runtime exhausted: unexpected extra iteration")
        script = self._scripts.pop(0)
        script(run_dir, iter_dir, prompt)
        trajectory = Trajectory(
            iter_id=iter_dir.name,
            runtime=self._runtime_name,
            started_at=_TS,
            ended_at=_TS + dt.timedelta(seconds=1),
            exit_code=0,
            prompt_sha256="0" * 64,  # the loop overrides this with the real digest
        )
        return RuntimeIterationResult(trajectory=trajectory)


def test_run_plan_exec_loop_signature_matches_spec() -> None:
    sig = inspect.signature(run_plan_exec_loop)
    assert list(sig.parameters) == ["config", "runtime", "force"]
    force_param = sig.parameters["force"]
    assert force_param.kind is inspect.Parameter.KEYWORD_ONLY
    assert force_param.default is False


def test_run_plan_exec_loop_protocol_conformance() -> None:
    # A `_StubRuntime` instance must satisfy the `AgentRuntime` Protocol.
    stub = _StubRuntime(scripts=[])
    assert isinstance(stub, AgentRuntime)


def _config(tmp_path: Path) -> PlanExecLoopConfig:
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="plan-prompt", execute="exec-prompt"),
        agents_md="# rules\n",
        max_iters=3,
        timeout=30.0,
    )


def test_run_plan_exec_loop_drives_planner_then_executor(tmp_path: Path) -> None:
    """Happy path: planner emits one task, executor marks it `[x]`."""

    plan_md = "# Plan\n\n## Tasks\n- [ ] homepage\n"
    plan_done = "# Plan\n\n## Tasks\n- [x] homepage\n"

    def planner_script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text(plan_md, encoding="utf-8")

    def executor_script(run_dir: Path, _iter_dir: Path, prompt: str) -> None:
        # Sanity-check the harness control header reached the executor.
        assert "<<<harness-control>>>" in prompt
        assert "selected_task_id: homepage" in prompt
        (run_dir / "plan.md").write_text(plan_done, encoding="utf-8")

    runtime = _StubRuntime(scripts=[planner_script, executor_script])
    cfg = _config(tmp_path)

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.COMPLETED
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == 1
    assert result.trajectory_paths == (
        "iters/plan/trajectory.json",
        "iters/exec-0001/trajectory.json",
    )
    assert tuple(t.id for t in result.tasks_final) == ("homepage",)

    # `run.json` was rewritten and matches the returned result.
    assert (cfg.run_dir / "run.json").is_file()

    # Plan + exec iter dirs both exist with the §5.3 sidecars.
    plan_dir = cfg.run_dir / "iters" / "plan"
    exec_dir = cfg.run_dir / "iters" / "exec-0001"
    for d in (plan_dir, exec_dir):
        assert (d / "trajectory.json").is_file()
        assert (d / "metadata.json").is_file()
        assert (d / "plan.before.md").is_file()
        assert (d / "plan.after.md").is_file()
    assert (exec_dir / "checks" / "protocol.json").is_file()


def test_run_plan_exec_loop_completes_when_planner_makes_no_tasks(
    tmp_path: Path,
) -> None:
    """An empty `## Tasks` section completes immediately without exec iters."""

    def planner_script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text("# Plan\n\n## Tasks\n", encoding="utf-8")

    runtime = _StubRuntime(scripts=[planner_script])

    result = run_plan_exec_loop(_config(tmp_path), runtime)

    assert result.final_status is FinalStatus.COMPLETED
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == 0
    assert result.tasks_final == ()


def test_run_plan_exec_loop_overrides_prompt_sha256_with_actual_prompt(
    tmp_path: Path,
) -> None:
    """The loop recomputes `prompt_sha256` from the prompt it sent."""

    def planner_script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text("# Plan\n\n## Tasks\n", encoding="utf-8")

    runtime = _StubRuntime(scripts=[planner_script])
    cfg = _config(tmp_path)
    run_plan_exec_loop(cfg, runtime)

    expected = hashlib.sha256(cfg.prompts.planner.encode("utf-8")).hexdigest()
    payload = json.loads(
        (cfg.run_dir / "iters" / "plan" / "trajectory.json").read_text(encoding="utf-8")
    )
    assert payload["prompt_sha256"] == expected


def test_run_plan_exec_loop_maps_runtime_exception_to_runtime_error(
    tmp_path: Path,
) -> None:
    """A runtime exception other than TimeoutExpired aborts as RUNTIME_ERROR."""

    class _BoomRuntime:
        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del run_dir, iter_dir, prompt, timeout
            raise RuntimeError("boom")

    result = run_plan_exec_loop(_config(tmp_path), _BoomRuntime())

    assert result.final_status is FinalStatus.RUNTIME_ERROR
    assert result.plan_iter_count == 0
    assert result.exec_iter_count == 0


def test_run_plan_exec_loop_maps_timeout_to_timeout_status(tmp_path: Path) -> None:
    """`subprocess.TimeoutExpired` from the runtime maps to FinalStatus.TIMEOUT."""

    class _SlowRuntime:
        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del run_dir, iter_dir, prompt
            raise subprocess.TimeoutExpired(cmd="agent", timeout=timeout)

    result = run_plan_exec_loop(_config(tmp_path), _SlowRuntime())

    assert result.final_status is FinalStatus.TIMEOUT


def test_run_plan_exec_loop_executor_timeout_keeps_counts_consistent(
    tmp_path: Path,
) -> None:
    """Executor timeout after a successful planner must not desync iter counts.

    Regression: `_exec_iter_count` was incremented before the runtime
    invocation, so a timeout left `trajectory_paths` short by one and
    `PlanExecLoopResult` failed validation.
    """

    plan_md = "# Plan\n\n## Tasks\n- [ ] homepage\n"

    def planner_script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text(plan_md, encoding="utf-8")

    class _PlannerThenTimeoutRuntime:
        def __init__(self) -> None:
            self._calls = 0

        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            self._calls += 1
            if self._calls == 1:
                planner_script(run_dir, iter_dir, prompt)
                return RuntimeIterationResult(
                    trajectory=Trajectory(
                        iter_id=iter_dir.name,
                        runtime="stub",
                        started_at=_TS,
                        ended_at=_TS + dt.timedelta(seconds=1),
                        exit_code=0,
                        prompt_sha256="0" * 64,
                    )
                )
            raise subprocess.TimeoutExpired(cmd="agent", timeout=timeout)

    result = run_plan_exec_loop(_config(tmp_path), _PlannerThenTimeoutRuntime())

    assert result.final_status is FinalStatus.TIMEOUT
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == 0
    assert result.trajectory_paths == ("iters/plan/trajectory.json",)


def test_run_plan_exec_loop_budget_exhausted_when_pending_remain(tmp_path: Path) -> None:
    """When `max_iters` is reached with PENDING tasks left, status is BUDGET_EXHAUSTED."""

    plan_two_pending = "# Plan\n\n## Tasks\n- [ ] homepage\n- [ ] checkout\n"
    plan_one_done = "# Plan\n\n## Tasks\n- [x] homepage\n- [ ] checkout\n"

    def planner_script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text(plan_two_pending, encoding="utf-8")

    def executor_script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text(plan_one_done, encoding="utf-8")

    runtime = _StubRuntime(scripts=[planner_script, executor_script])
    cfg = PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="plan-prompt", execute="exec-prompt"),
        agents_md="# rules\n",
        max_iters=1,  # only one executor iteration allowed
        timeout=30.0,
    )

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.BUDGET_EXHAUSTED
    assert result.exec_iter_count == 1
