"""Unit tests for `harness.verifiers.dispatch` (verifiers.md §5.3)."""

from __future__ import annotations

import json
from pathlib import Path

from harness.plan.tasks import TaskList
from harness.verifiers import Verdict, VerifierContext, VerifierResult
from harness.verifiers.dispatch import (
    dispatch_verifiers,
    render_feedback_for_prompt,
    rewrite_selected_task_marker,
)


class _StubRuntime:
    def run_iteration(  # type: ignore[no-untyped-def]
        self,
        *,
        run_dir,
        iter_dir,
        prompt,
        timeout,
    ):
        del run_dir, iter_dir, prompt, timeout
        raise NotImplementedError


class _AlwaysPass:
    name = "always_pass"

    def applies_to(self, task_id: str) -> bool:
        del task_id
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        return VerifierResult(verdict=Verdict.PASS)


class _AlwaysFail:
    name = "always_fail"

    def __init__(self, feedback: str = "broken") -> None:
        self._feedback = feedback

    def applies_to(self, task_id: str) -> bool:
        del task_id
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=self._feedback,
            details={"why": "stub"},
        )


class _Advisory:
    name = "advisory"

    def applies_to(self, task_id: str) -> bool:
        del task_id
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        return VerifierResult(verdict=Verdict.ADVISORY, feedback="heads up")


class _Boom:
    name = "boom"

    def applies_to(self, task_id: str) -> bool:
        del task_id
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        raise RuntimeError("kaboom")


class _OnlyHomepage:
    name = "only_homepage"

    def applies_to(self, task_id: str) -> bool:
        return task_id == "homepage"

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        return VerifierResult(verdict=Verdict.PASS)


def _setup_workspace(tmp_path: Path, plan_md: str) -> tuple[Path, Path, Path]:
    """Create a minimal run_dir with the iter_dir scaffold."""
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "artifact"
    iter_dir = run_dir / "iters" / "exec-0001"
    iter_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (run_dir / "plan.md").write_text(plan_md, encoding="utf-8")
    return run_dir, artifact_dir, iter_dir


def _dispatch(
    tmp_path: Path,
    *,
    verifiers: list[object],
    plan_md: str = "## Tasks\n- [x] homepage\n",
    selected_task_id: str = "homepage",
    feedback_max_chars: int = 4000,
):
    run_dir, artifact_dir, iter_dir = _setup_workspace(tmp_path, plan_md)
    plan = TaskList(tasks=())
    return (
        dispatch_verifiers(
            verifiers=verifiers,  # type: ignore[arg-type]
            iter_dir=iter_dir,
            iter_id="exec-0001",
            run_dir=run_dir,
            selected_task_id=selected_task_id,
            plan=plan,
            artifact_dir=artifact_dir,
            runtime=_StubRuntime(),
            feedback_max_chars=feedback_max_chars,
        ),
        run_dir,
        iter_dir,
    )


def test_dispatch_with_no_verifiers_is_a_noop(tmp_path: Path) -> None:
    outcome, run_dir, iter_dir = _dispatch(tmp_path, verifiers=[])
    assert outcome.runs == ()
    assert outcome.blocking is False
    assert outcome.wrote_feedback is False
    assert not (iter_dir / "checks").exists()
    # Plan unchanged.
    assert (run_dir / "plan.md").read_text(encoding="utf-8") == "## Tasks\n- [x] homepage\n"


def test_dispatch_pass_writes_per_verifier_file_and_does_not_block(tmp_path: Path) -> None:
    outcome, _, iter_dir = _dispatch(tmp_path, verifiers=[_AlwaysPass()])
    assert outcome.blocking is False
    assert outcome.wrote_feedback is False
    assert len(outcome.runs) == 1
    written = iter_dir / "checks" / "verifiers" / "always_pass.json"
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"
    assert payload["task_id"] == "homepage"
    assert payload["iter_id"] == "exec-0001"


def test_dispatch_fail_blocks_and_rewrites_marker(tmp_path: Path) -> None:
    outcome, run_dir, _iter_dir = _dispatch(tmp_path, verifiers=[_AlwaysFail()])
    assert outcome.blocking is True
    assert outcome.wrote_feedback is True
    assert (run_dir / "plan.md").read_text(encoding="utf-8") == "## Tasks\n- [~] homepage\n"


def test_dispatch_advisory_does_not_block(tmp_path: Path) -> None:
    outcome, run_dir, iter_dir = _dispatch(tmp_path, verifiers=[_Advisory()])
    assert outcome.blocking is False
    assert outcome.wrote_feedback is True
    fb = (iter_dir / "checks" / "verifiers" / "feedback.md").read_text(encoding="utf-8")
    assert "## advisory" in fb
    assert "heads up" in fb
    # Marker untouched.
    assert (run_dir / "plan.md").read_text(encoding="utf-8") == "## Tasks\n- [x] homepage\n"


def test_dispatch_exception_is_recorded_as_error_and_does_not_block(tmp_path: Path) -> None:
    outcome, run_dir, iter_dir = _dispatch(tmp_path, verifiers=[_Boom()])
    assert outcome.blocking is False
    assert len(outcome.runs) == 1
    assert outcome.runs[0].verdict is Verdict.ERROR
    written = iter_dir / "checks" / "verifiers" / "boom.json"
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["verdict"] == "error"
    assert "kaboom" in payload["feedback"]
    assert (run_dir / "plan.md").read_text(encoding="utf-8") == "## Tasks\n- [x] homepage\n"


def test_dispatch_filters_by_applies_to(tmp_path: Path) -> None:
    outcome, _, iter_dir = _dispatch(
        tmp_path,
        verifiers=[_OnlyHomepage()],
        selected_task_id="other",
    )
    assert outcome.runs == ()
    # Per-verifier file must not be written for non-applicable verifiers.
    assert not (iter_dir / "checks" / "verifiers").exists()


def test_dispatch_preserves_registration_order(tmp_path: Path) -> None:
    outcome, _, _iter_dir = _dispatch(
        tmp_path,
        verifiers=[_AlwaysPass(), _Advisory(), _AlwaysFail()],
    )
    names = tuple(run.name for run in outcome.runs)
    assert names == ("always_pass", "advisory", "always_fail")


def test_rewrite_marker_handles_x_with_priority_and_note(tmp_path: Path) -> None:
    plan_md = "## Tasks\n- [x] homepage [priority: 5] — done\n- [ ] other\n"
    plan = tmp_path / "plan.md"
    plan.write_text(plan_md, encoding="utf-8")
    rewrite_selected_task_marker(plan, "homepage")
    assert plan.read_text(encoding="utf-8") == (
        "## Tasks\n- [~] homepage [priority: 5] — done\n- [ ] other\n"
    )


def test_rewrite_marker_handles_blocked_marker(tmp_path: Path) -> None:
    plan_md = "## Tasks\n- [!] homepage\n"
    plan = tmp_path / "plan.md"
    plan.write_text(plan_md, encoding="utf-8")
    rewrite_selected_task_marker(plan, "homepage")
    assert plan.read_text(encoding="utf-8") == "## Tasks\n- [~] homepage\n"


def test_rewrite_marker_leaves_other_tasks_untouched(tmp_path: Path) -> None:
    plan_md = "## Tasks\n- [x] homepage\n- [x] other\n"
    plan = tmp_path / "plan.md"
    plan.write_text(plan_md, encoding="utf-8")
    rewrite_selected_task_marker(plan, "homepage")
    assert plan.read_text(encoding="utf-8") == "## Tasks\n- [~] homepage\n- [x] other\n"


def test_rewrite_marker_is_a_noop_for_non_terminal_marker(tmp_path: Path) -> None:
    plan_md = "## Tasks\n- [ ] homepage\n"
    plan = tmp_path / "plan.md"
    plan.write_text(plan_md, encoding="utf-8")
    rewrite_selected_task_marker(plan, "homepage")
    assert plan.read_text(encoding="utf-8") == plan_md


def test_render_feedback_returns_empty_when_missing(tmp_path: Path) -> None:
    assert render_feedback_for_prompt(tmp_path / "missing.md", max_chars=100) == ""


def test_render_feedback_truncates_with_marker(tmp_path: Path) -> None:
    body = "x" * 100
    fb = tmp_path / "feedback.md"
    fb.write_text(body, encoding="utf-8")
    rendered = render_feedback_for_prompt(fb, max_chars=10)
    assert rendered.startswith("x" * 10)
    assert rendered.endswith("[...truncated]")


def test_render_feedback_passthrough_within_budget(tmp_path: Path) -> None:
    body = "short body"
    fb = tmp_path / "feedback.md"
    fb.write_text(body, encoding="utf-8")
    assert render_feedback_for_prompt(fb, max_chars=100) == body
