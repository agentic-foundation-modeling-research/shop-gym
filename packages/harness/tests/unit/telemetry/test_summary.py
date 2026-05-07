"""Tests for `harness.telemetry.summary.RunSummaryWriter`."""

from __future__ import annotations

import json
from pathlib import Path

from harness.config import FinalStatus, PlanExecLoopResult
from harness.plan.tasks import Task, TaskStatus
from harness.telemetry import RunSummaryWriter

_TWO_EXEC_ITERS = 2
_SAMPLE_MAX_ITERS = 3


def _make_result(run_dir: Path) -> PlanExecLoopResult:
    return PlanExecLoopResult(
        run_dir=run_dir,
        final_status=FinalStatus.COMPLETED,
        plan_iter_count=1,
        exec_iter_count=2,
        trajectory_paths=(
            "iters/plan/trajectory.json",
            "iters/exec-0001/trajectory.json",
            "iters/exec-0002/trajectory.json",
        ),
        tasks_final=(
            Task(id="homepage", status=TaskStatus.DONE),
            Task(id="checkout", status=TaskStatus.DONE, note="auth wall handled"),
        ),
    )


def test_rewrite_writes_result_payload(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = _make_result(run_dir)

    RunSummaryWriter.rewrite(run_dir, result=result)

    payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == "completed"
    assert payload["exec_iter_count"] == _TWO_EXEC_ITERS
    assert payload["trajectory_paths"] == [
        "iters/plan/trajectory.json",
        "iters/exec-0001/trajectory.json",
        "iters/exec-0002/trajectory.json",
    ]
    # Result reloads cleanly when no config_snapshot is attached.
    assert "config_snapshot" not in payload
    restored = PlanExecLoopResult.model_validate(payload)
    assert restored == result


def test_rewrite_attaches_scrubbed_config_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = _make_result(run_dir)

    RunSummaryWriter.rewrite(
        run_dir,
        result=result,
        config_snapshot={
            "runtime": "claude_code",
            "max_iters": 3,
            "api_key": "sk-secret-do-not-leak",
            "runtime_kwargs": {"auth_token": "leak-too"},
        },
    )

    payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    snapshot = payload["config_snapshot"]
    assert snapshot["runtime"] == "claude_code"
    assert snapshot["max_iters"] == _SAMPLE_MAX_ITERS
    assert snapshot["api_key"] == "***REDACTED***"
    assert snapshot["runtime_kwargs"]["auth_token"] == "***REDACTED***"
    raw = (run_dir / "run.json").read_text(encoding="utf-8")
    assert "sk-secret-do-not-leak" not in raw
    assert "leak-too" not in raw


def test_rewrite_overwrites_existing_run_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text("stale", encoding="utf-8")
    result = _make_result(run_dir)

    RunSummaryWriter.rewrite(run_dir, result=result)

    payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == "completed"
