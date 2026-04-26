"""Tests for `harness.telemetry.ids`."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.config import PlanExecLoopConfig, Prompts
from harness.telemetry import PLAN_ITER_ID, exec_iter_id, iter_dir
from harness.workspace import Workspace


def _config(tmp_path: Path) -> PlanExecLoopConfig:
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="p", execute="e"),
        agents_md="# rules\n",
        max_iters=3,
        timeout=60.0,
    )


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
