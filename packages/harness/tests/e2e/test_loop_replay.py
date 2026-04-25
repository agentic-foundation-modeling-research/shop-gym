"""End-to-end replay test for `run_plan_exec_loop` (T2.6).

Drives a full toy run against the per-runtime ``toy_homepage_*``
cassettes under ``ReplayRuntime`` and asserts the harness produces the
§5.3 workspace layout, terminates with ``FinalStatus.COMPLETED``, and
that ``telemetry.reconstruct`` rebuilds the same `PlanExecLoopResult`
from disk (SC1 + SC3).

Cassettes are recorded against each real CLI runtime (impl plan T3.3)
via ``scripts/record_toy_cassette.py`` so the e2e suite catches drift in
either runtime's stream-event contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.config import FinalStatus, PlanExecLoopConfig, Prompts
from harness.loop import run_plan_exec_loop
from harness.runtimes import get_runtime
from harness.telemetry import reconstruct

_CASSETTE_ROOT = Path(__file__).resolve().parent.parent / "cassettes"
_RUNTIME_NAMES = ("claude_code", "pi")
_CASSETTE_DIRS = tuple(_CASSETTE_ROOT / f"toy_homepage_{name}" for name in _RUNTIME_NAMES)
_EXPECTED_EXEC_IDS = ("exec-0001", "exec-0002")


def _config(tmp_path: Path) -> PlanExecLoopConfig:
    """Build a `PlanExecLoopConfig` with a budget large enough for the toy run."""
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="planner-prompt", execute="execute-prompt"),
        agents_md="# AGENTS\n",
        max_iters=5,
        timeout=30.0,
    )


@pytest.mark.parametrize("cassette_dir", _CASSETTE_DIRS, ids=_RUNTIME_NAMES)
def test_toy_homepage_replay_completes(tmp_path: Path, cassette_dir: Path) -> None:
    """Full replay run reaches COMPLETED with both tasks marked done."""
    cfg = _config(tmp_path)
    runtime = get_runtime("replay", scenario_dir=cassette_dir)

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.COMPLETED
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == len(_EXPECTED_EXEC_IDS)
    assert result.trajectory_paths == (
        "iters/plan/trajectory.json",
        "iters/exec-0001/trajectory.json",
        "iters/exec-0002/trajectory.json",
    )
    final_ids = tuple(t.id for t in result.tasks_final)
    assert final_ids == ("homepage", "product_detail")
    assert all(t.status.value == "done" for t in result.tasks_final)


@pytest.mark.parametrize("cassette_dir", _CASSETTE_DIRS, ids=_RUNTIME_NAMES)
def test_toy_homepage_replay_materialises_spec_5_3_layout(
    tmp_path: Path, cassette_dir: Path
) -> None:
    """The post-run workspace matches the §5.3 layout, including overlay artifacts."""
    cfg = _config(tmp_path)
    runtime = get_runtime("replay", scenario_dir=cassette_dir)

    run_plan_exec_loop(cfg, runtime)

    rd = cfg.run_dir
    # Stable surfaces
    assert (rd / "AGENTS.md").read_text(encoding="utf-8") == cfg.agents_md
    assert (rd / "prompts" / "planner.md").read_text(encoding="utf-8") == cfg.prompts.planner
    assert (rd / "prompts" / "execute.md").read_text(encoding="utf-8") == cfg.prompts.execute

    # Evolving surfaces
    assert (rd / "plan.md").is_file()
    assert (rd / "artifact" / "homepage.md").is_file()
    assert (rd / "artifact" / "product_detail.md").is_file()

    # Append-only telemetry per iteration
    for iter_id in ("plan", *_EXPECTED_EXEC_IDS):
        d = rd / "iters" / iter_id
        assert (d / "trajectory.json").is_file(), f"missing trajectory.json in {iter_id}"
        assert (d / "metadata.json").is_file(), f"missing metadata.json in {iter_id}"
        assert (d / "plan.before.md").is_file(), f"missing plan.before.md in {iter_id}"
        assert (d / "plan.after.md").is_file(), f"missing plan.after.md in {iter_id}"
    for exec_id in _EXPECTED_EXEC_IDS:
        assert (rd / "iters" / exec_id / "checks" / "protocol.json").is_file()

    # Run summary
    assert (rd / "run.json").is_file()


@pytest.mark.parametrize("cassette_dir", _CASSETTE_DIRS, ids=_RUNTIME_NAMES)
def test_toy_homepage_replay_reconstruct_matches_returned_result(
    tmp_path: Path, cassette_dir: Path
) -> None:
    """SC3: `telemetry.reconstruct(run_dir)` rebuilds the same `PlanExecLoopResult`."""
    cfg = _config(tmp_path)
    runtime = get_runtime("replay", scenario_dir=cassette_dir)

    result = run_plan_exec_loop(cfg, runtime)
    reconstructed = reconstruct(cfg.run_dir)

    assert reconstructed == result
