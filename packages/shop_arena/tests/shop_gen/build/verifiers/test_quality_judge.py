"""Unit tests for :class:`shop_gen.build.verifiers.quality_judge.QualityJudgeVerifier`.

Covers T5.5 + spec §5.5.3: the verifier renders ``capabilities.json``
plus the hydrogen sources into a prompt, calls
``ctx.runtime.complete``, and translates the LLM's JSON verdict into a
:class:`harness.verifiers.VerifierResult`.

The tests inject a stub :class:`~harness.runtimes.LLMCompleter` through
``make_ctx(runtime=...)`` so no model is actually queried.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from harness.runtimes.base import RuntimeIterationResult
from harness.verifiers import Verdict, VerifierContext
from shop_gen.build.verifiers.quality_judge import QualityJudgeVerifier

# --------------------------------------------------------------------------- #
# Test stubs
# --------------------------------------------------------------------------- #


class _AgentRuntimeStub:
    """``AgentRuntime`` shape; the LLM verifiers never call ``run_iteration``."""

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del run_dir, iter_dir, prompt, timeout
        raise AssertionError("verifier tests do not invoke run_iteration")


class _StubLLM(_AgentRuntimeStub):
    """``LLMCompleter`` stub: records prompts, returns canned responses FIFO."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses: list[str] = list(responses) if responses is not None else []
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM was called more times than expected")
        return self.responses.pop(0)


class _RaisingLLM(_AgentRuntimeStub):
    """``LLMCompleter`` stub that raises on ``complete``."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        raise self._exc


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #


_MINIMAL_CAPABILITIES: dict[str, object] = {
    "version": "0.1",
    "shop": {
        "descriptor": "Premium Storefront",
        "category": "fashion",
        "currency": "USD",
        "tone": ["clean"],
    },
    "site_shell": {"nav_depth": 1},
    "homepage": {"section_types": ["hero"], "section_count": 1},
    "collection": {"filters": [], "sort": []},
    "product": {"variant_selectors": []},
    "search": {"predictive_types": []},
    "info_pages_present": [],
}


def _seed_capabilities(artifact_dir: Path) -> Path:
    """Write the minimal capabilities document into the verifier's view."""
    target = artifact_dir / "capabilities.json"
    target.write_text(json.dumps(_MINIMAL_CAPABILITIES), encoding="utf-8")
    return target


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_name_and_applicability() -> None:
    verifier = QualityJudgeVerifier()
    assert verifier.name == "quality_judge"
    # Per spec §5.5.3.
    for task_id in (
        "gen_homepage",
        "gen_product",
        "gen_cart_search",
        "visual_fix",
    ):
        assert verifier.applies_to(task_id) is True, f"missing task {task_id}"
    # Other gen_* tasks (and non-gen tasks) are out of scope.
    assert verifier.applies_to("gen_theme") is False
    assert verifier.applies_to("gen_navigation") is False
    assert verifier.applies_to("plan") is False


def test_passes_when_llm_returns_pass(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_capabilities(artifact_dir)
    write_app_file(
        "routes/_index.tsx",
        "export default function Home() { return <section data-hero />; }\n",
    )
    runtime = _StubLLM(responses=['{"verdict": "pass", "feedback": ""}'])
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))

    assert result.verdict is Verdict.PASS
    assert result.feedback == ""
    assert result.details["files_reviewed"] == 1
    assert result.details["task_id"] == "gen_homepage"
    # The prompt must mention the selected task + the capabilities slot.
    [prompt] = runtime.prompts
    assert "gen_homepage" in prompt
    assert "Premium Storefront" in prompt
    assert "data-hero" in prompt  # the source block was forwarded


def test_fails_when_llm_returns_fail_with_feedback(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_capabilities(artifact_dir)
    write_app_file("routes/_index.tsx", "export default function Home() { return null; }\n")
    runtime = _StubLLM(
        responses=[
            '{"verdict": "fail", "feedback": "homepage missing hero section"}',
        ],
    )
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "homepage missing hero section" in result.feedback


def test_fail_when_capabilities_missing(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    runtime = _StubLLM(responses=[])  # no LLM call expected
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "capabilities.json" in result.feedback
    assert result.details["exists"] is False
    # The verifier short-circuits before invoking the LLM.
    assert runtime.prompts == []


def test_fail_when_capabilities_invalid_json(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
) -> None:
    (artifact_dir / "capabilities.json").write_text("not json", encoding="utf-8")
    runtime = _StubLLM(responses=[])
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "could not parse" in result.feedback
    assert runtime.prompts == []


def test_fail_when_hydrogen_tree_missing(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
) -> None:
    _seed_capabilities(artifact_dir)
    # Strip the app/ subtree.
    (artifact_dir / "hydrogen" / "app").rmdir()
    (artifact_dir / "hydrogen").rmdir()
    runtime = _StubLLM(responses=[])
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "hydrogen app tree" in result.feedback
    assert runtime.prompts == []


def test_fail_on_llm_timeout(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_capabilities(artifact_dir)
    write_app_file("routes/_index.tsx", "export default null;\n")
    runtime = _RaisingLLM(exc=subprocess.TimeoutExpired(cmd="llm", timeout=180.0))
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "timeout" in result.feedback.lower()
    assert result.details["phase"] == "llm_complete"


def test_fail_on_llm_arbitrary_error(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_capabilities(artifact_dir)
    write_app_file("routes/_index.tsx", "export default null;\n")
    runtime = _RaisingLLM(exc=RuntimeError("model returned 500"))
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "RuntimeError" in result.feedback


def test_fail_on_unparseable_llm_response(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_capabilities(artifact_dir)
    write_app_file("routes/_index.tsx", "export default null;\n")
    runtime = _StubLLM(responses=["I am not sure."])
    verifier = QualityJudgeVerifier()
    result = verifier.run(make_ctx(runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "could not parse the LLM verdict" in result.feedback
    assert result.details["phase"] == "parse"
    assert result.details["raw"] == "I am not sure."


def test_runtime_without_completer_raises(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A runtime that does not implement :class:`LLMCompleter` is a wiring bug."""
    _seed_capabilities(artifact_dir)
    write_app_file("routes/_index.tsx", "export default null;\n")
    verifier = QualityJudgeVerifier()
    with pytest.raises(TypeError, match="LLMCompleter"):
        # The default fixture runtime is a bare ``AgentRuntime`` without
        # ``complete``; the LLM verifier surfaces that as a TypeError so
        # the wiring bug is loud rather than silently advisory.
        verifier.run(make_ctx())
