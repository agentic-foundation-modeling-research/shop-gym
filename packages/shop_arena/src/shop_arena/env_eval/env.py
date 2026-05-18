"""``EnvEvalBrowserTask`` + ``make_env()`` BrowserGym factory (spec §5.10, M1).

EnvEval drives BrowserGym through a minimal task wrapper: one
:class:`EnvEvalBrowserTask` per run, navigates to the shop homepage during
``setup()``, exposes no validation goal. The pipeline visits subsequent
sample URLs by calling ``page.goto()`` on the same Playwright ``Page``
rather than tearing down and re-creating the env (spec §5.3, §5.10,
impl-plan M0 decision: "hold one BrowserGym env open for the whole run").

:func:`make_env` is the only call site that constructs a
``browsergym.core.env.BrowserEnv``. It returns a context manager yielding a
small :class:`EnvEvalSession` adapter that exposes the four primitives the
rest of the pipeline needs: ``goto``, ``axtree``, ``dom_object``,
``screenshot``, plus the underlying ``page`` (impl-plan M1).

Tests stub ``BrowserEnv`` and the ``extract_*`` helpers via
:func:`make_env`'s ``env_factory``/``observers`` keyword arguments so unit
tests do not launch a real Chromium process.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Protocol, cast

import playwright.sync_api
from browsergym.core.env import BrowserEnv
from browsergym.core.observation import (
    _post_extract,  # pyright: ignore[reportPrivateUsage]  # canonical mark cleanup; mirrors BrowserEnv._get_obs
    _pre_extract,  # pyright: ignore[reportPrivateUsage]  # canonical bid marker; mirrors BrowserEnv._get_obs
    extract_dom_snapshot,  # pyright: ignore[reportUnknownVariableType]  # 3p partial stub
    extract_merged_axtree,
    extract_screenshot,
)
from browsergym.core.task import AbstractBrowserTask

from shop_arena.env_eval.config import DEFAULT_VIEWPORT

__all__ = [
    "DEFAULT_NAV_TIMEOUT_MS",
    "EnvEvalBrowserTask",
    "EnvEvalSession",
    "Observers",
    "make_env",
]

logger = logging.getLogger(__name__)

#: Default per-navigation timeout (milliseconds). SandboxShops served from
#: Cloud Run can have multi-second cold starts; matches the value
#: :class:`shop_guru.eval.task.ShopGuruBrowserTask` already uses for parity.
DEFAULT_NAV_TIMEOUT_MS: int = 30_000

#: Max attempts for ``_pre_extract`` to dodge the iframe-detach race in
#: BrowserGym's ``mark_frames_recursive`` (see :func:`_pre_extract_safely`).
_PRE_EXTRACT_MAX_ATTEMPTS: Final[int] = 3

#: Settle delay between :func:`_pre_extract_safely` retries.  Real
#: storefronts mount/remove ephemeral iframes (chat widgets, ads, review
#: embeds) on a sub-second cadence; ~200 ms is enough to clear the race
#: in practice without noticeably extending the run.
_PRE_EXTRACT_RETRY_DELAY_S: Final[float] = 0.2


def _pre_extract_safely(page: playwright.sync_api.Page) -> None:
    """Call ``_pre_extract`` with retries to dodge iframe-detach races.

    BrowserGym's ``mark_frames_recursive`` reads ``frame.child_frames``,
    then for each child calls ``frame_element()``. Real storefronts
    attach/detach iframes between those two calls (chat widgets, ads,
    review embeds), and the ``frame_element()`` call raises
    ``Frame has been detached``. ``lenient=True`` only handles the
    cross-origin/no-bid branch, not this race. Re-running ``_pre_extract``
    after a brief settle clears it; the marker JS preserves bids on
    already-marked elements so retries are idempotent.
    """
    last_exc: playwright.sync_api.Error | None = None
    for attempt in range(_PRE_EXTRACT_MAX_ATTEMPTS):
        try:
            _pre_extract(page, lenient=True)
            return
        except playwright.sync_api.Error as exc:
            last_exc = exc
            logger.warning(
                "_pre_extract attempt %d/%d failed: %s",
                attempt + 1,
                _PRE_EXTRACT_MAX_ATTEMPTS,
                exc,
            )
            time.sleep(_PRE_EXTRACT_RETRY_DELAY_S)
    assert last_exc is not None
    raise last_exc


class EnvEvalBrowserTask(AbstractBrowserTask):
    """No-validation BrowserGym task that navigates to a single shop URL.

    Spec §5.10: ``EnvEvalBrowserTask(AbstractBrowserTask)`` accepts the
    shop's homepage URL, navigates to it during setup, exposes no
    validation goal, and lets BrowserGym produce the observation
    (``screenshot``, ``axtree_object``, DOM metadata, URL). The task is
    constructed **once per run**; the pipeline drives subsequent sample
    URLs by calling ``page.goto()`` on the same Playwright ``Page``.

    Attributes:
        start_url: Storefront homepage URL navigated to during ``setup``.
        viewport: Desktop viewport reported back to ``BrowserEnv`` when
            the env did not pin one. Stored as the ``{"width", "height"}``
            dict shape BrowserGym's reset code expects.
        timeout: Per-navigation timeout in milliseconds. Also propagated
            up so ``BrowserEnv`` uses it as the Playwright default.
    """

    def __init__(
        self,
        seed: int,
        *,
        start_url: str,
        viewport: tuple[int, int] = DEFAULT_VIEWPORT,
        timeout: int = DEFAULT_NAV_TIMEOUT_MS,
    ) -> None:
        super().__init__(seed)
        self.start_url = start_url
        # BrowserEnv reads these as override knobs during ``reset``; using
        # the same attribute names ShopGuru uses keeps the contract
        # explicit and consistent across the two BrowserGym callers.
        self.viewport = {"width": viewport[0], "height": viewport[1]}
        self.slow_mo = 0
        self.timeout = timeout
        self.locale: str | None = None
        self.timezone_id: str | None = None

    @classmethod
    def get_task_id(cls) -> str:
        return "shop_arena.env_eval"

    def setup(
        self,
        page: playwright.sync_api.Page,
    ) -> tuple[str, dict[str, Any]]:
        """Navigate to ``start_url`` and return an empty goal.

        EnvEval is a measurement-only task: there is no agent goal and no
        validation criterion. Returning an empty string keeps BrowserGym's
        ``goal_object`` legal while signalling "no goal".

        A navigation timeout is logged and swallowed so an unresponsive
        homepage does not abort env construction; page selection (spec
        §5.2) is responsible for translating a missing or non-2xx
        homepage into :class:`shop_arena.env_eval.errors.ShopUnreachableError`.
        """
        try:
            page.goto(self.start_url, timeout=self.timeout)
        except playwright.sync_api.TimeoutError:
            logger.warning(
                "EnvEvalBrowserTask: initial navigation to %s timed out; "
                "continuing so page selection can decide how to surface it",
                self.start_url,
            )
        return "", {"start_url": self.start_url}

    def teardown(self) -> None:
        return None

    def validate(
        self,
        page: playwright.sync_api.Page,
        chat_messages: list[str],
    ) -> tuple[float, bool, str, dict[str, Any]]:
        """Measurement-only: never terminates, never rewards.

        BrowserEnv calls ``validate`` after every step, so this must be
        cheap and side-effect-free. The ``chat_messages`` parameter mirrors
        the upstream ``AbstractBrowserTask`` signature (``list[str]``); EnvEval
        does not consume them.
        """
        del page, chat_messages
        return 0.0, False, "", {}


class Observers(Protocol):
    """Pluggable BrowserGym observers used by :class:`EnvEvalSession`.

    Tests inject a stub implementation through :func:`make_env`'s
    ``observers`` argument so they do not need a real Playwright page.
    Production code uses :data:`_DEFAULT_OBSERVERS`, which delegates to
    ``browsergym.core.observation``.
    """

    def axtree(self, page: playwright.sync_api.Page) -> dict[str, Any]: ...
    def dom_object(self, page: playwright.sync_api.Page) -> dict[str, Any]: ...
    def screenshot(self, page: playwright.sync_api.Page) -> Any: ...


@dataclass(frozen=True)
class _BrowserGymObservers:
    """Default :class:`Observers` impl backed by ``browsergym.core.observation``.

    The axtree / DOM extractors require each markable DOM element to carry
    a ``browsergym_id`` ARIA descriptor; that bid is what the action layer
    (spec §5.4) and the stateful pass (spec §5.5.2) resolve selectors
    against. ``BrowserEnv._get_obs`` plants those bids by calling
    ``_pre_extract`` before each extraction and stripping them again with
    ``_post_extract``. ``EnvEvalSession`` does not drive the env through
    ``step``/``_get_obs`` (it only navigates between sample URLs), so we
    mirror the same mark/extract/unmark cycle here per call. Without it
    every ``_node_bid(...)`` returns ``None`` and the stateful selector
    resolver (:func:`shop_arena.env_eval.transition.stateful.resolve_selector`)
    bails out with ``no_target`` for every rule.
    """

    def axtree(self, page: playwright.sync_api.Page) -> dict[str, Any]:
        # lenient=True downgrades MarkingError on un-bid-able cross-origin
        # iframes (chat/review widgets on real storefronts) to a warning so
        # measurement of the host page can still complete. Elements inside
        # those frames are unreachable to Playwright anyway under the
        # Same-Origin policy, so the action/stateful passes lose nothing.
        _pre_extract_safely(page)
        try:
            return cast(dict[str, Any], extract_merged_axtree(page))
        finally:
            _post_extract(page)

    def dom_object(self, page: playwright.sync_api.Page) -> dict[str, Any]:
        _pre_extract_safely(page)
        try:
            return cast(dict[str, Any], extract_dom_snapshot(page))
        finally:
            _post_extract(page)

    def screenshot(self, page: playwright.sync_api.Page) -> Any:
        # ``extract_screenshot`` returns an ``np.ndarray`` of shape
        # ``(H, W, 3)``. The pipeline (M1) is responsible for encoding
        # that to ``*.png`` on disk.
        return extract_screenshot(page)


_DEFAULT_OBSERVERS: Observers = _BrowserGymObservers()


@dataclass
class EnvEvalSession:
    """Adapter exposing the four BrowserGym primitives EnvEval consumes.

    The pipeline holds exactly one session per run (spec §5.3) and drives
    sample URLs through :meth:`goto`. Observation reads (:meth:`axtree`,
    :meth:`dom_object`, :meth:`screenshot`) are pulled per measured page.

    Attributes:
        env: The underlying ``browsergym.core.env.BrowserEnv``. Held so
            :func:`make_env` can call ``env.close()`` on context exit.
        observers: BrowserGym observation extractors. Replaced in tests.
        nav_count: Running tally of :meth:`goto` calls, surfaced into
            ``manifest.json`` as ``browser_navigations`` (impl-plan M1).
            The initial homepage navigation done in
            :meth:`EnvEvalBrowserTask.setup` is **not** counted here —
            the pipeline adds ``1`` for that pre-yield navigation when
            it builds the manifest.
    """

    env: Any
    observers: Observers = _DEFAULT_OBSERVERS
    nav_count: int = 0

    @property
    def page(self) -> playwright.sync_api.Page:
        """Return the active Playwright page from the BrowserGym env."""
        page = self.env.page
        if page is None:
            raise RuntimeError(
                "EnvEvalSession.page accessed before BrowserEnv.reset(); "
                "make_env() should have called reset before yielding",
            )
        return page

    def goto(
        self,
        url: str,
        *,
        timeout: int = DEFAULT_NAV_TIMEOUT_MS,
    ) -> playwright.sync_api.Response | None:
        """Navigate the open page to ``url``.

        Page selection (M1, spec §5.2) is responsible for interpreting the
        return value (``None`` ⇒ same-document nav; non-2xx ⇒ ``not_found``
        bucket; missing homepage ⇒ ``ShopUnreachableError``).
        """
        self.nav_count += 1
        return self.page.goto(url, timeout=timeout)

    def axtree(self) -> dict[str, Any]:
        """Return BrowserGym's merged accessibility tree for the active page."""
        return self.observers.axtree(self.page)

    def dom_object(self) -> dict[str, Any]:
        """Return BrowserGym's DOM snapshot (CDP ``DOMSnapshot.captureSnapshot``)."""
        return self.observers.dom_object(self.page)

    def screenshot(self) -> Any:
        """Return a full-viewport screenshot as a ``(H, W, 3)`` numpy array."""
        return self.observers.screenshot(self.page)


class _EnvFactory(Protocol):
    """Builds a ``BrowserEnv``-like object. Replaced in unit tests."""

    def __call__(
        self,
        *,
        task_entrypoint: type[AbstractBrowserTask],
        task_kwargs: dict[str, Any],
        viewport: dict[str, int],
        headless: bool,
        timeout: int,
    ) -> Any: ...


def _default_env_factory(
    *,
    task_entrypoint: type[AbstractBrowserTask],
    task_kwargs: dict[str, Any],
    viewport: dict[str, int],
    headless: bool,
    timeout: int,
) -> BrowserEnv:
    """Construct the production ``BrowserEnv``.

    Kept narrow on purpose: every BrowserEnv knob EnvEval cares about is
    surfaced as a named arg so tests can mirror the signature with a stub.
    """
    return BrowserEnv(
        task_entrypoint=task_entrypoint,
        task_kwargs=task_kwargs,
        viewport=viewport,
        headless=headless,
        timeout=timeout,
    )


@contextmanager
def make_env(
    url: str,
    *,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
    headless: bool = True,
    timeout: int = DEFAULT_NAV_TIMEOUT_MS,
    env_factory: _EnvFactory = _default_env_factory,
    observers: Observers = _DEFAULT_OBSERVERS,
) -> Generator[EnvEvalSession, None, None]:
    """Open one BrowserGym env per run and yield an :class:`EnvEvalSession`.

    Constructs an :class:`EnvEvalBrowserTask` seeded with ``url``, drives
    the env through ``reset()`` (which lands on the shop homepage), and
    yields a session adapter to the caller. The env is closed on context
    exit, even when the body raises.

    Args:
        url: Storefront homepage URL. Passed to the task as ``start_url``.
        viewport: Desktop viewport ``(width, height)``. Single viewport in
            v0.1 (spec §4.1).
        headless: Whether to run Chromium headless. Defaults to ``True``;
            tests/debug sessions can flip this off.
        timeout: Per-navigation timeout in milliseconds.
        env_factory: Hook for tests; defaults to a real ``BrowserEnv``.
        observers: BrowserGym observation extractors; defaults to
            ``browsergym.core.observation``.

    Yields:
        :class:`EnvEvalSession` exposing ``goto/axtree/dom_object/screenshot/page``.
    """
    env = env_factory(
        task_entrypoint=EnvEvalBrowserTask,
        task_kwargs={
            "start_url": url,
            "viewport": viewport,
            "timeout": timeout,
        },
        viewport={"width": viewport[0], "height": viewport[1]},
        headless=headless,
        timeout=timeout,
    )
    try:
        env.reset()
        yield EnvEvalSession(env=env, observers=observers)
    finally:
        env.close()
