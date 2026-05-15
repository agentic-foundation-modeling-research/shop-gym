"""Shared subprocess seam for the rule-based pnpm verifiers (spec §5.5.3).

The :class:`TscVerifier` and :class:`BuildVerifier` both shell out to
``pnpm`` against the hydrogen tree. They share two concerns:

* **Determinism in tests.** Spawning a real ``pnpm`` for unit tests is
  out of reach — the harness ships no Node toolchain. Both verifiers
  expose the same ``runner`` injection seam so tests can substitute a
  pure-Python fake without monkey-patching ``subprocess`` globally.
* **Truncation of long stderr.** ``tsc`` and ``react-router build``
  can emit megabytes of output. Pasting the full body into the next
  iteration's prompt would explode the model context. The shared
  helper trims the captured streams to a fixed budget before the
  feedback markdown is rendered.

The seam is intentionally tiny — one ``Protocol`` plus a default
implementation that calls :func:`subprocess.run` — and is consumed by
this package only. Callers outside ``build.verifiers`` should not
depend on it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

# Stream-truncation budget. Empirically large enough to capture the
# first few `tsc` errors (or the failing build's tail) without bloating
# the next iteration's prompt. Verifier feedback as a whole is further
# truncated by the harness via `verifier_feedback_max_chars` (default
# 4000); this budget keeps each captured stream comfortably under that
# ceiling so both stdout and stderr survive intact.
_STREAM_BUDGET_CHARS: Final[int] = 1500


@dataclass(frozen=True, slots=True)
class CompletedSubprocess:
    """Outcome of one :class:`SubprocessRunner` invocation.

    Attributes:
        returncode: Exit code of the spawned process. 0 means success.
        stdout: Captured stdout, decoded as UTF-8 with replacement.
        stderr: Captured stderr, decoded as UTF-8 with replacement.
    """

    returncode: int
    stdout: str
    stderr: str


@runtime_checkable
class SubprocessRunner(Protocol):
    """Callable that runs a command and captures its output.

    Production callers use :func:`default_subprocess_runner`. Tests
    inject a stub that returns a scripted :class:`CompletedSubprocess`
    so the verifier under test runs without spawning ``pnpm``.
    """

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
    ) -> CompletedSubprocess:
        """Run ``argv`` with ``cwd`` as the working directory.

        Args:
            argv: Process-spawn argument vector.
            cwd: Working directory.
            timeout: Wall-clock budget in seconds.

        Returns:
            A :class:`CompletedSubprocess` with the captured streams.

        Raises:
            subprocess.TimeoutExpired: When the command exceeds
                ``timeout``.
            FileNotFoundError: When ``argv[0]`` is not on ``PATH``.
        """
        ...


def default_subprocess_runner(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
) -> CompletedSubprocess:
    """Run ``argv`` via :func:`subprocess.run` and capture the streams.

    Decodes stdout/stderr as UTF-8 with replacement so a non-UTF-8 byte
    in the toolchain output never blocks the verifier.
    """
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return CompletedSubprocess(
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )


def truncate_stream(text: str) -> str:
    """Trim ``text`` to :data:`_STREAM_BUDGET_CHARS` characters.

    Returns the original string when it already fits the budget;
    otherwise returns the first ``_STREAM_BUDGET_CHARS`` characters
    followed by a ``[...truncated]`` suffix.
    """
    if len(text) <= _STREAM_BUDGET_CHARS:
        return text
    return text[:_STREAM_BUDGET_CHARS] + "\n[...truncated]"


__all__ = [
    "CompletedSubprocess",
    "SubprocessRunner",
    "default_subprocess_runner",
    "truncate_stream",
]
