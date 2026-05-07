"""Smoke tests for the reference verifier fixtures (verifiers.md §9.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.plan.tasks import TaskList
from harness.verifiers import Verdict, VerifierContext
from tests.integration.verifiers import (
    AlwaysFail,
    AlwaysPass,
    LLMCompleterDriven,
    RaisesException,
)


class _NoCompleterRuntime:
    """`AgentRuntime`-shaped object with no `complete()` method."""

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


class _CompleterRuntime(_NoCompleterRuntime):
    """`AgentRuntime` that also implements `LLMCompleter`."""

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        return f"completed: {prompt}"


def _ctx(tmp_path: Path, runtime: object) -> VerifierContext:
    return VerifierContext(
        run_dir=tmp_path,
        iter_id="exec-0001",
        selected_task_id="homepage",
        plan=TaskList(tasks=()),
        artifact_dir=tmp_path / "artifact",
        runtime=runtime,  # type: ignore[arg-type]
    )


def test_always_pass_returns_pass(tmp_path: Path) -> None:
    verifier = AlwaysPass()
    assert verifier.applies_to("any") is True
    result = verifier.run(_ctx(tmp_path, _NoCompleterRuntime()))
    assert result.verdict is Verdict.PASS


def test_always_pass_respects_scope(tmp_path: Path) -> None:
    verifier = AlwaysPass(scope="homepage")
    assert verifier.applies_to("homepage") is True
    assert verifier.applies_to("other") is False


def test_always_fail_returns_fail_with_feedback(tmp_path: Path) -> None:
    verifier = AlwaysFail(feedback="please fix layout")
    result = verifier.run(_ctx(tmp_path, _NoCompleterRuntime()))
    assert result.verdict is Verdict.FAIL
    assert result.feedback == "please fix layout"
    assert result.details == {"source": "AlwaysFail"}


def test_raises_exception_propagates(tmp_path: Path) -> None:
    verifier = RaisesException(message="boom!")
    with pytest.raises(RuntimeError, match="boom!"):
        verifier.run(_ctx(tmp_path, _NoCompleterRuntime()))


def test_llm_completer_driven_uses_runtime_complete(tmp_path: Path) -> None:
    verifier = LLMCompleterDriven(prompt="judge me")
    result = verifier.run(_ctx(tmp_path, _CompleterRuntime()))
    assert result.verdict is Verdict.ADVISORY
    assert result.feedback == "completed: judge me"


def test_llm_completer_driven_returns_error_when_no_completer(tmp_path: Path) -> None:
    verifier = LLMCompleterDriven()
    result = verifier.run(_ctx(tmp_path, _NoCompleterRuntime()))
    assert result.verdict is Verdict.ERROR
    assert "LLMCompleter" in result.feedback
