"""``build`` build-loop verifier (spec §5.5.3).

Shells out to ``pnpm build`` against the hydrogen tree under
``ctx.artifact_dir / "hydrogen"``. The hydrogen template's ``build``
script is ``react-router typegen && react-router build`` (see the
shipped ``package.json``); a non-zero exit code signals either a
type-generation failure or a bundler error.

Spec §5.5.3 phrases the command as ``pnpm --filter hydrogen build``.
The artifact tree the harness loop drives is a freestanding hydrogen
package — not a member of any pnpm workspace — so ``--filter`` would
have no scope to bind to. Running ``pnpm build`` from inside the
hydrogen directory invokes the same ``build`` script; the spec's
phrasing is approximate.

Applicability mirrors :class:`TscVerifier`: every ``gen_*`` task plus
the mandatory ``visual_fix`` task (spec §5.5.4).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_arena.gen.build.verifiers._subprocess import (
    SubprocessRunner,
    default_subprocess_runner,
    truncate_stream,
)

_NAME: Final[str] = "build"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_DIR: Final[str] = "hydrogen"
"""Path of the hydrogen tree relative to ``VerifierContext.artifact_dir``."""

_DEFAULT_TIMEOUT_S: Final[float] = 600.0
"""Wall-clock budget for ``pnpm build``. The hydrogen template's build
chains ``react-router typegen`` + ``react-router build``; a cold cache
on CI hardware finishes well inside ten minutes."""

_ARGV: Final[tuple[str, ...]] = ("pnpm", "build")
"""Process-spawn argument vector. See the module docstring for why
``--filter hydrogen`` is dropped from the spec phrasing."""


class BuildVerifier:
    """Runs ``pnpm build`` against the hydrogen tree.

    Attributes:
        name: ``"build"`` — used as the per-verifier telemetry filename
            and the markdown section heading in ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        app_dir: Path = Path(_HYDROGEN_DIR),
        argv: tuple[str, ...] = _ARGV,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        runner: SubprocessRunner = default_subprocess_runner,
    ) -> None:
        """Build the verifier with optional injection seams.

        Args:
            app_dir: Storefront app directory relative to
                ``VerifierContext.artifact_dir``. Defaults to
                ``hydrogen`` for backward compatibility.
            argv: Build command to run from ``app_dir``.
            timeout_s: Wall-clock budget for the ``pnpm`` invocation.
                Defaults to :data:`_DEFAULT_TIMEOUT_S`.
            runner: Subprocess runner used to spawn ``pnpm``. Tests
                inject a stub; production callers leave the default.
        """
        self._app_dir = app_dir
        self._argv = argv
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
        """Spawn ``pnpm build`` and translate the exit code into a verdict.

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
        app_dir = ctx.artifact_dir / self._app_dir
        try:
            completed = self._runner(
                self._argv,
                cwd=app_dir,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "`pnpm build` exceeded the verifier timeout of "
                    f"{self._timeout_s:.0f}s. The bundle did not "
                    "finish."
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
                "argv": list(self._argv),
            },
        )


def _render_failure_markdown(stdout: str, stderr: str) -> str:
    """Render ``pnpm build`` failure output as feedback markdown.

    Args:
        stdout: Captured standard output from the ``pnpm`` invocation.
        stderr: Captured standard error from the ``pnpm`` invocation.

    Returns:
        Multi-line markdown body with truncated stdout/stderr blocks.
    """
    lines = ["`pnpm build` failed."]
    if stdout.strip():
        lines.extend(("", "stdout:", "```", truncate_stream(stdout.rstrip()), "```"))
    if stderr.strip():
        lines.extend(("", "stderr:", "```", truncate_stream(stderr.rstrip()), "```"))
    return "\n".join(lines)


__all__ = ["BuildVerifier"]
