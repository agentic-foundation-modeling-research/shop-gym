"""Unit tests for the ``cross_task_consistency`` build-loop verifier.

Covers T5.5 + spec §5.5.4: the verifier renders ``data/collections.json``
+ the hydrogen sources into a prompt, calls ``ctx.runtime.complete``,
and translates the LLM's JSON verdict into a
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
from shop_gen.build.verifiers.cross_task_consistency import (
    CrossTaskConsistencyVerifier,
)

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
# Helpers
# --------------------------------------------------------------------------- #


def _seed_collections(
    artifact_dir: Path,
    *,
    handles: tuple[str, ...] = ("best-sellers", "new-arrivals"),
) -> Path:
    """Write a minimal ``data/collections.json`` payload."""
    target = artifact_dir / "data" / "collections.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([{"handle": handle, "title": handle.title()} for handle in handles]),
        encoding="utf-8",
    )
    return target


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_name_and_applicability() -> None:
    verifier = CrossTaskConsistencyVerifier()
    assert verifier.name == "cross_task_consistency"
    # Per spec §5.5.4: post-consolidate only.
    assert verifier.applies_to("consolidate") is True
    # Every other task is out of scope by design.
    for task_id in (
        "gen_homepage",
        "gen_product",
        "gen_cart_search",
        "gen_navigation",
        "gen_theme",
        "visual_polish",
        "plan",
    ):
        assert verifier.applies_to(task_id) is False, f"unexpected match {task_id}"


def test_passes_when_llm_returns_pass(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_collections(artifact_dir)
    write_app_file(
        "routes/collections.$handle.tsx",
        "export default function Collection() { return null; }\n",
    )
    runtime = _StubLLM(responses=['{"verdict": "pass", "feedback": ""}'])
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))

    assert result.verdict is Verdict.PASS
    assert result.feedback == ""
    assert result.details["files_reviewed"] == 1
    assert result.details["collection_handles"] == ["best-sellers", "new-arrivals"]
    [prompt] = runtime.prompts
    assert "best-sellers" in prompt
    assert "new-arrivals" in prompt
    assert "collections.$handle.tsx" in prompt


def test_fails_when_llm_returns_fail(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_collections(artifact_dir)
    write_app_file("routes/collections.$handle.tsx", "export default null;\n")
    runtime = _StubLLM(
        responses=[
            '{"verdict": "fail", "feedback": "navigation references a missing handle"}',
        ],
    )
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "navigation references a missing handle" in result.feedback


def test_fail_when_collections_missing(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    runtime = _StubLLM(responses=[])
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "collections.json" in result.feedback
    assert runtime.prompts == []


def test_fail_when_collections_invalid_json(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
) -> None:
    target = artifact_dir / "data" / "collections.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not json", encoding="utf-8")
    runtime = _StubLLM(responses=[])
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "could not parse" in result.feedback
    assert runtime.prompts == []


def test_fail_when_hydrogen_tree_missing(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
) -> None:
    _seed_collections(artifact_dir)
    (artifact_dir / "hydrogen" / "app").rmdir()
    (artifact_dir / "hydrogen").rmdir()
    runtime = _StubLLM(responses=[])
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "hydrogen" in result.feedback
    assert runtime.prompts == []


def test_collection_payload_with_non_dict_entries_yields_empty_handles(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A malformed collections payload is forwarded as an empty handle list.

    The verifier deliberately stays structurally permissive — schema
    enforcement is the upstream verifier's job; here we only need
    enough information to render the cross-task prompt.
    """
    target = artifact_dir / "data" / "collections.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(["not-an-object", 1, None]), encoding="utf-8")
    write_app_file("routes/_index.tsx", "export default null;\n")
    runtime = _StubLLM(responses=['{"verdict": "pass", "feedback": ""}'])
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))
    assert result.verdict is Verdict.PASS
    assert result.details["collection_handles"] == []


def test_fail_on_llm_timeout(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_collections(artifact_dir)
    write_app_file("routes/_index.tsx", "export default null;\n")
    runtime = _RaisingLLM(exc=subprocess.TimeoutExpired(cmd="llm", timeout=240.0))
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "timeout" in result.feedback.lower()
    assert result.details["phase"] == "llm_complete"


def test_fail_on_unparseable_llm_response(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    _seed_collections(artifact_dir)
    write_app_file("routes/_index.tsx", "export default null;\n")
    runtime = _StubLLM(responses=["the answer depends"])
    verifier = CrossTaskConsistencyVerifier()
    result = verifier.run(make_ctx(selected_task_id="consolidate", runtime=runtime))
    assert result.verdict is Verdict.FAIL
    assert "could not parse the LLM" in result.feedback
    assert result.details["phase"] == "parse"


def test_runtime_without_completer_raises(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A runtime that does not implement :class:`LLMCompleter` is a wiring bug."""
    _seed_collections(artifact_dir)
    write_app_file("routes/_index.tsx", "export default null;\n")
    verifier = CrossTaskConsistencyVerifier()
    with pytest.raises(TypeError, match="LLMCompleter"):
        verifier.run(make_ctx(selected_task_id="consolidate"))
