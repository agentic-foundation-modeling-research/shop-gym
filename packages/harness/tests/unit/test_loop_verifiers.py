"""Loop-level tests for verifier dispatch (verifiers.md M1 + M2)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

from harness.config import FinalStatus, PlanExecLoopConfig, Prompts
from harness.loop import run_plan_exec_loop
from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import Trajectory
from harness.verifiers import Verdict, VerifierContext, VerifierResult

_TS = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)


class _StubRuntime:
    """Reusable scripted runtime mirroring the one in test_loop_signature."""

    def __init__(self, scripts: list[Callable[[Path, Path, str], None]]) -> None:
        self._scripts = list(scripts)
        self.prompts: list[str] = []

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del timeout
        self.prompts.append(prompt)
        if not self._scripts:
            raise AssertionError("stub runtime exhausted")
        script = self._scripts.pop(0)
        script(run_dir, iter_dir, prompt)
        return RuntimeIterationResult(
            trajectory=Trajectory(
                iter_id=iter_dir.name,
                runtime="stub",
                started_at=_TS,
                ended_at=_TS + dt.timedelta(seconds=1),
                exit_code=0,
                prompt_sha256="0" * 64,
            )
        )


class _RecordingPass:
    name = "rec_pass"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def applies_to(self, task_id: str) -> bool:
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        self.calls.append(ctx.iter_id)
        return VerifierResult(verdict=Verdict.PASS)


class _FailFirstThenPass:
    name = "fail_first"

    def __init__(self, feedback: str = "fix the thing") -> None:
        self._feedback = feedback
        self._calls = 0

    def applies_to(self, task_id: str) -> bool:
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        self._calls += 1
        if self._calls == 1:
            return VerifierResult(verdict=Verdict.FAIL, feedback=self._feedback)
        return VerifierResult(verdict=Verdict.PASS)


def _config(
    tmp_path: Path,
    *,
    verifiers: list[object] | None = None,
    execute: str = "execute-prompt",
    feedback_max_chars: int = 4000,
    max_iters: int = 4,
) -> PlanExecLoopConfig:
    kwargs: dict[str, object] = {
        "run_dir": tmp_path / "run",
        "prompts": Prompts(planner="planner-prompt", execute=execute),
        "agents_md": "# AGENTS\n",
        "max_iters": max_iters,
        "timeout": 30.0,
        "verifier_feedback_max_chars": feedback_max_chars,
    }
    if verifiers is not None:
        kwargs["verifiers"] = tuple(verifiers)
    return PlanExecLoopConfig(**kwargs)  # type: ignore[arg-type]


def _planner_writes(plan_md: str) -> Callable[[Path, Path, str], None]:
    def _script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text(plan_md, encoding="utf-8")

    return _script


def _executor_writes(plan_md: str) -> Callable[[Path, Path, str], None]:
    def _script(run_dir: Path, _iter_dir: Path, _prompt: str) -> None:
        (run_dir / "plan.md").write_text(plan_md, encoding="utf-8")

    return _script


# ---------------------------------------------------------------------------
# T1.6 (a) — empty verifiers leaves telemetry unchanged
# ---------------------------------------------------------------------------


def test_empty_verifiers_writes_no_verifier_telemetry(tmp_path: Path) -> None:
    runtime = _StubRuntime(
        [
            _planner_writes("# Plan\n## Tasks\n- [ ] homepage\n"),
            _executor_writes("# Plan\n## Tasks\n- [x] homepage\n"),
        ]
    )
    cfg = _config(tmp_path)
    result = run_plan_exec_loop(cfg, runtime)
    assert result.final_status is FinalStatus.COMPLETED
    assert result.verifier_runs == ()
    assert not (cfg.run_dir / "iters" / "exec-0001" / "checks" / "verifiers").exists()


# ---------------------------------------------------------------------------
# T1.6 (b) — all-PASS leaves [x] intact, writes per-verifier file
# ---------------------------------------------------------------------------


def test_all_pass_keeps_done_marker_and_writes_per_verifier_file(tmp_path: Path) -> None:
    plan_done = "# Plan\n## Tasks\n- [x] homepage\n"
    runtime = _StubRuntime(
        [
            _planner_writes("# Plan\n## Tasks\n- [ ] homepage\n"),
            _executor_writes(plan_done),
        ]
    )
    verifier = _RecordingPass()
    cfg = _config(tmp_path, verifiers=[verifier])
    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.COMPLETED
    assert verifier.calls == ["exec-0001"]
    assert len(result.verifier_runs) == 1
    assert result.verifier_runs[0].verdict is Verdict.PASS
    written = cfg.run_dir / "iters" / "exec-0001" / "checks" / "verifiers" / "rec_pass.json"
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"

    # Plan keeps the [x] marker, no feedback.md surfaced.
    assert (cfg.run_dir / "plan.md").read_text(encoding="utf-8") == plan_done
    assert not (
        cfg.run_dir / "iters" / "exec-0001" / "checks" / "verifiers" / "feedback.md"
    ).is_file()


# ---------------------------------------------------------------------------
# T1.6 (c) — FAIL rewrites [x] → [~] and surfaces feedback to next prompt
# ---------------------------------------------------------------------------


def test_fail_rewrites_marker_and_next_prompt_sees_feedback(tmp_path: Path) -> None:
    plan_initial = "# Plan\n## Tasks\n- [ ] homepage\n"
    plan_done = "# Plan\n## Tasks\n- [x] homepage\n"
    runtime = _StubRuntime(
        [
            _planner_writes(plan_initial),
            _executor_writes(plan_done),
            # Second iteration redoes the task and finishes.
            _executor_writes(plan_done),
        ]
    )
    cfg = _config(
        tmp_path,
        verifiers=[_FailFirstThenPass(feedback="please fix the layout")],
        execute="body before\n{{verifier_feedback}}\nbody after",
    )

    result = run_plan_exec_loop(cfg, runtime)

    assert result.final_status is FinalStatus.COMPLETED
    assert result.exec_iter_count == 2  # noqa: PLR2004 — fail-then-pass cycle

    # First iteration's verifier was FAIL; second was PASS.
    verdicts = tuple(r.verdict for r in result.verifier_runs)
    assert verdicts == (Verdict.FAIL, Verdict.PASS)

    # Feedback file landed on disk for iter 1.
    feedback_md = cfg.run_dir / "iters" / "exec-0001" / "checks" / "verifiers" / "feedback.md"
    assert feedback_md.is_file()
    body = feedback_md.read_text(encoding="utf-8")
    assert "## fail_first" in body
    assert "please fix the layout" in body

    # First-iteration prompt has empty feedback slot;
    # second-iteration prompt receives the verbatim feedback body.
    assert "please fix the layout" not in runtime.prompts[1]  # exec-0001 prompt
    assert "please fix the layout" in runtime.prompts[2]  # exec-0002 prompt


# ---------------------------------------------------------------------------
# T1.6 (d) — ERROR does not block
# ---------------------------------------------------------------------------


class _BoomVerifier:
    name = "boom"

    def applies_to(self, task_id: str) -> bool:
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        raise RuntimeError("kaboom")


def test_error_verifier_does_not_block_run(tmp_path: Path) -> None:
    plan_done = "# Plan\n## Tasks\n- [x] homepage\n"
    runtime = _StubRuntime(
        [
            _planner_writes("# Plan\n## Tasks\n- [ ] homepage\n"),
            _executor_writes(plan_done),
        ]
    )
    cfg = _config(tmp_path, verifiers=[_BoomVerifier()])
    result = run_plan_exec_loop(cfg, runtime)
    assert result.final_status is FinalStatus.COMPLETED
    assert result.verifier_runs[0].verdict is Verdict.ERROR
    # [x] retained — error is non-blocking.
    assert (cfg.run_dir / "plan.md").read_text(encoding="utf-8") == plan_done


# ---------------------------------------------------------------------------
# T2.2 — feedback truncation honoured by prompt slot, full body on disk
# ---------------------------------------------------------------------------


class _BigFeedbackFail:
    name = "big_feedback"

    def __init__(self, body: str) -> None:
        self._body = body
        self._calls = 0

    def applies_to(self, task_id: str) -> bool:
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        self._calls += 1
        if self._calls == 1:
            return VerifierResult(verdict=Verdict.FAIL, feedback=self._body)
        return VerifierResult(verdict=Verdict.PASS)


def test_feedback_truncation_only_at_prompt_render(tmp_path: Path) -> None:
    body = "x" * 200
    plan_initial = "# Plan\n## Tasks\n- [ ] homepage\n"
    plan_done = "# Plan\n## Tasks\n- [x] homepage\n"
    runtime = _StubRuntime(
        [
            _planner_writes(plan_initial),
            _executor_writes(plan_done),
            _executor_writes(plan_done),
        ]
    )
    cfg = _config(
        tmp_path,
        verifiers=[_BigFeedbackFail(body)],
        execute="exec\n{{verifier_feedback}}\nend",
        feedback_max_chars=50,
    )
    run_plan_exec_loop(cfg, runtime)

    # Truncated copy in iter-2 prompt
    iter2_prompt = runtime.prompts[2]
    assert "[...truncated]" in iter2_prompt
    # Full body still on disk
    feedback_md = cfg.run_dir / "iters" / "exec-0001" / "checks" / "verifiers" / "feedback.md"
    assert body in feedback_md.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T2.3 — slot rendering is a no-op when execute body lacks placeholder
# ---------------------------------------------------------------------------


def test_no_placeholder_no_injection(tmp_path: Path) -> None:
    plan_done = "# Plan\n## Tasks\n- [x] homepage\n"
    runtime = _StubRuntime(
        [
            _planner_writes("# Plan\n## Tasks\n- [ ] homepage\n"),
            _executor_writes(plan_done),
            _executor_writes(plan_done),
        ]
    )
    cfg = _config(
        tmp_path,
        verifiers=[_FailFirstThenPass()],
        execute="exec body without placeholder",
    )
    run_plan_exec_loop(cfg, runtime)
    iter2_prompt = runtime.prompts[2]
    assert "fix the thing" not in iter2_prompt


# ---------------------------------------------------------------------------
# T1.5 — run.json carries verifier_runs summary rows
# ---------------------------------------------------------------------------


def test_run_json_includes_verifier_runs(tmp_path: Path) -> None:
    plan_done = "# Plan\n## Tasks\n- [x] homepage\n"
    runtime = _StubRuntime(
        [
            _planner_writes("# Plan\n## Tasks\n- [ ] homepage\n"),
            _executor_writes(plan_done),
        ]
    )
    cfg = _config(tmp_path, verifiers=[_RecordingPass()])
    run_plan_exec_loop(cfg, runtime)
    payload = json.loads((cfg.run_dir / "run.json").read_text(encoding="utf-8"))
    assert "verifier_runs" in payload
    assert len(payload["verifier_runs"]) == 1
    row = payload["verifier_runs"][0]
    assert row["verdict"] == "pass"
    assert row["name"] == "rec_pass"
    # Summary rows must NOT carry feedback/details (spec §5.6).
    assert "feedback" not in row
    assert "details" not in row


# ---------------------------------------------------------------------------
# T1.4 — plan.after.md is captured BEFORE dispatch (reflects executor's intent)
# ---------------------------------------------------------------------------


def test_plan_after_md_captures_pre_dispatch_state(tmp_path: Path) -> None:
    """`plan.after.md` keeps the executor's `[x]` even when verifier rewrites it."""
    plan_done = "# Plan\n## Tasks\n- [x] homepage\n"
    runtime = _StubRuntime(
        [
            _planner_writes("# Plan\n## Tasks\n- [ ] homepage\n"),
            _executor_writes(plan_done),
            _executor_writes(plan_done),
        ]
    )
    cfg = _config(tmp_path, verifiers=[_FailFirstThenPass()])
    run_plan_exec_loop(cfg, runtime)
    plan_after = (cfg.run_dir / "iters" / "exec-0001" / "plan.after.md").read_text(encoding="utf-8")
    assert plan_after == plan_done
