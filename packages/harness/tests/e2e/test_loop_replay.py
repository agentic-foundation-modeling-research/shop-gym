"""End-to-end replay test for `run_plan_exec_loop`.

Drives a full two-task toy run against a synthetic in-test cassette
materialised via `ReplayRuntime` and asserts the harness produces the
§5.3 workspace layout, terminates with `FinalStatus.COMPLETED`, and
that `telemetry.reconstruct` rebuilds the same `PlanExecLoopResult`
from disk.

The cassette is assembled per test under `tmp_path` with hand-written
static content (no recordings, no host paths) so the suite stays
hermetic.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from harness.config import FinalStatus, PlanExecLoopConfig, Prompts
from harness.loop import run_plan_exec_loop
from harness.runtimes.replay import ReplayRuntime
from harness.telemetry import reconstruct
from harness.trajectory import Trajectory

_TS: Final[dt.datetime] = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
_PROMPT_SHA_PLACEHOLDER: Final[str] = "0" * 64
_EXPECTED_EXEC_IDS: Final[tuple[str, ...]] = ("exec-0001", "exec-0002")

_PLAN_PENDING: Final[str] = (
    "# Plan\n\n"
    "## Tasks\n"
    "- [ ] homepage         [priority: 2]\n"
    "- [ ] product_detail   [priority: 1]\n"
)
_PLAN_HOMEPAGE_DONE: Final[str] = (
    "# Plan\n\n"
    "## Tasks\n"
    "- [x] homepage         [priority: 2]\n"
    "- [ ] product_detail   [priority: 1]\n"
)
_PLAN_BOTH_DONE: Final[str] = (
    "# Plan\n\n"
    "## Tasks\n"
    "- [x] homepage         [priority: 2]\n"
    "- [x] product_detail   [priority: 1]\n"
)
_HOMEPAGE_ARTIFACT: Final[str] = "# homepage\nsynthetic\n"
_PRODUCT_DETAIL_ARTIFACT: Final[str] = "# product_detail\nsynthetic\n"


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
    overlay: Mapping[str, str],
) -> None:
    """Materialise a cassette: trajectory + `workspace_after/` overlay files."""
    cassette_dir = scenario_dir / iter_id
    cassette_dir.mkdir(parents=True)
    (cassette_dir / "trajectory.json").write_text(
        json.dumps(_trajectory(iter_id).model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_root = cassette_dir / "workspace_after"
    for rel, content in overlay.items():
        target = overlay_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _build_scenario(scenario_dir: Path) -> None:
    """Lay out the three-iteration toy scenario under `scenario_dir`."""
    _write_cassette(scenario_dir, "plan", overlay={"plan.md": _PLAN_PENDING})
    _write_cassette(
        scenario_dir,
        "exec-0001",
        overlay={
            "plan.md": _PLAN_HOMEPAGE_DONE,
            "artifact/homepage.md": _HOMEPAGE_ARTIFACT,
        },
    )
    _write_cassette(
        scenario_dir,
        "exec-0002",
        overlay={
            "plan.md": _PLAN_BOTH_DONE,
            "artifact/product_detail.md": _PRODUCT_DETAIL_ARTIFACT,
        },
    )


def _config(tmp_path: Path) -> PlanExecLoopConfig:
    """Build a `PlanExecLoopConfig` with a budget large enough for the toy run."""
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="planner-prompt", execute="execute-prompt"),
        agents_md="# AGENTS\n",
        max_iters=5,
        timeout=30.0,
    )


def test_toy_homepage_replay_completes(tmp_path: Path) -> None:
    """Full replay run reaches COMPLETED with both tasks marked done."""
    scenario_dir = tmp_path / "cassettes"
    _build_scenario(scenario_dir)
    cfg = _config(tmp_path)
    runtime = ReplayRuntime(scenario_dir)

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


def test_toy_homepage_replay_materialises_spec_5_3_layout(tmp_path: Path) -> None:
    """The post-run workspace matches the §5.3 layout, including overlay artifacts."""
    scenario_dir = tmp_path / "cassettes"
    _build_scenario(scenario_dir)
    cfg = _config(tmp_path)
    runtime = ReplayRuntime(scenario_dir)

    run_plan_exec_loop(cfg, runtime)

    rd = cfg.run_dir
    assert (rd / "AGENTS.md").read_text(encoding="utf-8") == cfg.agents_md
    assert (rd / "prompts" / "planner.md").read_text(encoding="utf-8") == cfg.prompts.planner
    assert (rd / "prompts" / "execute.md").read_text(encoding="utf-8") == cfg.prompts.execute

    assert (rd / "plan.md").is_file()
    assert (rd / "artifact" / "homepage.md").is_file()
    assert (rd / "artifact" / "product_detail.md").is_file()

    for iter_id in ("plan", *_EXPECTED_EXEC_IDS):
        d = rd / "iters" / iter_id
        assert (d / "trajectory.json").is_file(), f"missing trajectory.json in {iter_id}"
        assert (d / "metadata.json").is_file(), f"missing metadata.json in {iter_id}"
        assert (d / "plan.before.md").is_file(), f"missing plan.before.md in {iter_id}"
        assert (d / "plan.after.md").is_file(), f"missing plan.after.md in {iter_id}"
    for exec_id in _EXPECTED_EXEC_IDS:
        assert (rd / "iters" / exec_id / "checks" / "protocol.json").is_file()

    assert (rd / "run.json").is_file()


def test_toy_homepage_replay_reconstruct_matches_returned_result(tmp_path: Path) -> None:
    """`telemetry.reconstruct(run_dir)` rebuilds the same `PlanExecLoopResult`."""
    scenario_dir = tmp_path / "cassettes"
    _build_scenario(scenario_dir)
    cfg = _config(tmp_path)
    runtime = ReplayRuntime(scenario_dir)

    result = run_plan_exec_loop(cfg, runtime)
    reconstructed = reconstruct(cfg.run_dir)

    assert reconstructed == result
