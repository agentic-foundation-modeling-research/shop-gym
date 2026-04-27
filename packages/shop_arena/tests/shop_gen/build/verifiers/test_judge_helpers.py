"""Unit tests for the shared LLM-judge helpers (T5.5).

The two LLM verifiers (``quality_judge`` + ``cross_task_consistency``)
delegate verdict parsing and runtime narrowing to
:mod:`shop_gen.build.verifiers._judge`. Per-verdict-shape coverage lives
here; the per-verifier tests focus on workspace-precondition + dispatch
behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.runtimes.base import RuntimeIterationResult
from harness.verifiers import Verdict
from shop_gen.build.verifiers._judge import (
    JudgeParseError,
    parse_judge_output,
    render_source_blocks,
    require_completer,
)


class _BareRuntime:
    """``AgentRuntime`` shape with no ``complete`` method."""

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del run_dir, iter_dir, prompt, timeout
        raise AssertionError("not used")


class _LLMRuntime(_BareRuntime):
    """``AgentRuntime`` that also implements :class:`LLMCompleter`."""

    def complete(self, prompt: str, *, timeout: float) -> str:
        del prompt, timeout
        return ""


def test_parse_judge_output_accepts_pass_with_empty_feedback() -> None:
    parsed = parse_judge_output('{"verdict": "pass", "feedback": ""}')
    assert parsed.verdict is Verdict.PASS
    assert parsed.feedback == ""


def test_parse_judge_output_accepts_fail_with_feedback() -> None:
    parsed = parse_judge_output(
        '{"verdict": "fail", "feedback": "homepage missing hero section"}',
    )
    assert parsed.verdict is Verdict.FAIL
    assert parsed.feedback == "homepage missing hero section"


def test_parse_judge_output_strips_fenced_code_block() -> None:
    raw = 'Here is my verdict.\n```json\n{"verdict": "fail", "feedback": "missing nav link"}\n```\n'
    parsed = parse_judge_output(raw)
    assert parsed.verdict is Verdict.FAIL
    assert parsed.feedback == "missing nav link"


def test_parse_judge_output_falls_back_to_bare_object() -> None:
    """An LLM that forgets the fence still parses if the JSON is well-formed."""
    raw = 'Final answer: {"verdict": "pass", "feedback": ""} (done)'
    parsed = parse_judge_output(raw)
    assert parsed.verdict is Verdict.PASS


def test_parse_judge_output_normalizes_verdict_case() -> None:
    parsed = parse_judge_output(
        '{"verdict": "PASS", "feedback": ""}',
    )
    assert parsed.verdict is Verdict.PASS


def test_parse_judge_output_rejects_non_object_payload() -> None:
    """A list-shaped response (no inner ``{...}``) is rejected verbosely."""
    with pytest.raises(JudgeParseError, match="does not contain a JSON object"):
        parse_judge_output('["pass"]')


def test_parse_judge_output_rejects_missing_verdict() -> None:
    with pytest.raises(JudgeParseError, match="missing a string `verdict`"):
        parse_judge_output('{"feedback": "ok"}')


def test_parse_judge_output_rejects_unknown_verdict() -> None:
    with pytest.raises(JudgeParseError, match="must be one of"):
        parse_judge_output('{"verdict": "advisory", "feedback": "x"}')


def test_parse_judge_output_rejects_fail_with_empty_feedback() -> None:
    with pytest.raises(JudgeParseError, match="empty"):
        parse_judge_output('{"verdict": "fail", "feedback": "  "}')


def test_parse_judge_output_rejects_invalid_json() -> None:
    with pytest.raises(JudgeParseError, match="not valid JSON"):
        parse_judge_output('{"verdict": fail}')


def test_parse_judge_output_rejects_response_without_object() -> None:
    with pytest.raises(JudgeParseError, match="does not contain a JSON object"):
        parse_judge_output("I cannot decide.")


def test_require_completer_returns_runtime_when_compatible() -> None:
    runtime = _LLMRuntime()
    out = require_completer(runtime, verifier_name="quality_judge")
    assert out is runtime


def test_require_completer_rejects_runtime_without_complete() -> None:
    with pytest.raises(TypeError, match="LLMCompleter"):
        require_completer(_BareRuntime(), verifier_name="quality_judge")


def test_render_source_blocks_walks_and_truncates(tmp_path: Path) -> None:
    app = tmp_path / "hydrogen" / "app"
    (app / "components").mkdir(parents=True)
    (app / "components" / "Hero.tsx").write_text(
        "export const Hero = () => null;\n",
        encoding="utf-8",
    )
    long_body = "x" * 200
    (app / "Big.tsx").write_text(long_body, encoding="utf-8")
    (app / "ignored.json").write_text('{"a": 1}', encoding="utf-8")

    blocks, reviewed, elided = render_source_blocks(
        app,
        max_bytes_per_file=64,
        max_total_bytes=10_000,
    )
    assert reviewed == 2  # noqa: PLR2004 -- two scannable files
    assert elided == 0
    assert "hydrogen/app/Big.tsx" in blocks
    assert "bytes elided" in blocks  # truncation marker
    # Non-allowlisted suffix is skipped.
    assert "ignored.json" not in blocks


def test_render_source_blocks_drops_files_past_total_budget(
    tmp_path: Path,
) -> None:
    app = tmp_path / "hydrogen" / "app"
    app.mkdir(parents=True)
    body = "y" * 100
    for index in range(5):
        (app / f"f{index}.tsx").write_text(body, encoding="utf-8")
    blocks, reviewed, elided = render_source_blocks(
        app,
        max_bytes_per_file=200,
        max_total_bytes=250,
    )
    # Exact partition depends on the byte rendering of the surrounding
    # markdown; what we lock is "some files were elided + the elision
    # note appears verbatim".
    assert reviewed >= 1
    assert elided >= 1
    assert "additional file(s) elided" in blocks


def test_render_source_blocks_handles_empty_tree(tmp_path: Path) -> None:
    app = tmp_path / "hydrogen" / "app"
    app.mkdir(parents=True)
    blocks, reviewed, elided = render_source_blocks(
        app,
        max_bytes_per_file=64,
        max_total_bytes=10_000,
    )
    assert reviewed == 0
    assert elided == 0
    assert "no reviewable source files" in blocks
