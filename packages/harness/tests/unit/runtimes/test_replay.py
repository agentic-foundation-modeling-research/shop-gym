"""Unit tests for `harness.runtimes.replay.ReplayRuntime` (T2.3).

Covers:

* Replay mode: overlay copy preserves untouched files, overwrites
  conflicting files, materialises new files; `trajectory.json` and
  `native.log` are surfaced into `iter_dir`; the returned trajectory
  matches the cassette.
* Replay mode error paths: missing cassette dir, missing
  `trajectory.json`.
* Record mode: delegates to a stub fallback, writes a fresh cassette
  containing `trajectory.json`, `native.log`, and a `workspace_after/`
  overlay reflecting the live workspace.
* Record mode error path: `HARNESS_RECORD=1` without a fallback.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from harness.runtimes.base import RuntimeIterationResult
from harness.runtimes.replay import ReplayError, ReplayRuntime
from harness.trajectory import Trajectory

_TS = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


def _trajectory(iter_id: str, runtime: str = "replay") -> Trajectory:
    """Build a minimal `Trajectory` for cassette fixtures."""
    return Trajectory(
        iter_id=iter_id,
        runtime=runtime,
        started_at=_TS,
        ended_at=_TS,
        exit_code=0,
        prompt_sha256="0" * 64,
    )


def _write_cassette(
    scenario_dir: Path,
    iter_id: str,
    *,
    trajectory: Trajectory,
    native_log: str | None = None,
    workspace_after: dict[str, str] | None = None,
) -> Path:
    """Materialise a minimal cassette under `scenario_dir/iter_id/`."""
    cassette_dir = scenario_dir / iter_id
    cassette_dir.mkdir(parents=True)
    (cassette_dir / "trajectory.json").write_text(
        json.dumps(trajectory.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    if native_log is not None:
        (cassette_dir / "native.log").write_text(native_log, encoding="utf-8")
    if workspace_after is not None:
        overlay = cassette_dir / "workspace_after"
        overlay.mkdir()
        for rel, contents in workspace_after.items():
            target = overlay / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
    return cassette_dir


def _make_run_dir(tmp_path: Path) -> tuple[Path, Path]:
    """Create a `run_dir` plus a per-iteration `iter_dir` under `tmp_path`."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    iter_dir = run_dir / "iters" / "plan"
    iter_dir.mkdir(parents=True)
    return run_dir, iter_dir


# ---------------------------------------------------------------------------
# Replay mode
# ---------------------------------------------------------------------------


def test_replay_overlay_overwrites_and_preserves_files(tmp_path: Path) -> None:
    """Files in the overlay overwrite live files; unrelated files remain."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        trajectory=_trajectory("plan"),
        workspace_after={
            "plan.md": "## Tasks\n- [ ] homepage\n",
            "artifact/notes.md": "fresh\n",
        },
    )

    run_dir, iter_dir = _make_run_dir(tmp_path)
    (run_dir / "plan.md").write_text("seed\n", encoding="utf-8")
    (run_dir / "artifact").mkdir()
    (run_dir / "artifact" / "preexisting.txt").write_text("keep me\n", encoding="utf-8")
    (run_dir / "AGENTS.md").write_text("rules\n", encoding="utf-8")

    runtime = ReplayRuntime(scenario_dir)
    result = runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)

    assert isinstance(result, RuntimeIterationResult)
    assert result.trajectory.iter_id == "plan"
    # Overlay overwrote plan.md and added a new artifact file.
    assert (run_dir / "plan.md").read_text(encoding="utf-8") == "## Tasks\n- [ ] homepage\n"
    assert (run_dir / "artifact" / "notes.md").read_text(encoding="utf-8") == "fresh\n"
    # Files outside the overlay are preserved.
    assert (run_dir / "artifact" / "preexisting.txt").read_text(encoding="utf-8") == "keep me\n"
    assert (run_dir / "AGENTS.md").read_text(encoding="utf-8") == "rules\n"


def test_replay_copies_trajectory_and_native_log_into_iter_dir(tmp_path: Path) -> None:
    """`native.log` is mirrored into `iter_dir`; the trajectory is returned in-memory."""
    scenario_dir = tmp_path / "cassettes"
    trajectory = _trajectory("plan")
    _write_cassette(
        scenario_dir,
        "plan",
        trajectory=trajectory,
        native_log="raw cli stream\n",
        workspace_after={"plan.md": "## Tasks\n- [ ] x\n"},
    )

    run_dir, iter_dir = _make_run_dir(tmp_path)

    runtime = ReplayRuntime(scenario_dir)
    result = runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)

    assert (iter_dir / "native.log").read_text(encoding="utf-8") == "raw cli stream\n"
    assert result.trajectory == trajectory


def test_replay_works_without_native_log(tmp_path: Path) -> None:
    """A cassette that omits `native.log` replays cleanly without one."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        trajectory=_trajectory("plan"),
        workspace_after={"plan.md": "## Tasks\n"},
    )

    run_dir, iter_dir = _make_run_dir(tmp_path)
    runtime = ReplayRuntime(scenario_dir)
    runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)

    assert not (iter_dir / "native.log").exists()


def test_replay_uses_iter_dir_name_as_iter_id(tmp_path: Path) -> None:
    """The iteration id is taken from `iter_dir.name`, not the prompt."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "exec-0001",
        trajectory=_trajectory("exec-0001"),
        workspace_after={"plan.md": "## Tasks\n- [x] homepage\n"},
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    iter_dir = run_dir / "iters" / "exec-0001"
    iter_dir.mkdir(parents=True)

    runtime = ReplayRuntime(scenario_dir)
    result = runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)

    assert result.trajectory.iter_id == "exec-0001"


def test_replay_missing_cassette_raises_replay_error(tmp_path: Path) -> None:
    """A missing cassette directory surfaces as `ReplayError`."""
    run_dir, iter_dir = _make_run_dir(tmp_path)

    runtime = ReplayRuntime(tmp_path / "cassettes")
    with pytest.raises(ReplayError, match="cassette directory not found"):
        runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)


def test_replay_missing_trajectory_raises_replay_error(tmp_path: Path) -> None:
    """A cassette directory without `trajectory.json` is malformed."""
    scenario_dir = tmp_path / "cassettes"
    (scenario_dir / "plan").mkdir(parents=True)

    run_dir, iter_dir = _make_run_dir(tmp_path)
    runtime = ReplayRuntime(scenario_dir)
    with pytest.raises(ReplayError, match=r"missing trajectory\.json"):
        runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)


def test_replay_invalid_trajectory_json_raises_replay_error(tmp_path: Path) -> None:
    """A non-JSON `trajectory.json` is rejected with `ReplayError`."""
    scenario_dir = tmp_path / "cassettes"
    cassette_dir = scenario_dir / "plan"
    cassette_dir.mkdir(parents=True)
    (cassette_dir / "trajectory.json").write_text("not json", encoding="utf-8")

    run_dir, iter_dir = _make_run_dir(tmp_path)
    runtime = ReplayRuntime(scenario_dir)
    with pytest.raises(ReplayError, match="not valid JSON"):
        runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)


# ---------------------------------------------------------------------------
# Record mode
# ---------------------------------------------------------------------------


class _StubFallback:
    """Minimal `AgentRuntime` that mutates the workspace and emits telemetry."""

    def __init__(self, trajectory: Trajectory, native_log: str, plan_after: str) -> None:
        self._trajectory = trajectory
        self._native_log = native_log
        self._plan_after = plan_after
        self.calls: list[dict[str, object]] = []

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Simulate a real runtime: write log + plan, return the trajectory."""
        self.calls.append(
            {"run_dir": run_dir, "iter_dir": iter_dir, "prompt": prompt, "timeout": timeout}
        )
        (iter_dir / "native.log").write_text(self._native_log, encoding="utf-8")
        (run_dir / "plan.md").write_text(self._plan_after, encoding="utf-8")
        artifact_dir = run_dir / "artifact"
        artifact_dir.mkdir(exist_ok=True)
        (artifact_dir / "summary.md").write_text("recorded artifact\n", encoding="utf-8")
        return RuntimeIterationResult(trajectory=self._trajectory)


def test_record_mode_writes_fresh_cassette(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`HARNESS_RECORD=1` writes a cassette mirroring the live workspace and telemetry."""
    monkeypatch.setenv("HARNESS_RECORD", "1")

    scenario_dir = tmp_path / "cassettes"
    trajectory = _trajectory("plan", runtime="claude_code")
    fallback = _StubFallback(
        trajectory=trajectory,
        native_log="streamed cli output\n",
        plan_after="## Tasks\n- [ ] homepage\n",
    )

    run_dir, iter_dir = _make_run_dir(tmp_path)

    runtime = ReplayRuntime(scenario_dir, fallback=fallback)
    expected_timeout = 2.5
    result = runtime.run_iteration(
        run_dir=run_dir, iter_dir=iter_dir, prompt="hello", timeout=expected_timeout
    )

    # Fallback was called with the harness-provided arguments.
    assert len(fallback.calls) == 1
    assert fallback.calls[0]["prompt"] == "hello"
    assert fallback.calls[0]["timeout"] == expected_timeout

    # Trajectory propagated unchanged.
    assert result.trajectory == trajectory

    cassette_dir = scenario_dir / "plan"
    assert cassette_dir.is_dir()

    recorded = json.loads((cassette_dir / "trajectory.json").read_text(encoding="utf-8"))
    assert Trajectory.model_validate(recorded) == trajectory

    assert (cassette_dir / "native.log").read_text(encoding="utf-8") == "streamed cli output\n"

    overlay = cassette_dir / "workspace_after"
    assert (overlay / "plan.md").read_text(encoding="utf-8") == "## Tasks\n- [ ] homepage\n"
    artifact_summary = overlay / "artifact" / "summary.md"
    assert artifact_summary.read_text(encoding="utf-8") == "recorded artifact\n"


def test_record_mode_replaces_stale_cassette(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-recording wipes any pre-existing cassette files for the iteration."""
    monkeypatch.setenv("HARNESS_RECORD", "1")

    scenario_dir = tmp_path / "cassettes"
    cassette_dir = scenario_dir / "plan"
    cassette_dir.mkdir(parents=True)
    (cassette_dir / "stale.txt").write_text("leftover\n", encoding="utf-8")

    fallback = _StubFallback(
        trajectory=_trajectory("plan"),
        native_log="x\n",
        plan_after="## Tasks\n",
    )

    run_dir, iter_dir = _make_run_dir(tmp_path)
    runtime = ReplayRuntime(scenario_dir, fallback=fallback)
    runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)

    assert not (cassette_dir / "stale.txt").exists()


def test_record_mode_without_fallback_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`HARNESS_RECORD=1` without a fallback runtime is a configuration error."""
    monkeypatch.setenv("HARNESS_RECORD", "1")

    scenario_dir = tmp_path / "cassettes"
    run_dir, iter_dir = _make_run_dir(tmp_path)

    runtime = ReplayRuntime(scenario_dir)
    with pytest.raises(ReplayError, match="HARNESS_RECORD=1"):
        runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)


def test_record_mode_skipped_when_env_not_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unset (or non-``1``) `HARNESS_RECORD` falls through to replay mode."""
    monkeypatch.delenv("HARNESS_RECORD", raising=False)

    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        trajectory=_trajectory("plan"),
        workspace_after={"plan.md": "## Tasks\n"},
    )

    fallback = _StubFallback(
        trajectory=_trajectory("plan"),
        native_log="x",
        plan_after="## Tasks\n",
    )

    run_dir, iter_dir = _make_run_dir(tmp_path)
    runtime = ReplayRuntime(scenario_dir, fallback=fallback)
    runtime.run_iteration(run_dir=run_dir, iter_dir=iter_dir, prompt="x", timeout=1.0)

    # Fallback must not be invoked in pure-replay mode.
    assert fallback.calls == []
