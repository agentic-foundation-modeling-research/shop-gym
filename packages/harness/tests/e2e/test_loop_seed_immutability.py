"""End-to-end seed-immutability tests for `run_plan_exec_loop`.

Spec: `docs/specs/harness/seed_immutability.md`. Drives the loop through
the `ReplayRuntime` against handcrafted cassettes that either leave the
seeded subtree alone or mutate it, and asserts the harness terminates
with `FinalStatus.PROTOCOL_VIOLATION` exactly when a seed deviation is
introduced.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Final

from harness.config import FinalStatus, PlanExecLoopConfig, Prompts
from harness.loop import run_plan_exec_loop
from harness.runtimes.replay import ReplayRuntime
from harness.trajectory import Trajectory

_TS: Final[dt.datetime] = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
_PROMPT_SHA_PLACEHOLDER: Final[str] = "0" * 64


def _trajectory(iter_id: str) -> Trajectory:
    """Build a minimal cassette trajectory for one iteration."""
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
    overlay_files: dict[str, bytes] | None = None,
) -> None:
    """Materialise a cassette that writes `plan.md` and optional artifact files.

    `overlay_files` keys are POSIX paths relative to `workspace_after/`,
    e.g. ``"artifact/prefetch/intruder.md"``.
    """
    cassette_dir = scenario_dir / iter_id
    cassette_dir.mkdir(parents=True)
    (cassette_dir / "trajectory.json").write_text(
        json.dumps(_trajectory(iter_id).model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    overlay = cassette_dir / "workspace_after"
    overlay.mkdir()
    (overlay / "plan.md").write_text(plan_md, encoding="utf-8")
    if overlay_files:
        for rel, content in overlay_files.items():
            target = overlay / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


def _seed_dir(tmp_path: Path) -> Path:
    """Return a seed dir with a single ``prefetch/`` top-level entry."""
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    (seed / "prefetch" / "homepage.html").write_text(
        "<html><body>seed</body></html>\n", encoding="utf-8"
    )
    return seed


def _config(tmp_path: Path, *, seed: Path | None) -> PlanExecLoopConfig:
    """Build a `PlanExecLoopConfig` with optional `artifact_seed_dir`."""
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="planner-prompt", execute="execute-prompt"),
        agents_md="# AGENTS\n",
        artifact_seed_dir=seed,
        max_iters=3,
        timeout=30.0,
    )


# ---------------------------------------------------------------------------
# Planner-phase seed check
# ---------------------------------------------------------------------------


def test_planner_seed_extension_aborts_run_with_protocol_violation(tmp_path: Path) -> None:
    """Planner writes inside the seeded subtree → terminal `protocol_violation`."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md="# Plan\n\n## Tasks\n- [ ] homepage\n",
        # Reproduces the spec §3 failure: a drifted-CWD planner saves
        # work inside the seed.
        overlay_files={
            "artifact/prefetch/_planner/snapshot.md": b"intruder",
        },
    )

    runtime = ReplayRuntime(scenario_dir)
    cfg = _config(tmp_path, seed=_seed_dir(tmp_path))

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.PROTOCOL_VIOLATION
    assert result.plan_iter_count == 1
    assert result.exec_iter_count == 0

    protocol_path = result.run_dir / "iters" / "plan" / "checks" / "protocol.json"
    assert protocol_path.is_file(), "planner phase must write its first protocol.json"
    payload = json.loads(protocol_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any(v.startswith("seed_extended:") for v in payload["violations"])
    assert any("prefetch/_planner/snapshot.md" in v for v in payload["violations"])


def test_planner_seed_mutation_aborts_run_with_protocol_violation(tmp_path: Path) -> None:
    """Planner overwrites a seeded file → terminal `protocol_violation`."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md="# Plan\n\n## Tasks\n- [ ] homepage\n",
        overlay_files={
            "artifact/prefetch/robots.txt": b"User-agent: evil\n",
        },
    )

    runtime = ReplayRuntime(scenario_dir)
    cfg = _config(tmp_path, seed=_seed_dir(tmp_path))

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.PROTOCOL_VIOLATION
    payload = json.loads(
        (result.run_dir / "iters" / "plan" / "checks" / "protocol.json").read_text(encoding="utf-8")
    )
    assert any(v == "seed_mutated: prefetch/robots.txt" for v in payload["violations"])


# ---------------------------------------------------------------------------
# Executor-phase seed check
# ---------------------------------------------------------------------------


def test_executor_seed_violation_merges_into_protocol_json(tmp_path: Path) -> None:
    """Executor mutates seed → seed violation merged into one protocol.json."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md="# Plan\n\n## Tasks\n- [ ] homepage\n",
    )
    _write_cassette(
        scenario_dir,
        "exec-0001",
        # Plan-protocol passes (selected task is the only one flipped to [x]).
        plan_md="# Plan\n\n## Tasks\n- [x] homepage\n",
        # But the executor also touches the seed.
        overlay_files={
            "artifact/prefetch/robots.txt": b"User-agent: evil\n",
        },
    )

    runtime = ReplayRuntime(scenario_dir)
    cfg = _config(tmp_path, seed=_seed_dir(tmp_path))

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.PROTOCOL_VIOLATION
    assert result.exec_iter_count == 1

    protocol_path = result.run_dir / "iters" / "exec-0001" / "checks" / "protocol.json"
    assert protocol_path.is_file()
    payload = json.loads(protocol_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any(v.startswith("seed_mutated:") for v in payload["violations"])


# ---------------------------------------------------------------------------
# No-op when no seed dir
# ---------------------------------------------------------------------------


def test_no_seed_dir_means_no_planner_protocol_json(tmp_path: Path) -> None:
    """Without an artifact_seed_dir, the planner phase writes no protocol.json."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md="# Plan\n\n## Tasks\n",
    )

    runtime = ReplayRuntime(scenario_dir)
    cfg = _config(tmp_path, seed=None)

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.COMPLETED
    assert not (result.run_dir / "iters" / "plan" / "checks" / "protocol.json").exists()


def test_unmutated_seed_lets_run_complete(tmp_path: Path) -> None:
    """Seed left intact → run reaches COMPLETED, planner protocol.json passes."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md="# Plan\n\n## Tasks\n- [ ] homepage\n",
    )
    _write_cassette(
        scenario_dir,
        "exec-0001",
        plan_md="# Plan\n\n## Tasks\n- [x] homepage\n",
    )

    runtime = ReplayRuntime(scenario_dir)
    cfg = _config(tmp_path, seed=_seed_dir(tmp_path))

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.COMPLETED
    plan_protocol = result.run_dir / "iters" / "plan" / "checks" / "protocol.json"
    exec_protocol = result.run_dir / "iters" / "exec-0001" / "checks" / "protocol.json"
    for path in (plan_protocol, exec_protocol):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["passed"] is True
        assert payload["violations"] == []


def test_writes_outside_seeded_subtree_are_ignored(tmp_path: Path) -> None:
    """Per spec §5.5b: only paths under `seeded_roots` are inspected."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md="# Plan\n\n## Tasks\n- [ ] homepage\n",
        overlay_files={
            # `evidence/` is not a seeded root in our seed; agents have
            # full access here per parent spec §5.4.
            "artifact/evidence/screenshot.png": b"\x89PNG",
        },
    )
    _write_cassette(
        scenario_dir,
        "exec-0001",
        plan_md="# Plan\n\n## Tasks\n- [x] homepage\n",
    )

    runtime = ReplayRuntime(scenario_dir)
    cfg = _config(tmp_path, seed=_seed_dir(tmp_path))

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.COMPLETED
