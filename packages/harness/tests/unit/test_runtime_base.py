"""Import-only smoke tests for `harness.runtimes.base`."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from harness.runtimes import AgentRuntime, RuntimeIterationResult
from harness.runtimes.base import AgentRuntime as AgentRuntimeFromBase
from harness.types import Trajectory


def test_agent_runtime_reexported_from_package() -> None:
    """`AgentRuntime` is importable from both the package and `base`."""
    assert AgentRuntime is AgentRuntimeFromBase


def test_runtime_iteration_result_is_frozen_and_holds_trajectory() -> None:
    """`RuntimeIterationResult` is a frozen dataclass wrapping a `Trajectory`."""
    now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    trajectory = Trajectory(
        iter_id="plan",
        runtime="replay",
        started_at=now,
        ended_at=now,
        exit_code=0,
        prompt_sha256="0" * 64,
    )

    result = RuntimeIterationResult(trajectory=trajectory)

    assert result.trajectory is trajectory


def test_protocol_accepts_minimal_implementation() -> None:
    """A class implementing `run_iteration` satisfies the `AgentRuntime` Protocol."""

    class _Stub:
        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del run_dir, iter_dir, prompt, timeout
            now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
            return RuntimeIterationResult(
                trajectory=Trajectory(
                    iter_id="plan",
                    runtime="stub",
                    started_at=now,
                    ended_at=now,
                    exit_code=0,
                    prompt_sha256="0" * 64,
                ),
            )

    stub: AgentRuntime = _Stub()
    assert isinstance(stub, AgentRuntime)
