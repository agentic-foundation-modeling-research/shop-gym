"""Unit tests for ``shop_arena.env_eval.env`` (impl plan M1).

Covers the contract documented in spec §5.10:

* :class:`EnvEvalBrowserTask` navigates to the shop homepage during
  ``setup``, exposes no validation goal, and propagates the timeout/viewport
  knobs BrowserGym reads during ``reset``.
* :func:`make_env` constructs **one** BrowserEnv per run, drives it through
  ``reset``, yields an :class:`EnvEvalSession` exposing
  ``goto/axtree/dom_object/screenshot/page``, and always closes the env on
  context exit (even when the body raises).

Tests use a stub env factory + stub observers so no real Chromium is
launched.
"""

from __future__ import annotations

from typing import Any

import playwright.sync_api
import pytest

from shop_arena.env_eval.config import DEFAULT_VIEWPORT
from shop_arena.env_eval.env import (
    DEFAULT_NAV_TIMEOUT_MS,
    EnvEvalBrowserTask,
    EnvEvalSession,
    make_env,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakePage:
    """Minimal stand-in for ``playwright.sync_api.Page``."""

    def __init__(
        self,
        *,
        goto_raises: type[BaseException] | None = None,
    ) -> None:
        self.goto_calls: list[tuple[str, int | None]] = []
        self._goto_raises = goto_raises

    def goto(
        self,
        url: str,
        *,
        timeout: int | None = None,
    ) -> Any:
        self.goto_calls.append((url, timeout))
        if self._goto_raises is not None:
            raise self._goto_raises("simulated timeout")
        return None


class _FakeEnv:
    """Stand-in for ``browsergym.core.env.BrowserEnv``."""

    def __init__(self, *, page: _FakePage | None = None) -> None:
        self.page: _FakePage | None = page
        self.reset_called = 0
        self.close_called = 0

    def reset(self) -> None:
        self.reset_called += 1

    def close(self) -> None:
        self.close_called += 1


class _RecordingObservers:
    """Records calls so tests can assert ``axtree/dom_object/screenshot`` wiring."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, _FakePage]] = []

    def axtree(self, page: _FakePage) -> dict[str, Any]:  # type: ignore[override]
        self.calls.append(("axtree", page))
        return {"role": "WebArea"}

    def dom_object(self, page: _FakePage) -> dict[str, Any]:  # type: ignore[override]
        self.calls.append(("dom_object", page))
        return {"documents": []}

    def screenshot(self, page: _FakePage) -> bytes:  # type: ignore[override]
        self.calls.append(("screenshot", page))
        return b"\x89PNG"


# ---------------------------------------------------------------------------
# EnvEvalBrowserTask
# ---------------------------------------------------------------------------


def test_task_setup_navigates_to_start_url() -> None:
    """``setup`` issues ``page.goto(start_url, timeout=task.timeout)``."""
    task = EnvEvalBrowserTask(
        seed=0,
        start_url="https://example-shop.com",
        timeout=12345,
    )
    page = _FakePage()

    goal, info = task.setup(page)  # type: ignore[arg-type]

    assert goal == ""
    assert info == {"start_url": "https://example-shop.com"}
    assert page.goto_calls == [("https://example-shop.com", 12345)]


def test_task_setup_swallows_navigation_timeout() -> None:
    """A Playwright ``TimeoutError`` is logged and absorbed (page selection decides)."""
    task = EnvEvalBrowserTask(seed=0, start_url="https://slow.example")
    page = _FakePage(goto_raises=playwright.sync_api.TimeoutError)

    goal, info = task.setup(page)  # type: ignore[arg-type]

    assert goal == ""
    assert info["start_url"] == "https://slow.example"
    assert page.goto_calls == [("https://slow.example", DEFAULT_NAV_TIMEOUT_MS)]


def test_task_validate_is_measurement_only() -> None:
    """``validate`` always returns the no-op tuple — EnvEval has no agent goal."""
    task = EnvEvalBrowserTask(seed=0, start_url="https://example-shop.com")

    reward, done, message, info = task.validate(_FakePage(), [])  # type: ignore[arg-type]

    assert reward == 0.0
    assert done is False
    assert message == ""
    assert info == {}


def test_task_exposes_browsergym_override_attributes() -> None:
    """``BrowserEnv.reset`` reads ``viewport``/``slow_mo``/``timeout`` off the task."""
    task = EnvEvalBrowserTask(
        seed=0,
        start_url="https://example-shop.com",
        viewport=(1280, 720),
        timeout=15_000,
    )

    assert task.viewport == {"width": 1280, "height": 720}
    assert task.slow_mo == 0
    assert task.timeout == 15_000
    # Locale/timezone are unset so BrowserEnv keeps its defaults.
    assert task.locale is None
    assert task.timezone_id is None


def test_task_id_is_namespaced_to_env_eval() -> None:
    """The task id should not collide with ShopGuru's task id."""
    assert EnvEvalBrowserTask.get_task_id() == "shop_arena.env_eval"


# ---------------------------------------------------------------------------
# EnvEvalSession
# ---------------------------------------------------------------------------


def test_session_page_property_returns_underlying_page() -> None:
    page = _FakePage()
    session = EnvEvalSession(env=_FakeEnv(page=page), observers=_RecordingObservers())

    assert session.page is page


def test_session_page_raises_when_env_not_reset() -> None:
    """A pre-reset BrowserEnv has ``page == None``; surface that loudly."""
    session = EnvEvalSession(env=_FakeEnv(page=None), observers=_RecordingObservers())

    with pytest.raises(RuntimeError, match="reset"):
        _ = session.page


def test_session_goto_delegates_to_page() -> None:
    page = _FakePage()
    session = EnvEvalSession(env=_FakeEnv(page=page), observers=_RecordingObservers())

    session.goto("https://example-shop.com/cart", timeout=5_000)

    assert page.goto_calls == [("https://example-shop.com/cart", 5_000)]


def test_session_observation_methods_call_observers_with_page() -> None:
    page = _FakePage()
    observers = _RecordingObservers()
    session = EnvEvalSession(env=_FakeEnv(page=page), observers=observers)

    assert session.axtree() == {"role": "WebArea"}
    assert session.dom_object() == {"documents": []}
    assert session.screenshot() == b"\x89PNG"
    # Each observer received the same Playwright page object.
    assert observers.calls == [
        ("axtree", page),
        ("dom_object", page),
        ("screenshot", page),
    ]


# ---------------------------------------------------------------------------
# make_env
# ---------------------------------------------------------------------------


def _build_factory(env: _FakeEnv) -> tuple[Any, dict[str, Any]]:
    """Return an ``env_factory`` recording the kwargs ``make_env`` passed."""
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _FakeEnv:
        captured.update(kwargs)
        return env

    return factory, captured


def test_make_env_resets_then_yields_session_then_closes() -> None:
    """Lifecycle: ``reset`` → yield → ``close`` (even when body raises)."""
    page = _FakePage()
    env = _FakeEnv(page=page)
    factory, captured = _build_factory(env)
    observers = _RecordingObservers()

    with make_env(
        "https://example-shop.com",
        env_factory=factory,
        observers=observers,
    ) as session:
        assert isinstance(session, EnvEvalSession)
        assert session.env is env
        assert session.observers is observers
        assert env.reset_called == 1
        assert env.close_called == 0
        # Observation primitives are wired to the same page.
        session.axtree()

    assert env.close_called == 1
    assert observers.calls == [("axtree", page)]
    # Factory wiring: BrowserGym task + viewport/headless/timeout knobs.
    assert captured["task_entrypoint"] is EnvEvalBrowserTask
    assert captured["task_kwargs"] == {
        "start_url": "https://example-shop.com",
        "viewport": DEFAULT_VIEWPORT,
        "timeout": DEFAULT_NAV_TIMEOUT_MS,
    }
    assert captured["viewport"] == {"width": 1440, "height": 900}
    assert captured["headless"] is True
    assert captured["timeout"] == DEFAULT_NAV_TIMEOUT_MS


def test_make_env_closes_env_on_exception() -> None:
    """If the with-body raises, the env is still closed (cleanup invariant)."""
    env = _FakeEnv(page=_FakePage())
    factory, _ = _build_factory(env)

    class _BoomError(RuntimeError):
        pass

    with (
        pytest.raises(_BoomError),
        make_env(
            "https://example-shop.com",
            env_factory=factory,
            observers=_RecordingObservers(),
        ),
    ):
        raise _BoomError("inside body")

    assert env.reset_called == 1
    assert env.close_called == 1


def test_make_env_threads_viewport_and_headless_into_factory() -> None:
    env = _FakeEnv(page=_FakePage())
    factory, captured = _build_factory(env)

    with make_env(
        "https://example-shop.com",
        viewport=(1280, 720),
        headless=False,
        timeout=9_000,
        env_factory=factory,
        observers=_RecordingObservers(),
    ):
        pass

    assert captured["task_kwargs"]["viewport"] == (1280, 720)
    assert captured["task_kwargs"]["timeout"] == 9_000
    assert captured["viewport"] == {"width": 1280, "height": 720}
    assert captured["headless"] is False
    assert captured["timeout"] == 9_000
