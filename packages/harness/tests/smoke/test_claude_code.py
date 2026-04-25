"""Live-CLI smoke test for `ClaudeCodeRuntime` (impl plan T3.4).

Skipped unless ``HARNESS_SMOKE_CLAUDE=1`` is set in the environment.
When enabled, the test drives the toy scenario through the real
``claude`` binary and asserts the run terminates with both toy tasks
done and the trajectories carry the cassette's step kinds.

These tests detect cassette drift: when the CLI's stream-json contract
or the planner/executor prompts diverge from the recorded cassette,
this test catches it before users do.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.runtimes import get_runtime
from tests.smoke._toy_scenario import (
    assert_step_kinds_within_tolerance,
    assert_toy_run_succeeded,
    run_toy_scenario,
)

_SMOKE_ENV_VAR = "HARNESS_SMOKE_CLAUDE"
_LIVE_TIMEOUT_SECONDS = 300.0


@pytest.mark.smoke
@pytest.mark.skipif(
    os.environ.get(_SMOKE_ENV_VAR) != "1",
    reason=f"{_SMOKE_ENV_VAR}!=1; live-CLI smoke test skipped",
)
def test_claude_code_toy_scenario_live(tmp_path: Path) -> None:
    """Run the toy scenario against the real ``claude`` CLI."""
    runtime = get_runtime("claude_code")
    result = run_toy_scenario(
        runtime,
        run_dir=tmp_path / "run",
        timeout=_LIVE_TIMEOUT_SECONDS,
    )
    assert_toy_run_succeeded(result)
    assert_step_kinds_within_tolerance(result.run_dir)
