"""Validation tests for `harness.config`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.config import (
    FinalStatus,
    PlanExecLoopConfig,
    PlanExecLoopResult,
    Prompts,
)
from harness.types import Task, TaskStatus

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def test_prompts_requires_both_fields() -> None:
    with pytest.raises(ValidationError):
        Prompts(execute="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Prompts(planner="x")  # type: ignore[call-arg]


def test_prompts_rejects_empty_strings() -> None:
    with pytest.raises(ValidationError):
        Prompts(planner="", execute="x")
    with pytest.raises(ValidationError):
        Prompts(planner="x", execute="")


def test_prompts_is_frozen() -> None:
    prompts = Prompts(planner="p", execute="e")
    with pytest.raises(ValidationError):
        prompts.planner = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PlanExecLoopConfig
# ---------------------------------------------------------------------------


_DEFAULT_MAX_ITERS = 3


def _valid_kwargs(tmp_path: Path) -> dict[str, object]:
    return {
        "run_dir": tmp_path / "run",
        "prompts": Prompts(planner="p", execute="e"),
        "agents_md": "# rules\n",
        "max_iters": _DEFAULT_MAX_ITERS,
        "timeout": 60.0,
    }


def test_config_accepts_valid_inputs(tmp_path: Path) -> None:
    cfg = PlanExecLoopConfig(**_valid_kwargs(tmp_path))  # type: ignore[arg-type]
    assert cfg.max_iters == _DEFAULT_MAX_ITERS
    assert cfg.artifact_seed_dir is None


def test_config_rejects_zero_max_iters(tmp_path: Path) -> None:
    kwargs = _valid_kwargs(tmp_path) | {"max_iters": 0}
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_rejects_negative_max_iters(tmp_path: Path) -> None:
    kwargs = _valid_kwargs(tmp_path) | {"max_iters": -1}
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_rejects_zero_timeout(tmp_path: Path) -> None:
    kwargs = _valid_kwargs(tmp_path) | {"timeout": 0.0}
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_rejects_empty_agents_md(tmp_path: Path) -> None:
    kwargs = _valid_kwargs(tmp_path) | {"agents_md": ""}
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_rejects_missing_prompts(tmp_path: Path) -> None:
    kwargs = _valid_kwargs(tmp_path)
    kwargs.pop("prompts")
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_rejects_extra_fields(tmp_path: Path) -> None:
    kwargs = _valid_kwargs(tmp_path) | {"surprise": 1}
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_accepts_existing_artifact_seed_dir(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    kwargs = _valid_kwargs(tmp_path) | {"artifact_seed_dir": seed}
    cfg = PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]
    assert cfg.artifact_seed_dir == seed


def test_config_rejects_missing_artifact_seed_dir(tmp_path: Path) -> None:
    kwargs = _valid_kwargs(tmp_path) | {"artifact_seed_dir": tmp_path / "nope"}
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_rejects_artifact_seed_dir_that_is_a_file(tmp_path: Path) -> None:
    seed = tmp_path / "seed.txt"
    seed.write_text("hi")
    kwargs = _valid_kwargs(tmp_path) | {"artifact_seed_dir": seed}
    with pytest.raises(ValidationError):
        PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def test_config_is_frozen(tmp_path: Path) -> None:
    cfg = PlanExecLoopConfig(**_valid_kwargs(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        cfg.max_iters = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FinalStatus + PlanExecLoopResult
# ---------------------------------------------------------------------------


def test_final_status_covers_every_terminal_state() -> None:
    expected = {
        "completed",
        "budget_exhausted",
        "invalid_plan",
        "protocol_violation",
        "timeout",
        "runtime_error",
    }
    assert {member.value for member in FinalStatus} == expected


def test_result_round_trips_through_json(tmp_path: Path) -> None:
    result = PlanExecLoopResult(
        run_dir=tmp_path / "run",
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
            Task(id="checkout", status=TaskStatus.BLOCKED, priority=2, note="auth wall"),
        ),
    )
    payload = result.model_dump_json()
    restored = PlanExecLoopResult.model_validate_json(payload)
    assert restored == result
    assert restored.final_status is FinalStatus.COMPLETED
    assert restored.tasks_final[0].id == "homepage"


def test_result_rejects_trajectory_count_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        PlanExecLoopResult(
            run_dir=tmp_path / "run",
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=1,
            exec_iter_count=2,
            trajectory_paths=("iters/plan/trajectory.json",),
        )


def test_result_rejects_negative_iter_counts(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        PlanExecLoopResult(
            run_dir=tmp_path / "run",
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=-1,
            exec_iter_count=0,
        )


def test_result_rejects_plan_iter_count_above_one(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        PlanExecLoopResult(
            run_dir=tmp_path / "run",
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=2,
            exec_iter_count=0,
        )


def test_result_is_frozen(tmp_path: Path) -> None:
    result = PlanExecLoopResult(
        run_dir=tmp_path / "run",
        final_status=FinalStatus.BUDGET_EXHAUSTED,
        plan_iter_count=1,
        exec_iter_count=0,
        trajectory_paths=("iters/plan/trajectory.json",),
    )
    with pytest.raises(ValidationError):
        result.exec_iter_count = 5  # type: ignore[misc]


def test_result_defaults_are_empty(tmp_path: Path) -> None:
    result = PlanExecLoopResult(
        run_dir=tmp_path / "run",
        final_status=FinalStatus.COMPLETED,
        plan_iter_count=0,
        exec_iter_count=0,
    )
    assert result.trajectory_paths == ()
    assert result.tasks_final == ()
