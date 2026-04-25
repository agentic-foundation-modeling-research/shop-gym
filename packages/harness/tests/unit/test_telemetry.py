"""Tests for `harness.telemetry`."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from harness.config import FinalStatus, PlanExecLoopConfig, PlanExecLoopResult, Prompts
from harness.telemetry import (
    PLAN_ITER_ID,
    RunSummaryWriter,
    exec_iter_id,
    iter_dir,
    reconstruct,
    scrub_secrets,
)
from harness.types import (
    IterationMetadata,
    ProtocolCheckResult,
    Task,
    TaskStatus,
    Trajectory,
)
from harness.workspace import Workspace

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TWO_EXEC_ITERS = 2
_SAMPLE_MAX_ITERS = 3
_SCRUB_SAMPLE_INT = 42

_TS = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)


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


# ---------------------------------------------------------------------------
# iteration id helpers
# ---------------------------------------------------------------------------


def test_exec_iter_id_zero_pads_to_four_digits() -> None:
    assert exec_iter_id(1) == "exec-0001"
    assert exec_iter_id(42) == "exec-0042"
    assert exec_iter_id(9999) == "exec-9999"


def test_exec_iter_id_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        exec_iter_id(0)
    with pytest.raises(ValueError):
        exec_iter_id(-1)


def test_iter_dir_resolves_planner(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    assert iter_dir(ws, PLAN_ITER_ID) == ws.iters_dir / "plan"


def test_iter_dir_resolves_executor(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    assert iter_dir(ws, "exec-0007") == ws.iters_dir / "exec-0007"


def test_iter_dir_does_not_create_directory(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    path = iter_dir(ws, "exec-0001")
    assert not path.exists()


def test_iter_dir_rejects_unknown_iter_id(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    with pytest.raises(ValueError):
        iter_dir(ws, "exec-1")  # not zero-padded
    with pytest.raises(ValueError):
        iter_dir(ws, "planner")
    with pytest.raises(ValueError):
        iter_dir(ws, "../escape")


# ---------------------------------------------------------------------------
# scrub_secrets
# ---------------------------------------------------------------------------


def test_scrub_secrets_redacts_top_level_secret_keys() -> None:
    out = scrub_secrets({"api_key": "sk-abc", "model": "gpt-5"})
    assert out == {"api_key": "***REDACTED***", "model": "gpt-5"}


def test_scrub_secrets_handles_common_secret_names() -> None:
    payload = {
        "api_key": "x",
        "API_KEY": "x",
        "ApiKey": "x",
        "api-key": "x",
        "openai_api_key": "x",
        "secret": "x",
        "client_secret": "x",
        "password": "x",
        "auth_token": "x",
        "access_key": "x",
    }
    redacted = scrub_secrets(payload)
    assert all(v == "***REDACTED***" for v in redacted.values())


def test_scrub_secrets_does_not_redact_innocent_keys() -> None:
    out = scrub_secrets({"runtime": "replay", "max_iters": 3, "timeout": 60.0})
    assert out == {"runtime": "replay", "max_iters": 3, "timeout": 60.0}


def test_scrub_secrets_recurses_into_nested_mappings() -> None:
    out = scrub_secrets(
        {
            "runtime": {"name": "claude_code", "api_key": "sk-abc"},
            "config": {"max_iters": 3, "secrets": {"token": "t"}},
        }
    )
    assert out == {
        "runtime": {"name": "claude_code", "api_key": "***REDACTED***"},
        "config": {"max_iters": 3, "secrets": "***REDACTED***"},
    }


def test_scrub_secrets_recurses_into_lists() -> None:
    out = scrub_secrets({"runtimes": [{"api_key": "k1"}, {"api_key": "k2"}]})
    assert out == {"runtimes": [{"api_key": "***REDACTED***"}, {"api_key": "***REDACTED***"}]}


def test_scrub_secrets_returns_scalars_unchanged() -> None:
    assert scrub_secrets("hello") == "hello"
    assert scrub_secrets(_SCRUB_SAMPLE_INT) == _SCRUB_SAMPLE_INT
    assert scrub_secrets(None) is None


# ---------------------------------------------------------------------------
# RunSummaryWriter.rewrite
# ---------------------------------------------------------------------------


_PLAN_TWO_DONE = "# Plan\n\n## Tasks\n- [x] homepage\n- [x] checkout — auth wall handled\n"


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


# ---------------------------------------------------------------------------
# reconstruct
# ---------------------------------------------------------------------------


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
