"""End-to-end resume tests for `run_plan_exec_loop` (resume.md M3+M4).

Resume mode is inferred from `config.run_dir` on disk: a non-empty
directory triggers `Workspace.open` plus the §5.3 loop-state
reconstruction. These tests drive a first attempt that lands in a
specific terminal state, then invoke `run_plan_exec_loop` a second time
against the same `run_dir` to assert the resumed behaviour:

* SC-R1: resume after `timeout` continues at the next `exec-NNNN`
  without re-running the planner.
* SC-R3: resume after `completed` is a no-op.
* SC-R4: resume after `protocol_violation` / `runtime_error` refuses
  by default; ``force=True`` overrides.
* §5.4: a partial `iters/<id>/` is renamed to `iters/<id>.aborted-<N>/`
  and the sentinel records the prior `final_status`.
* §5.7: each call to `run_plan_exec_loop` appends one entry to
  `config_snapshot.resume_history`; prior entries are immutable.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Final, cast

import pytest

from harness.config import FinalStatus, PlanExecLoopConfig, Prompts
from harness.loop import ResumeRefusedError, run_plan_exec_loop
from harness.runtimes.base import RuntimeIterationResult
from harness.runtimes.replay import ReplayRuntime
from harness.trajectory import Trajectory

_TS: Final[dt.datetime] = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
_PROMPT_SHA_PLACEHOLDER: Final[str] = "0" * 64

_PLAN_TWO_PENDING = (
    "# Plan\n\n"
    "## Tasks\n"
    "- [ ] homepage         [priority: 2]\n"
    "- [ ] product_detail   [priority: 1]\n"
)
_PLAN_ONE_DONE = (
    "# Plan\n\n"
    "## Tasks\n"
    "- [x] homepage         [priority: 2]\n"
    "- [ ] product_detail   [priority: 1]\n"
)
_PLAN_BOTH_DONE = (
    "# Plan\n\n"
    "## Tasks\n"
    "- [x] homepage         [priority: 2]\n"
    "- [x] product_detail   [priority: 1]\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    plan_md: str,
    overlay_files: dict[str, bytes] | None = None,
) -> None:
    """Materialise a minimal cassette: trajectory + `workspace_after/plan.md`.

    ``overlay_files`` keys are POSIX paths relative to ``workspace_after/``,
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


def _config(
    tmp_path: Path,
    *,
    max_iters: int = 5,
    seed: Path | None = None,
) -> PlanExecLoopConfig:
    """Build a `PlanExecLoopConfig` rooted at `tmp_path/run`."""
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner="planner-prompt", execute="execute-prompt"),
        agents_md="# AGENTS\n",
        artifact_seed_dir=seed,
        max_iters=max_iters,
        timeout=30.0,
    )


def _seed_dir(tmp_path: Path) -> Path:
    """Return a seed dir with a single ``prefetch/`` top-level entry."""
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    return seed


class _CountingRuntime:
    """Wraps a runtime and records each `run_iteration` call.

    Used to confirm whether the planner runs on resume — a resumed loop
    that re-invokes the runtime for `iters/plan/` would inflate
    `iter_ids` with a `"plan"` entry.
    """

    def __init__(self, inner: ReplayRuntime) -> None:
        self._inner = inner
        self.iter_ids: list[str] = []

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        self.iter_ids.append(iter_dir.name)
        return self._inner.run_iteration(
            run_dir=run_dir,
            iter_dir=iter_dir,
            prompt=prompt,
            timeout=timeout,
        )


class _ScriptedRuntime:
    """Runtime that runs the planner once, then raises a configured exception.

    Used to drive the harness into a specific terminal status (TIMEOUT
    or RUNTIME_ERROR) after the planner has already written its
    trajectory.
    """

    def __init__(
        self,
        *,
        plan_md: str,
        post_plan_error: BaseException,
    ) -> None:
        self._plan_md = plan_md
        self._post_plan_error = post_plan_error
        self._calls = 0
        self.iter_ids: list[str] = []

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del prompt
        self._calls += 1
        self.iter_ids.append(iter_dir.name)
        if self._calls == 1:
            (run_dir / "plan.md").write_text(self._plan_md, encoding="utf-8")
            return RuntimeIterationResult(
                trajectory=Trajectory(
                    iter_id=iter_dir.name,
                    runtime="scripted",
                    started_at=_TS,
                    ended_at=_TS,
                    exit_code=0,
                    prompt_sha256=_PROMPT_SHA_PLACEHOLDER,
                )
            )
        del timeout
        raise self._post_plan_error


# ---------------------------------------------------------------------------
# SC-R1: resume after timeout continues at next exec id
# ---------------------------------------------------------------------------


def test_resume_after_timeout_continues_at_next_exec_without_replanning(
    tmp_path: Path,
) -> None:
    """First attempt times out at exec-0001; resume runs exec-0001 cleanly."""
    # First attempt: planner writes the plan, then exec-0001 raises TimeoutExpired.
    first = _ScriptedRuntime(
        plan_md=_PLAN_TWO_PENDING,
        post_plan_error=subprocess.TimeoutExpired(cmd="agent", timeout=1.0),
    )
    cfg = _config(tmp_path)
    first_result = run_plan_exec_loop(cfg, first)

    assert first_result.final_status is FinalStatus.TIMEOUT
    assert first_result.plan_iter_count == 1
    assert first_result.exec_iter_count == 0
    # Planner was the only successful iteration; exec-0001 may exist on disk
    # as a partial dir (created before the runtime invocation that timed out).
    assert first.iter_ids[0] == "plan"

    # Second attempt: replay runtime drives both executor iterations to completion.
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_ONE_DONE)
    _write_cassette(scenario_dir, "exec-0002", plan_md=_PLAN_BOTH_DONE)
    runtime = _CountingRuntime(ReplayRuntime(scenario_dir))

    second_result = run_plan_exec_loop(cfg, runtime)

    # Planner is *not* re-invoked.
    assert "plan" not in runtime.iter_ids
    assert runtime.iter_ids == ["exec-0001", "exec-0002"]
    # Final result reflects the unioned iteration history.
    assert second_result.final_status is FinalStatus.COMPLETED
    assert second_result.plan_iter_count == 1
    assert second_result.exec_iter_count == first_result.exec_iter_count + len(runtime.iter_ids)
    assert second_result.trajectory_paths == (
        "iters/plan/trajectory.json",
        "iters/exec-0001/trajectory.json",
        "iters/exec-0002/trajectory.json",
    )


def test_resume_quarantines_partial_exec_dir_with_sentinel(tmp_path: Path) -> None:
    """A partial `iters/exec-0001/` left over from a prior crash is quarantined on resume.

    A normal in-run TIMEOUT now quarantines the iter dir mid-attempt
    (see `test_in_run_timeout_quarantines_iter_dir_with_sentinel`), so
    this test simulates the case where the harness process itself was
    killed externally (no `subprocess.TimeoutExpired` propagated, no
    chance to clean up). `_bootstrap_workspace` produces that exact
    on-disk state — a partial `exec-0001/` with no `trajectory.json`
    and a `run.json` recording the prior `timeout` final status.
    """
    run_dir = tmp_path / "run"
    _bootstrap_workspace(
        run_dir,
        plan_md=_PLAN_TWO_PENDING,
        partial_exec_ids=("exec-0001",),
        prior_final_status=FinalStatus.TIMEOUT,
    )
    iters_dir = run_dir / "iters"

    cfg = _config(tmp_path)
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_ONE_DONE)
    _write_cassette(scenario_dir, "exec-0002", plan_md=_PLAN_BOTH_DONE)
    runtime = ReplayRuntime(scenario_dir)
    run_plan_exec_loop(cfg, runtime)

    aborted_dir = iters_dir / "exec-0001.aborted-1"
    assert aborted_dir.is_dir(), "partial exec dir should have been quarantined"
    assert not (iters_dir / "exec-0001").exists() or (
        iters_dir / "exec-0001" / "trajectory.json"
    ).is_file(), "exec-0001 either renamed or rebuilt with trajectory"

    sentinel = aborted_dir / "aborted.txt"
    assert sentinel.is_file()
    body = sentinel.read_text(encoding="utf-8")
    assert "resume_at:" in body
    assert "prior_final_status: timeout" in body


def test_in_run_timeout_quarantines_iter_dir_with_sentinel(tmp_path: Path) -> None:
    """An in-run executor TIMEOUT renames the partial iter dir mid-attempt."""
    first = _ScriptedRuntime(
        plan_md=_PLAN_TWO_PENDING,
        post_plan_error=subprocess.TimeoutExpired(cmd="agent", timeout=1.0),
    )
    cfg = _config(tmp_path)
    result = run_plan_exec_loop(cfg, first)

    assert result.final_status is FinalStatus.TIMEOUT

    iters_dir = cfg.run_dir / "iters"
    # The canonical exec-0001 slot was reused for the second pending task
    # after the first TIMEOUT was quarantined, so we expect TWO aborted
    # dirs (one per pending task that timed out).
    aborted_first = iters_dir / "exec-0001.aborted-1"
    aborted_second = iters_dir / "exec-0001.aborted-2"
    assert aborted_first.is_dir()
    assert aborted_second.is_dir()
    # The canonical exec-0001/ slot is empty after quarantine (or was
    # never re-created because no further pending task remained).
    assert not (iters_dir / "exec-0001").exists()

    sentinel = aborted_first / "aborted.txt"
    assert sentinel.is_file()
    body = sentinel.read_text(encoding="utf-8")
    assert "aborted_at:" in body
    assert "reason: timeout" in body


def test_in_run_timeout_advances_to_next_pending_task(tmp_path: Path) -> None:
    """A TIMEOUT on one task does not block subsequent pending tasks from running."""

    plan_product_done = (
        "# Plan\n\n"
        "## Tasks\n"
        "- [ ] homepage         [priority: 2]\n"
        "- [x] product_detail   [priority: 1]\n"
    )

    planner_call = 1
    timeout_call = 2

    class _TimeoutThenSucceedRuntime:
        """Plan, then TIMEOUT on the first executor call, then succeed thereafter."""

        def __init__(self) -> None:
            self.iter_ids: list[str] = []
            self.selected_task_ids: list[str] = []
            self._calls = 0

        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del timeout
            self._calls += 1
            self.iter_ids.append(iter_dir.name)
            # The selected task id is encoded in the harness-control header.
            for line in prompt.splitlines():
                if line.startswith("selected_task_id:"):
                    self.selected_task_ids.append(line.split(":", 1)[1].strip())
                    break
            if self._calls == planner_call:
                (run_dir / "plan.md").write_text(_PLAN_TWO_PENDING, encoding="utf-8")
                return RuntimeIterationResult(trajectory=_trajectory(iter_dir.name))
            if self._calls == timeout_call:
                # TIMEOUT on the first executor call (task=homepage).
                raise subprocess.TimeoutExpired(cmd="agent", timeout=1.0)
            # Subsequent executor call (task=product_detail) succeeds. Mark
            # only the selected task done so the harness protocol checks
            # accept the iteration.
            (run_dir / "plan.md").write_text(plan_product_done, encoding="utf-8")
            return RuntimeIterationResult(trajectory=_trajectory(iter_dir.name))

    runtime = _TimeoutThenSucceedRuntime()
    cfg = _config(tmp_path)
    result = run_plan_exec_loop(cfg, runtime)

    # The run terminated as TIMEOUT (homepage timed out) but product_detail
    # still ran and was marked done — the loop did not stop after the timeout.
    assert result.final_status is FinalStatus.TIMEOUT
    # plan + 2 executor invocations (homepage timeout, product_detail success).
    assert runtime.selected_task_ids == ["homepage", "product_detail"]
    # Only product_detail produced a trajectory (homepage was quarantined).
    assert result.exec_iter_count == 1
    assert "iters/exec-0001/trajectory.json" in result.trajectory_paths
    # The on-disk plan still has homepage PENDING — a future resume retries it.
    final_by_id = {t.id: t.status.value for t in result.tasks_final}
    assert final_by_id == {"homepage": "pending", "product_detail": "done"}


def test_resume_quarantines_with_unique_counter_for_repeat_attempts(
    tmp_path: Path,
) -> None:
    """A second resume attempt produces `*.aborted-2/` rather than colliding."""
    iters_dir = tmp_path / "run" / "iters"
    iters_dir.mkdir(parents=True)
    (iters_dir / "exec-0001.aborted-1").mkdir()
    (iters_dir / "exec-0001.aborted-1" / "aborted.txt").write_text(
        "stale", encoding="utf-8"
    )

    # Construct a workspace with a partial exec-0001 (no trajectory.json).
    _bootstrap_workspace(
        tmp_path / "run",
        plan_md=_PLAN_ONE_DONE,
        partial_exec_ids=("exec-0001",),
        prior_final_status=FinalStatus.TIMEOUT,
    )

    cfg = _config(tmp_path)
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_BOTH_DONE)
    runtime = ReplayRuntime(scenario_dir)
    run_plan_exec_loop(cfg, runtime)

    assert (iters_dir / "exec-0001.aborted-2").is_dir()
    assert (iters_dir / "exec-0001.aborted-2" / "aborted.txt").is_file()


# ---------------------------------------------------------------------------
# SC-R3: resume after completed is a no-op
# ---------------------------------------------------------------------------


def test_resume_after_completed_is_a_no_op(tmp_path: Path) -> None:
    """A completed run cannot drive any new iterations on resume."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "plan", plan_md=_PLAN_TWO_PENDING)
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_ONE_DONE)
    _write_cassette(scenario_dir, "exec-0002", plan_md=_PLAN_BOTH_DONE)

    cfg = _config(tmp_path)
    first_result = run_plan_exec_loop(cfg, ReplayRuntime(scenario_dir))
    assert first_result.final_status is FinalStatus.COMPLETED

    # Re-invoke; nothing should change. Use a runtime that fails loudly if
    # the harness tries to invoke it — there's nothing left to do.
    silent = _CountingRuntime(ReplayRuntime(scenario_dir))
    second_result = run_plan_exec_loop(cfg, silent)

    assert silent.iter_ids == [], "no iterations should run when prior run completed"
    assert second_result.final_status is FinalStatus.COMPLETED
    assert second_result.plan_iter_count == 1
    assert second_result.exec_iter_count == first_result.exec_iter_count


# ---------------------------------------------------------------------------
# SC-R4: resume after protocol_violation / runtime_error refuses by default
# ---------------------------------------------------------------------------


def test_resume_after_protocol_violation_refuses_by_default(tmp_path: Path) -> None:
    """Prior `protocol_violation` blocks resume unless `force=True`.

    Driven by a planner-phase seed extension: per
    ``docs/specs/harness/protocol_violation_recovery.md`` only the planner
    branch still terminates with ``PROTOCOL_VIOLATION`` (executor-phase
    violations now recover in-place).
    """
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md=_PLAN_TWO_PENDING,
        overlay_files={"artifact/prefetch/_planner/snapshot.md": b"intruder"},
    )

    cfg = _config(tmp_path, seed=_seed_dir(tmp_path))
    first_result = run_plan_exec_loop(cfg, ReplayRuntime(scenario_dir))
    assert first_result.final_status is FinalStatus.PROTOCOL_VIOLATION

    silent = _CountingRuntime(ReplayRuntime(scenario_dir))
    with pytest.raises(ResumeRefusedError) as excinfo:
        run_plan_exec_loop(cfg, silent)
    assert excinfo.value.prior_status is FinalStatus.PROTOCOL_VIOLATION
    assert excinfo.value.run_dir == cfg.run_dir
    assert silent.iter_ids == [], "refusal must occur before any runtime call"


def test_resume_force_overrides_protocol_violation_refusal(tmp_path: Path) -> None:
    """`force=True` lets resume past the protocol-violation refusal gate.

    Same planner-phase trigger as the refusal test above.
    """
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(
        scenario_dir,
        "plan",
        plan_md=_PLAN_TWO_PENDING,
        overlay_files={"artifact/prefetch/_planner/snapshot.md": b"intruder"},
    )

    cfg = _config(tmp_path, seed=_seed_dir(tmp_path))
    first_result = run_plan_exec_loop(cfg, ReplayRuntime(scenario_dir))
    assert first_result.final_status is FinalStatus.PROTOCOL_VIOLATION

    # Re-invoke with force=True. The contract is that no
    # `ResumeRefusedError` is raised — whatever final status the resumed
    # run reaches is post-gate behaviour and out of scope here.
    silent = _CountingRuntime(ReplayRuntime(scenario_dir))
    # Should not raise.
    run_plan_exec_loop(cfg, silent, force=True)


def test_resume_after_runtime_error_refuses_by_default(tmp_path: Path) -> None:
    """Prior `runtime_error` requires `force=True` to resume (resume.md §5.5)."""
    first = _ScriptedRuntime(
        plan_md=_PLAN_TWO_PENDING,
        post_plan_error=RuntimeError("LLM unavailable"),
    )
    cfg = _config(tmp_path)
    first_result = run_plan_exec_loop(cfg, first)
    assert first_result.final_status is FinalStatus.RUNTIME_ERROR

    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_ONE_DONE)
    _write_cassette(scenario_dir, "exec-0002", plan_md=_PLAN_BOTH_DONE)

    silent = _CountingRuntime(ReplayRuntime(scenario_dir))
    with pytest.raises(ResumeRefusedError) as excinfo:
        run_plan_exec_loop(cfg, silent)
    assert excinfo.value.prior_status is FinalStatus.RUNTIME_ERROR
    assert silent.iter_ids == []


def test_resume_force_drives_to_completion_after_runtime_error(tmp_path: Path) -> None:
    """`force=True` allows the resumed run to drain the remaining tasks."""
    first = _ScriptedRuntime(
        plan_md=_PLAN_TWO_PENDING,
        post_plan_error=RuntimeError("LLM unavailable"),
    )
    cfg = _config(tmp_path)
    run_plan_exec_loop(cfg, first)

    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_ONE_DONE)
    _write_cassette(scenario_dir, "exec-0002", plan_md=_PLAN_BOTH_DONE)
    runtime = _CountingRuntime(ReplayRuntime(scenario_dir))

    second_result = run_plan_exec_loop(cfg, runtime, force=True)

    assert second_result.final_status is FinalStatus.COMPLETED
    assert "plan" not in runtime.iter_ids
    assert runtime.iter_ids == ["exec-0001", "exec-0002"]


# ---------------------------------------------------------------------------
# Resume after budget_exhausted is allowed (clean exit, more budget granted)
# ---------------------------------------------------------------------------


def test_resume_after_budget_exhausted_continues(tmp_path: Path) -> None:
    """A `budget_exhausted` run resumes cleanly with a fresh executor budget."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "plan", plan_md=_PLAN_TWO_PENDING)
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_ONE_DONE)

    cfg = _config(tmp_path, max_iters=1)
    first_result = run_plan_exec_loop(cfg, ReplayRuntime(scenario_dir))
    assert first_result.final_status is FinalStatus.BUDGET_EXHAUSTED
    assert first_result.exec_iter_count == 1

    _write_cassette(scenario_dir, "exec-0002", plan_md=_PLAN_BOTH_DONE)
    runtime = _CountingRuntime(ReplayRuntime(scenario_dir))
    second_result = run_plan_exec_loop(cfg, runtime)

    assert second_result.final_status is FinalStatus.COMPLETED
    assert "plan" not in runtime.iter_ids
    assert runtime.iter_ids == ["exec-0002"]
    assert second_result.exec_iter_count == first_result.exec_iter_count + len(runtime.iter_ids)


# ---------------------------------------------------------------------------
# §5.7: resume_history is appended to (never rewritten in place)
# ---------------------------------------------------------------------------


def test_resume_history_records_one_entry_per_attempt(tmp_path: Path) -> None:
    """Fresh run produces a single-entry history; each resume appends one."""
    scenario_dir = tmp_path / "cassettes"
    _write_cassette(scenario_dir, "plan", plan_md=_PLAN_TWO_PENDING)
    _write_cassette(scenario_dir, "exec-0001", plan_md=_PLAN_ONE_DONE)

    cfg = _config(tmp_path, max_iters=1)
    first_result = run_plan_exec_loop(cfg, ReplayRuntime(scenario_dir))
    assert first_result.final_status is FinalStatus.BUDGET_EXHAUSTED

    history_after_first = _read_resume_history(cfg.run_dir)
    assert len(history_after_first) == 1
    first_entry = history_after_first[0]
    assert first_entry["final_status"] == "budget_exhausted"
    assert "started_at" in first_entry
    assert "ended_at" in first_entry

    _write_cassette(scenario_dir, "exec-0002", plan_md=_PLAN_BOTH_DONE)
    second_result = run_plan_exec_loop(cfg, ReplayRuntime(scenario_dir))
    assert second_result.final_status is FinalStatus.COMPLETED

    history_after_second = _read_resume_history(cfg.run_dir)
    expected_history_len_after_two_attempts = 2
    assert len(history_after_second) == expected_history_len_after_two_attempts
    # Prior entry is immutable: identical to what the first attempt wrote.
    assert history_after_second[0] == first_entry
    # New tail entry reflects the second attempt's terminal status.
    assert history_after_second[1]["final_status"] == "completed"


def _read_resume_history(run_dir: Path) -> list[dict[str, str]]:
    """Pull `config_snapshot.resume_history` from `<run_dir>/run.json`."""
    payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    history = payload["config_snapshot"]["resume_history"]
    assert isinstance(history, list)
    typed_history = cast("list[dict[str, str]]", history)
    return [dict(entry) for entry in typed_history]


# ---------------------------------------------------------------------------
# Internal helpers used by the partial-counter test
# ---------------------------------------------------------------------------


def _bootstrap_workspace(
    run_dir: Path,
    *,
    plan_md: str,
    partial_exec_ids: tuple[str, ...],
    prior_final_status: FinalStatus,
) -> None:
    """Hand-build a workspace that can be opened by `Workspace.open`.

    Writes `AGENTS.md`, the prompts, an empty `artifact/`, the supplied
    `plan.md`, an `iters/` skeleton with a healthy planner trajectory and
    one or more partial executor dirs (no `trajectory.json`), plus a
    `run.json` reflecting `prior_final_status` so the refusal-policy
    branch sees the expected prior state.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    (prompts_dir / "planner.md").write_text("planner-prompt", encoding="utf-8")
    (prompts_dir / "execute.md").write_text("execute-prompt", encoding="utf-8")
    (run_dir / "artifact").mkdir(exist_ok=True)
    (run_dir / "plan.md").write_text(plan_md, encoding="utf-8")

    iters_dir = run_dir / "iters"
    iters_dir.mkdir(exist_ok=True)
    plan_dir = iters_dir / "plan"
    plan_dir.mkdir(exist_ok=True)
    (plan_dir / "trajectory.json").write_text(
        json.dumps(_trajectory("plan").model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    for exec_id in partial_exec_ids:
        (iters_dir / exec_id).mkdir(exist_ok=True)

    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "final_status": prior_final_status.value,
                "plan_iter_count": 1,
                "exec_iter_count": 0,
                "trajectory_paths": ["iters/plan/trajectory.json"],
                "tasks_final": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
