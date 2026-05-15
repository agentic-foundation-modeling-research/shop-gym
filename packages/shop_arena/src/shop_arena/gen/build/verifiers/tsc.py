"""``tsc`` build-loop verifier (spec §5.5.3).

Shells out to ``pnpm tsc --noEmit`` against the hydrogen tree under
``ctx.artifact_dir / "hydrogen"`` and surfaces a ``FAIL`` verdict with
the captured compiler output when typechecking does not pass cleanly.

Applicability mirrors the spec table: every ``gen_*`` task plus the
mandatory ``visual_fix`` task (spec §5.5.4).
"""

from __future__ import annotations

import subprocess
from typing import Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_arena.gen.build.verifiers._subprocess import (
    SubprocessRunner,
    default_subprocess_runner,
    truncate_stream,
)

_NAME: Final[str] = "tsc"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_DIR: Final[str] = "hydrogen"
"""Path of the hydrogen tree relative to ``VerifierContext.artifact_dir``."""

_DEFAULT_TIMEOUT_S: Final[float] = 180.0
"""Wall-clock budget for the typecheck. Hydrogen + react-router takes
~30s on a warm cache; the budget is conservative for cold runs."""

_ARGV: Final[tuple[str, ...]] = ("pnpm", "tsc", "--noEmit")
"""Process-spawn argument vector (spec §5.5.3 verbatim)."""


class TscVerifier:
    """Runs ``pnpm tsc --noEmit`` against the hydrogen tree.

    Attributes:
        name: ``"tsc"`` — used as the per-verifier telemetry filename
            and the markdown section heading in ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        runner: SubprocessRunner = default_subprocess_runner,
    ) -> None:
        """Build the verifier with optional injection seams.

        Args:
            timeout_s: Wall-clock budget for the ``pnpm`` invocation.
                Defaults to :data:`_DEFAULT_TIMEOUT_S`.
            runner: Subprocess runner used to spawn ``pnpm``. Tests
                inject a stub; production callers leave the default.
        """
        self._timeout_s = timeout_s
        self._runner = runner

    def applies_to(self, task_id: str) -> bool:
        """Match every ``gen_*`` task plus ``visual_fix`` (spec §5.5.4).

        Args:
            task_id: Selected task id (the executor's ``selected_task_id``).

        Returns:
            ``True`` when the verifier should run for ``task_id``.
        """
        return task_id.startswith("gen_") or task_id == "visual_fix"

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Spawn ``pnpm tsc --noEmit`` and translate the exit code into a verdict.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen tree; ``ctx.runtime`` is unused.

        Returns:
            ``PASS`` when ``pnpm`` returns 0; ``FAIL`` otherwise with
            the captured stdout/stderr embedded in the feedback
            markdown.

            A timeout is reported as ``FAIL`` with feedback explaining
            the budget was exhausted; the harness records the result
            without re-raising.
        """
        hydrogen_dir = ctx.artifact_dir / _HYDROGEN_DIR
        try:
            completed = self._runner(
                _ARGV,
                cwd=hydrogen_dir,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "`pnpm tsc --noEmit` exceeded the verifier "
                    f"timeout of {self._timeout_s:.0f}s. The typecheck "
                    "did not finish."
                ),
                details={"timeout_s": self._timeout_s},
            )
        if completed.returncode == 0:
            return VerifierResult(
                verdict=Verdict.PASS,
                details={"returncode": 0},
            )
        feedback = _render_failure_markdown(completed.stdout, completed.stderr)
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=feedback,
            details={
                "returncode": completed.returncode,
                "argv": list(_ARGV),
            },
        )


def _render_failure_markdown(stdout: str, stderr: str) -> str:
    """Render ``pnpm tsc`` failure output as feedback markdown.

    The harness pastes the returned string under a per-verifier heading
    in ``feedback.md``; using fenced code blocks keeps the compiler
    diagnostics legible to both the next iteration's agent and a human
    reading the run telemetry.

    Args:
        stdout: Captured standard output from the ``tsc`` invocation.
        stderr: Captured standard error from the ``tsc`` invocation.

    Returns:
        Multi-line markdown body with truncated stdout/stderr blocks.
    """
    lines = ["`pnpm tsc --noEmit` failed."]
    if stdout.strip():
        lines.extend(("", "stdout:", "```", truncate_stream(stdout.rstrip()), "```"))
    if stderr.strip():
        lines.extend(("", "stderr:", "```", truncate_stream(stderr.rstrip()), "```"))
    return "\n".join(lines)


__all__ = ["TscVerifier"]
