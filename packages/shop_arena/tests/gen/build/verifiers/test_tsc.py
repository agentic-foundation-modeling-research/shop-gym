"""Unit tests for :class:`shop_arena.gen.build.verifiers.tsc.TscVerifier`.

Covers the T5.4 contract: the verifier shells out to
``pnpm tsc --noEmit`` against ``ctx.artifact_dir / "hydrogen"`` and
translates the exit code into a :class:`Verdict`. The
:class:`SubprocessRunner` injection seam keeps the tests
toolchain-free.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from harness.verifiers import Verdict, VerifierContext
from shop_arena.gen.build.verifiers._subprocess import (
    CompletedSubprocess,
    SubprocessRunner,
)
from shop_arena.gen.build.verifiers.tsc import TscVerifier


def _runner(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    raises: BaseException | None = None,
    captured: list[tuple[Path, tuple[str, ...]]] | None = None,
) -> SubprocessRunner:
    """Build a :class:`SubprocessRunner` stub returning a scripted result.

    Args:
        returncode: Exit code the stub reports.
        stdout: Captured stdout body.
        stderr: Captured stderr body.
        raises: When set, the stub raises this exception instead of
            returning a result.
        captured: Optional list the stub appends ``(cwd, argv)`` tuples
            to so tests can assert spawn arguments.
    """

    def _run(
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
    ) -> CompletedSubprocess:
        del timeout
        if captured is not None:
            captured.append((cwd, tuple(argv)))
        if raises is not None:
            raise raises
        return CompletedSubprocess(returncode=returncode, stdout=stdout, stderr=stderr)

    return _run


def test_name_and_applicability() -> None:
    verifier = TscVerifier(runner=_runner())
    assert verifier.name == "tsc"
    assert verifier.applies_to("gen_theme") is True
    assert verifier.applies_to("gen_homepage") is True
    assert verifier.applies_to("visual_fix") is True
    assert verifier.applies_to("plan") is False


def test_passes_when_runner_returns_zero(
    make_ctx: Callable[..., VerifierContext],
    hydrogen_tree: Path,
) -> None:
    captured: list[tuple[Path, tuple[str, ...]]] = []
    verifier = TscVerifier(runner=_runner(captured=captured))
    result = verifier.run(make_ctx())

    assert result.verdict is Verdict.PASS
    assert result.feedback == ""
    assert result.details == {"returncode": 0}
    # Spawn target is the hydrogen tree, with the spec-prescribed argv.
    assert captured == [(hydrogen_tree, ("pnpm", "tsc", "--noEmit"))]


def test_fails_when_runner_returns_nonzero_and_embeds_streams(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    verifier = TscVerifier(
        runner=_runner(
            returncode=2,
            stdout="src/components/Header.tsx(12,5): error TS2322: ...",
            stderr="error TS2322: Type 'string' is not assignable",
        ),
    )
    result = verifier.run(make_ctx())

    assert result.verdict is Verdict.FAIL
    assert "`pnpm tsc --noEmit` failed." in result.feedback
    assert "stdout:" in result.feedback
    assert "stderr:" in result.feedback
    assert "TS2322" in result.feedback
    assert result.details["returncode"] == 2  # noqa: PLR2004
    assert result.details["argv"] == ["pnpm", "tsc", "--noEmit"]


def test_skips_empty_stream_blocks(make_ctx: Callable[..., VerifierContext]) -> None:
    """Empty stdout/stderr should not produce empty fenced code blocks."""
    verifier = TscVerifier(
        runner=_runner(returncode=1, stdout="", stderr="boom\n"),
    )
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "stdout:" not in result.feedback
    assert "stderr:" in result.feedback


def test_truncates_large_stream(make_ctx: Callable[..., VerifierContext]) -> None:
    """A very large stderr should be trimmed before reaching feedback."""
    huge = "X" * 10_000
    verifier = TscVerifier(runner=_runner(returncode=1, stderr=huge))
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "[...truncated]" in result.feedback
    assert len(result.feedback) < len(huge)


def test_timeout_returns_fail_without_propagating(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    timeout = subprocess.TimeoutExpired(cmd=["pnpm", "tsc", "--noEmit"], timeout=1.0)
    verifier = TscVerifier(timeout_s=1.0, runner=_runner(raises=timeout))
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "exceeded the verifier timeout" in result.feedback
    assert result.details == {"timeout_s": 1.0}


def test_default_runner_attribute_is_callable() -> None:
    """Smoke-test the default seam without spawning ``pnpm``."""
    verifier = TscVerifier()
    del verifier


def test_passing_synthetic_tree_does_not_require_app_dir(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    """The verifier should not require a populated tree to PASS.

    Spec §5.5.3: ``tsc`` runs ``pnpm`` against the hydrogen tree; if
    ``pnpm`` says the tree is fine, the verifier is fine.
    """
    verifier = TscVerifier(runner=_runner(returncode=0))
    ctx = make_ctx(selected_task_id="visual_fix")
    result = verifier.run(ctx)
    assert result.verdict is Verdict.PASS


def test_failing_synthetic_tree_uses_failing_runner(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    """A failing ``pnpm`` invocation surfaces FAIL even when the tree is empty."""
    verifier = TscVerifier(
        runner=_runner(
            returncode=1,
            stderr="error TS5033: Could not write file.",
        ),
    )
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "TS5033" in result.feedback


@pytest.mark.parametrize(
    "task_id",
    ["gen_theme", "gen_navigation", "gen_homepage", "visual_fix"],
)
def test_runs_against_all_gating_task_ids(
    make_ctx: Callable[..., VerifierContext],
    task_id: str,
) -> None:
    verifier = TscVerifier(runner=_runner(returncode=0))
    assert verifier.applies_to(task_id)
    assert verifier.run(make_ctx(selected_task_id=task_id)).verdict is Verdict.PASS
