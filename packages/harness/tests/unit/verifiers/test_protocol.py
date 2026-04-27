"""Unit tests for the verifier public surface (verifiers.md §5.2 + §9.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.plan.tasks import TaskList
from harness.verifiers import (
    Verdict,
    Verifier,
    VerifierContext,
    VerifierResult,
    VerifierRun,
)


class _StubRuntime:
    """Minimal `AgentRuntime`-shaped object for `VerifierContext` tests."""

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


def test_verdict_includes_pass_fail_advisory_error() -> None:
    assert {v.value for v in Verdict} == {"pass", "fail", "advisory", "error"}


def test_verifier_result_defaults() -> None:
    res = VerifierResult(verdict=Verdict.PASS)
    assert res.feedback == ""
    assert res.details == {}


def test_verifier_result_is_frozen_and_extra_forbid() -> None:
    res = VerifierResult(verdict=Verdict.PASS)
    with pytest.raises(ValidationError):
        res.feedback = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        VerifierResult(verdict=Verdict.PASS, surprise=1)  # type: ignore[call-arg]


def test_verifier_context_carries_runtime_protocol(tmp_path: Path) -> None:
    ctx = VerifierContext(
        run_dir=tmp_path,
        iter_id="exec-0001",
        selected_task_id="homepage",
        plan=TaskList(tasks=()),
        artifact_dir=tmp_path / "artifact",
        runtime=_StubRuntime(),
    )
    assert ctx.iter_id == "exec-0001"
    assert ctx.runtime is not None  # type: ignore[unreachable]


def test_verifier_run_round_trips_through_json() -> None:
    run = VerifierRun(
        iter_id="exec-0002",
        name="tsc",
        task_id="gen_homepage",
        verdict=Verdict.FAIL,
        started_at_iso="2026-04-26T10:14:00+00:00",
        duration_ms=4220,
        path="iters/exec-0002/checks/verifiers/tsc.json",
    )
    payload = run.model_dump_json()
    restored = VerifierRun.model_validate_json(payload)
    assert restored == run
    assert restored.verdict is Verdict.FAIL


def test_verifier_run_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        VerifierRun(
            iter_id="exec-0001",
            name="tsc",
            task_id="t",
            verdict=Verdict.PASS,
            started_at_iso="2026-04-26T10:14:00+00:00",
            duration_ms=-1,
            path="iters/exec-0001/checks/verifiers/tsc.json",
        )


class _GoodVerifier:
    name = "good"

    def applies_to(self, task_id: str) -> bool:
        del task_id
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        return VerifierResult(verdict=Verdict.PASS)


def test_verifier_protocol_runtime_check() -> None:
    assert isinstance(_GoodVerifier(), Verifier)
