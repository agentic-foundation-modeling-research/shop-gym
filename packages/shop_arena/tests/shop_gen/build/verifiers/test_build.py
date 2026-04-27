"""Unit tests for :class:`shop_gen.build.verifiers.build.BuildVerifier`.

Mirrors :mod:`test_tsc` because the two verifiers share the same
:class:`SubprocessRunner` injection seam. The test surface focuses on
the differences: argv, applicability, and timeout handling.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from harness.verifiers import Verdict, VerifierContext
from shop_gen.build.verifiers._subprocess import (
    CompletedSubprocess,
    SubprocessRunner,
)
from shop_gen.build.verifiers.build import BuildVerifier


def _runner(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    raises: BaseException | None = None,
    captured: list[tuple[Path, tuple[str, ...]]] | None = None,
) -> SubprocessRunner:
    """Stub :class:`SubprocessRunner`; see test_tsc._runner for the contract."""

    def _run(argv: Sequence[str], *, cwd: Path, timeout: float) -> CompletedSubprocess:
        del timeout
        if captured is not None:
            captured.append((cwd, tuple(argv)))
        if raises is not None:
            raise raises
        return CompletedSubprocess(returncode=returncode, stdout=stdout, stderr=stderr)

    return _run


def test_name_and_applicability() -> None:
    verifier = BuildVerifier(runner=_runner())
    assert verifier.name == "build"
    assert verifier.applies_to("gen_theme") is True
    assert verifier.applies_to("gen_homepage") is True
    assert verifier.applies_to("consolidate") is True
    assert verifier.applies_to("plan") is False


def test_passes_with_correct_argv(
    make_ctx: Callable[..., VerifierContext],
    hydrogen_tree: Path,
) -> None:
    captured: list[tuple[Path, tuple[str, ...]]] = []
    verifier = BuildVerifier(runner=_runner(captured=captured))
    result = verifier.run(make_ctx())

    assert result.verdict is Verdict.PASS
    assert result.details == {"returncode": 0}
    # The verifier intentionally drops `--filter hydrogen` (see module
    # docstring) and runs pnpm inside the hydrogen tree.
    assert captured == [(hydrogen_tree, ("pnpm", "build"))]


def test_fails_and_embeds_stderr(make_ctx: Callable[..., VerifierContext]) -> None:
    stderr = "[react-router] ERR_BUNDLE_FAILED missing route"
    verifier = BuildVerifier(runner=_runner(returncode=1, stderr=stderr))
    result = verifier.run(make_ctx())

    assert result.verdict is Verdict.FAIL
    assert "`pnpm build` failed." in result.feedback
    assert "ERR_BUNDLE_FAILED" in result.feedback
    assert result.details["returncode"] == 1
    assert result.details["argv"] == ["pnpm", "build"]


def test_timeout_returns_fail(make_ctx: Callable[..., VerifierContext]) -> None:
    timeout = subprocess.TimeoutExpired(cmd=["pnpm", "build"], timeout=1.0)
    verifier = BuildVerifier(timeout_s=1.0, runner=_runner(raises=timeout))
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "exceeded the verifier timeout" in result.feedback
    assert result.details == {"timeout_s": 1.0}


def test_truncation_protects_feedback_budget(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    huge_stdout = "Y" * 12_000
    verifier = BuildVerifier(runner=_runner(returncode=1, stdout=huge_stdout))
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "[...truncated]" in result.feedback
    assert len(result.feedback) < len(huge_stdout)


def test_default_runner_attribute_is_set() -> None:
    """Smoke-test the default seam — instantiation must not require args."""
    verifier = BuildVerifier()
    del verifier
