"""Tests for `harness.runtimes.get_runtime` registry.

Covers the T2.2 contract: unknown names raise `ValueError`, and the
`replay` runtime (registered in T2.2) constructs successfully now
that T2.3 has landed `ReplayRuntime`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.runtimes import AgentRuntime, get_runtime, validate_model_grammar
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


# --------------------------------------------------------------------------- #
# validate_model_grammar
# --------------------------------------------------------------------------- #


def test_validate_model_grammar_accepts_none_for_any_runtime() -> None:
    """``model=None`` always validates (means "use the runtime's own default")."""
    validate_model_grammar(None, "pi")
    validate_model_grammar(None, "claude_code")
    validate_model_grammar(None, "replay")


def test_validate_model_grammar_rejects_provider_prefix_for_claude_code() -> None:
    """The `claude` CLI rejects ``anthropic/foo``; surface that at config time."""
    with pytest.raises(ValueError, match="provider-prefixed"):
        validate_model_grammar("anthropic/claude-opus-4-7", "claude_code")


def test_validate_model_grammar_error_suggests_bare_form() -> None:
    """The error message includes the prefix-stripped suggestion."""
    with pytest.raises(ValueError, match="claude-opus-4-7"):
        validate_model_grammar("anthropic/claude-opus-4-7", "claude_code")


def test_validate_model_grammar_accepts_provider_prefix_for_pi() -> None:
    """Provider-prefixed IDs are valid pi grammar; do not reject."""
    validate_model_grammar("anthropic/claude-opus-4-7", "pi")


def test_validate_model_grammar_accepts_claude_code_aliases() -> None:
    """Bare aliases like ``opus`` are valid `claude` CLI grammar."""
    validate_model_grammar("opus", "claude_code")
    validate_model_grammar("claude-opus-4-5", "claude_code")
