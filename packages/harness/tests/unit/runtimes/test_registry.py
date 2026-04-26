"""Tests for `harness.runtimes.get_runtime` registry.

Covers the T2.2 contract: unknown names raise `ValueError`, and the
`replay` runtime (registered in T2.2) constructs successfully now
that T2.3 has landed `ReplayRuntime`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.runtimes import AgentRuntime, get_runtime
from harness.runtimes.replay import ReplayRuntime


def test_get_runtime_unknown_name_raises_value_error() -> None:
    """An unregistered name surfaces as `ValueError`, not `KeyError`."""
    with pytest.raises(ValueError, match="Unknown runtime 'nope'"):
        get_runtime("nope")


def test_get_runtime_value_error_lists_known_names() -> None:
    """The error message exposes registered names so the caller can fix.

    Also doubles as a registration smoke test: ``replay`` must appear in
    the listing even before its implementation module exists (T2.3).
    """
    with pytest.raises(ValueError, match="replay"):
        get_runtime("does_not_exist")


def test_get_runtime_replay_returns_replay_runtime(tmp_path: Path) -> None:
    """Looking up ``replay`` constructs a `ReplayRuntime` via the registry."""
    runtime = get_runtime("replay", scenario_dir=tmp_path)

    assert isinstance(runtime, ReplayRuntime)
    assert isinstance(runtime, AgentRuntime)
    assert runtime.scenario_dir == tmp_path
    assert runtime.fallback is None
