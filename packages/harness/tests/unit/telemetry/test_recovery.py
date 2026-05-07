"""Tests for `harness.telemetry.recovery.reconstruct`."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from harness.config import FinalStatus, PlanExecLoopConfig, PlanExecLoopResult, Prompts
from harness.telemetry import RunSummaryWriter, reconstruct
from harness.trajectory import IterationMetadata, ProtocolCheckResult, Trajectory
from harness.workspace import Workspace

_TWO_EXEC_ITERS = 2
_TS = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)

_PLAN_TWO_DONE = "# Plan\n\n## Tasks\n- [x] homepage\n- [x] checkout — auth wall handled\n"


def _config(tmp_path: Path) -> PlanExecLoopConfig:
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="p", execute="e"),
        agents_md="# rules\n",
        max_iters=3,
        timeout=60.0,
    )


def _trajectory(iter_id: str) -> Trajectory:
    return Trajectory(
        iter_id=iter_id,
        runtime="replay",
        started_at=_TS,
        ended_at=_TS + dt.timedelta(seconds=1),
        exit_code=0,
        prompt_sha256="0" * 64,
    )


def _metadata(iter_id: str, kind: str, **extra: object) -> IterationMetadata:
    return IterationMetadata(
        iter_id=iter_id,
        iter_kind=kind,  # type: ignore[arg-type]
        runtime="replay",
        started_at=_TS,
        ended_at=_TS + dt.timedelta(seconds=1),
        **extra,  # type: ignore[arg-type]
    )


def _write_iter(
    ws: Workspace,
    iter_id: str,
    kind: str,
    *,
    plan_before: str = "",
    plan_after: str = "",
    selected_task_id: str | None = None,
    completed: tuple[str, ...] = (),
    blocked: tuple[str, ...] = (),
    added: tuple[str, ...] = (),
    protocol: ProtocolCheckResult | None = None,
) -> Path:
    d = ws.iters_dir / iter_id
    d.mkdir(parents=True)
    (d / "trajectory.json").write_text(_trajectory(iter_id).model_dump_json(), encoding="utf-8")
    (d / "native.log").write_text("", encoding="utf-8")
    (d / "plan.before.md").write_text(plan_before, encoding="utf-8")
    (d / "plan.after.md").write_text(plan_after, encoding="utf-8")
    meta_kwargs: dict[str, object] = {}
    if selected_task_id is not None:
        meta_kwargs["selected_task_id"] = selected_task_id
        meta_kwargs["completed_task_ids"] = completed
        meta_kwargs["blocked_task_ids"] = blocked
        meta_kwargs["added_task_ids"] = added
    (d / "metadata.json").write_text(
        _metadata(iter_id, kind, **meta_kwargs).model_dump_json(), encoding="utf-8"
    )
    if protocol is not None:
        (d / "checks").mkdir()
        (d / "checks" / "protocol.json").write_text(protocol.model_dump_json(), encoding="utf-8")
    return d


def test_reconstruct_rebuilds_completed_run_from_iters_tree(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    ws.plan_md.write_text(_PLAN_TWO_DONE, encoding="utf-8")
    _write_iter(ws, "plan", "plan", plan_after=_PLAN_TWO_DONE)
    _write_iter(
        ws,
        "exec-0001",
        "exec",
        plan_before=_PLAN_TWO_DONE,
        plan_after=_PLAN_TWO_DONE,
        selected_task_id="homepage",
        completed=("homepage",),
        protocol=ProtocolCheckResult(iter_id="exec-0001", passed=True),
    )
    _write_iter(
        ws,
        "exec-0002",
        "exec",
        plan_before=_PLAN_TWO_DONE,
        plan_after=_PLAN_TWO_DONE,
        selected_task_id="checkout",
        completed=("checkout",),
        protocol=ProtocolCheckResult(iter_id="exec-0002", passed=True),
    )

    result = reconstruct(ws.run_dir)

    assert result.final_status is FinalStatus.COMPLETED
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == _TWO_EXEC_ITERS
    assert result.trajectory_paths == (
        "iters/plan/trajectory.json",
        "iters/exec-0001/trajectory.json",
        "iters/exec-0002/trajectory.json",
    )
    assert tuple(t.id for t in result.tasks_final) == ("homepage", "checkout")


def test_reconstruct_returns_budget_exhausted_when_pending_remains(
    tmp_path: Path,
) -> None:
    ws = Workspace.create(_config(tmp_path))
    plan = "# Plan\n\n## Tasks\n- [x] homepage\n- [ ] checkout\n"
    ws.plan_md.write_text(plan, encoding="utf-8")
    _write_iter(ws, "plan", "plan", plan_after=plan)
    _write_iter(
        ws,
        "exec-0001",
        "exec",
        plan_before=plan,
        plan_after=plan,
        selected_task_id="homepage",
        completed=("homepage",),
        protocol=ProtocolCheckResult(iter_id="exec-0001", passed=True),
    )

    result = reconstruct(ws.run_dir)

    assert result.final_status is FinalStatus.BUDGET_EXHAUSTED
    assert result.exec_iter_count == 1


def test_reconstruct_returns_invalid_plan_when_plan_unparseable(
    tmp_path: Path,
) -> None:
    ws = Workspace.create(_config(tmp_path))
    ws.plan_md.write_text("# Plan\n\nno tasks heading here\n", encoding="utf-8")
    _write_iter(ws, "plan", "plan")

    result = reconstruct(ws.run_dir)

    assert result.final_status is FinalStatus.INVALID_PLAN
    assert result.tasks_final == ()
    assert result.plan_iter_count == 1


def test_reconstruct_returns_protocol_violation_when_check_failed(
    tmp_path: Path,
) -> None:
    ws = Workspace.create(_config(tmp_path))
    plan = "# Plan\n\n## Tasks\n- [x] homepage\n- [x] checkout\n"
    ws.plan_md.write_text(plan, encoding="utf-8")
    _write_iter(ws, "plan", "plan", plan_after=plan)
    _write_iter(
        ws,
        "exec-0001",
        "exec",
        plan_before=plan,
        plan_after=plan,
        selected_task_id="homepage",
        completed=("homepage", "checkout"),
        protocol=ProtocolCheckResult(
            iter_id="exec-0001",
            passed=False,
            violations=("non-selected tasks newly marked terminal: ['checkout']",),
        ),
    )

    result = reconstruct(ws.run_dir)

    assert result.final_status is FinalStatus.PROTOCOL_VIOLATION


def test_reconstruct_skips_iter_dirs_without_trajectory(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    ws.plan_md.write_text(_PLAN_TWO_DONE, encoding="utf-8")
    _write_iter(ws, "plan", "plan", plan_after=_PLAN_TWO_DONE)
    # exec-0001 wrote telemetry; exec-0002 crashed before emitting trajectory.json.
    _write_iter(
        ws,
        "exec-0001",
        "exec",
        plan_before=_PLAN_TWO_DONE,
        plan_after=_PLAN_TWO_DONE,
        selected_task_id="homepage",
        completed=("homepage",),
        protocol=ProtocolCheckResult(iter_id="exec-0001", passed=True),
    )
    crashed = ws.iters_dir / "exec-0002"
    crashed.mkdir()
    (crashed / "plan.before.md").write_text(_PLAN_TWO_DONE, encoding="utf-8")

    result = reconstruct(ws.run_dir)

    assert result.exec_iter_count == 1
    assert result.trajectory_paths == (
        "iters/plan/trajectory.json",
        "iters/exec-0001/trajectory.json",
    )


def test_reconstruct_handles_empty_plan_md(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    # Default `Workspace.create` leaves plan.md empty; no iterations recorded.

    result = reconstruct(ws.run_dir)

    assert result.final_status is FinalStatus.COMPLETED
    assert result.plan_iter_count == 0
    assert result.exec_iter_count == 0
    assert result.tasks_final == ()


def test_reconstruct_round_trips_through_rewrite(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    ws.plan_md.write_text(_PLAN_TWO_DONE, encoding="utf-8")
    _write_iter(ws, "plan", "plan", plan_after=_PLAN_TWO_DONE)
    _write_iter(
        ws,
        "exec-0001",
        "exec",
        plan_before=_PLAN_TWO_DONE,
        plan_after=_PLAN_TWO_DONE,
        selected_task_id="homepage",
        completed=("homepage",),
        protocol=ProtocolCheckResult(iter_id="exec-0001", passed=True),
    )
    _write_iter(
        ws,
        "exec-0002",
        "exec",
        plan_before=_PLAN_TWO_DONE,
        plan_after=_PLAN_TWO_DONE,
        selected_task_id="checkout",
        completed=("checkout",),
        protocol=ProtocolCheckResult(iter_id="exec-0002", passed=True),
    )
    result = reconstruct(ws.run_dir)

    RunSummaryWriter.rewrite(ws.run_dir, result=result)

    payload = json.loads(ws.run_summary.read_text(encoding="utf-8"))
    restored = PlanExecLoopResult.model_validate(payload)
    assert restored == result


def test_reconstruct_raises_when_iters_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "bare"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        reconstruct(run_dir)
