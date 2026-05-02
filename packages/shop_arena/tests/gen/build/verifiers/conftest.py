"""Shared fixtures for the build-loop verifier tests.

The fixtures here are pytest-autoloaded; tests do not import them
directly. Helpers that are not stateful enough to be fixtures live as
private functions inside each test file (matching the codebase's
existing pattern under ``tests/gen/data_validation/``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from harness.plan.tasks import TaskList
from harness.runtimes.base import AgentRuntime, RuntimeIterationResult
from harness.verifiers import VerifierContext


class _StubRuntime:
    """Minimal ``AgentRuntime`` stub.

    Verifier tests never invoke ``run_iteration``; the stub exists only
    to satisfy the ``VerifierContext.runtime: AgentRuntime`` contract.
    Tests that need an :class:`~harness.runtimes.LLMCompleter` (the LLM
    verifiers under T5.5) define their own stub locally — the
    completer-shape is small enough that inlining keeps each test
    file self-contained.
    """

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Always raise — verifier tests do not exercise this path."""
        del run_dir, iter_dir, prompt, timeout
        raise AssertionError("verifier tests do not invoke run_iteration")


@pytest.fixture
def hydrogen_tree(tmp_path: Path) -> Path:
    """Return a fresh ``<tmp_path>/run/artifact/hydrogen/`` skeleton.

    The skeleton ships an empty ``app/`` subtree because every verifier
    in this package reads under ``hydrogen/app/``. Individual tests
    layer files into the tree as needed.
    """
    artifact = tmp_path / "run" / "artifact"
    hydrogen = artifact / "hydrogen"
    (hydrogen / "app").mkdir(parents=True)
    return hydrogen


@pytest.fixture
def artifact_dir(hydrogen_tree: Path) -> Path:
    """Return ``hydrogen_tree.parent`` — the verifier ``artifact_dir`` value."""
    return hydrogen_tree.parent


@pytest.fixture
def make_ctx(artifact_dir: Path) -> Callable[..., VerifierContext]:
    """Factory fixture that builds a :class:`VerifierContext`.

    The default keyword arguments target the most common verifier-test
    scenario: a ``gen_homepage`` selection with an empty plan list
    against the fixture-provided ``artifact_dir``.

    Returns:
        A callable accepting overrides for ``selected_task_id``,
        ``iter_id``, ``run_dir``, ``plan``, ``runtime``, and (rarely)
        ``artifact_dir``.
    """

    def _factory(
        *,
        selected_task_id: str = "gen_homepage",
        iter_id: str = "exec-0001",
        run_dir: Path | None = None,
        plan: TaskList | None = None,
        artifact_dir_override: Path | None = None,
        runtime: AgentRuntime | None = None,
    ) -> VerifierContext:
        artifact = artifact_dir_override if artifact_dir_override is not None else artifact_dir
        if run_dir is None:
            run_dir = artifact.parent
        if plan is None:
            plan = TaskList(tasks=())
        if runtime is None:
            runtime = _StubRuntime()
        return VerifierContext(
            run_dir=run_dir,
            iter_id=iter_id,
            selected_task_id=selected_task_id,
            plan=plan,
            artifact_dir=artifact,
            runtime=runtime,
        )

    return _factory


@pytest.fixture
def write_app_file(hydrogen_tree: Path) -> Callable[[str, str], Path]:
    """Factory fixture that writes a file under ``hydrogen/app/``.

    Returns:
        A callable ``write_app_file(relative, body)`` that writes
        ``body`` to ``hydrogen/app/<relative>`` (creating parents) and
        returns the resulting path.
    """

    def _writer(relative: str, body: str) -> Path:
        target = hydrogen_tree / "app" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return target

    return _writer
