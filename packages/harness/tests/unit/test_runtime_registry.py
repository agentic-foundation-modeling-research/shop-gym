"""Tests for `harness.runtimes.get_runtime` registry.

Covers the T2.2 contract: unknown names raise `ValueError`, and the
`replay` runtime is registered (its module-level resolution lands in
T2.3).
"""

from __future__ import annotations

import pytest

from harness.runtimes import get_runtime


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


def test_get_runtime_replay_lookup_passes_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Looking up ``replay`` must reach the import step, not error in the registry.

    Until T2.3 lands the import itself will fail with `ModuleNotFoundError`;
    that is fine — it proves the registry resolved the name correctly.
    Once T2.3 lands, this test should be replaced with a real construction
    assertion.
    """
    del monkeypatch  # reserved for the post-T2.3 rewrite
    with pytest.raises((ModuleNotFoundError, ImportError)):
        get_runtime("replay")
