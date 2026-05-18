"""Shared fixtures for ``shop_arena.env_eval`` tests.

The single fixture below auto-disables :func:`wait_for_axtree_settle` for
every test in this directory.  Production callers (``execute_rule``,
``_capture_url_node_artifact``) use the helper to wait for delayed DOM
mutations (setTimeout popups, fade-in animations) before snapshotting.
That polling is correct in production but wasteful in unit tests, where
fakes return synthetic axtrees that never mutate; without the fixture
each settle call would block for ``DEFAULT_AXTREE_STABLE_MS`` (≈800 ms)
times the number of URL-node captures the test exercises.

Tests that want to exercise the real settle behaviour import the
function directly under a different alias before the fixture runs (see
``test_transition_stateful.py::test_wait_for_axtree_settle_*``); the
direct binding is captured at module import and is unaffected by the
``monkeypatch.setattr`` calls below.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_axtree_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace :func:`wait_for_axtree_settle` with a no-op for all env_eval tests."""

    def _noop(**_kwargs: object) -> None:
        return None

    # Patch both bindings: the canonical definition in stateful, and the
    # eager re-export in pipeline (``from ... import wait_for_axtree_settle``).
    monkeypatch.setattr(
        "shop_arena.env_eval.transition.stateful.wait_for_axtree_settle",
        _noop,
    )
    monkeypatch.setattr(
        "shop_arena.env_eval.pipeline.wait_for_axtree_settle",
        _noop,
    )
