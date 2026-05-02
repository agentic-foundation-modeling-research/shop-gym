"""Playwright orchestration for ShopProbe v1.0.

The runner owns Chromium's lifecycle so callers (capture/bundle.py and
transition/) only see a fresh :class:`Page` per call. Every page runs in:

* an **isolated** browser context (one per call, discarded after);
* a **fixed viewport** of ``(1280, 800)`` CSS pixels;
* a **pinned user agent** advertising ``ShopProbe/<version>``;
* **headless** Chromium;
* a **hard timeout** of 15 s by default, configurable per-call.

This module performs no I/O at import time: launching Playwright happens
inside :meth:`PlaywrightRunner.__aenter__`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Final, TypeVar

from playwright.async_api import Browser, Page, async_playwright

from shop_arena.probe import __version__ as _shop_probe_version

PINNED_USER_AGENT: Final[str] = (
    f"Mozilla/5.0 (compatible; ShopProbe/{_shop_probe_version}; "
    "+https://github.com/oss/shop-gym) Chromium HeadlessChrome"
)
"""UA string the runner advertises. Mirrors a real browser prefix so
storefronts that gate on ``Mozilla/5.0`` still serve their normal HTML."""

VIEWPORT_WIDTH: Final[int] = 1280
"""Fixed viewport width in CSS pixels."""

VIEWPORT_HEIGHT: Final[int] = 800
"""Fixed viewport height in CSS pixels."""

DEFAULT_PAGE_TIMEOUT_S: Final[float] = 15.0
"""Hard per-call timeout in seconds."""


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PageOutcome:
    """Wrapper recording the wall-clock duration of one runner call."""

    duration_ms: int


class PlaywrightRunner:
    """Async-context-managed Chromium lifecycle.

    Use as ``async with PlaywrightRunner() as runner: ...``. Each
    :meth:`run` call opens an isolated browser context, hands the
    callable a fresh :class:`Page`, enforces ``timeout_s`` (default 15 s),
    and disposes the context on exit. The callable returns whatever it
    likes; the runner times the call and returns ``(value, PageOutcome)``.
    """

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_PAGE_TIMEOUT_S,
        user_agent: str = PINNED_USER_AGENT,
        viewport: tuple[int, int] = (VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
        headless: bool = True,
    ) -> None:
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self.viewport = viewport
        self.headless = headless
        self._stack: contextlib.AsyncExitStack | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> PlaywrightRunner:
        stack = contextlib.AsyncExitStack()
        await stack.__aenter__()
        try:
            playwright = await stack.enter_async_context(async_playwright())
            browser = await playwright.chromium.launch(headless=self.headless)
            stack.push_async_callback(browser.close)
        except BaseException:
            await stack.aclose()
            raise
        self._browser = browser
        self._stack = stack
        return self

    @property
    def browser(self) -> Browser:
        if self._browser is None:
            msg = "PlaywrightRunner must be used as an async context manager"
            raise RuntimeError(msg)
        return self._browser

    @property
    def chromium_version(self) -> str:
        return self.browser.version

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        stack, self._stack = self._stack, None
        self._browser = None
        if stack is not None:
            await stack.__aexit__(exc_type, exc, tb)

    async def run(
        self,
        fn: Callable[[Page], Awaitable[T]],
        *,
        timeout_s: float | None = None,
    ) -> tuple[T, PageOutcome]:
        """Run ``fn`` inside a fresh isolated context and time the call.

        Args:
            fn: Coroutine taking a :class:`Page` and returning a value.
            timeout_s: Override the runner's default timeout for this
                call only.

        Returns:
            ``(value, PageOutcome)``. ``PageOutcome.duration_ms`` is wall-
            clock from context creation through ``fn`` completion.

        Raises:
            RuntimeError: If called outside the ``async with`` block.
            TimeoutError: When ``fn`` exceeds ``timeout_s``.
        """
        if self._browser is None:
            msg = "PlaywrightRunner must be used as an async context manager"
            raise RuntimeError(msg)
        budget = timeout_s if timeout_s is not None else self.timeout_s
        start = time.perf_counter()
        context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
        )
        try:
            page = await context.new_page()
            page.set_default_timeout(budget * 1000.0)
            value = await asyncio.wait_for(fn(page), timeout=budget)
        finally:
            await context.close()
        duration_ms = int((time.perf_counter() - start) * 1000)
        return value, PageOutcome(duration_ms=duration_ms)
