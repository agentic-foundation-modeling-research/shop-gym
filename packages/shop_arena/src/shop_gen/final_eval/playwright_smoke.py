"""Playwright smoke runner for the Phase 5 ``final_eval`` step (spec §5.5.5, T6.1).

Drives the spec-mandated post-build smoke flow against a freshly built
hydrogen tree:

1. Boot the dev server (delegated to :class:`DevServerFactory`).
2. Walk the canonical flow — home → collection → product → add-to-cart
   → checkout-redirect — at every configured viewport.
3. Capture screenshots at each step under
   ``<out_dir>/runs/build/final_eval/screenshots/``.

The actual browser automation is delegated to a :class:`BrowserDriver`
seam: production callers inject a Playwright-backed driver (lands with
T6.2 / T6.3 alongside the LLM judge and ``final_eval`` step), tests
inject a stub that records the calls and writes deterministic stand-in
screenshot bytes. This mirrors the pattern
:class:`shop_gen.build.verifiers.routes_200.Routes200Verifier` uses for
its own dev-server seam: the smoke logic stays
test-deterministic without pulling Playwright into ``shop_arena``'s
runtime dependency set ahead of T6.3.

The module also owns:

* :func:`resolve_smoke_flow` — read the published ``data/products.json``
  and ``data/collections.json`` and synthesise the canonical flow with
  real handles, so the resolved URLs are renderable by the dev server.
* :func:`run_playwright_smoke` — top-level entrypoint that the eventual
  ``final_eval`` step (T6.3) calls into. Returns a :class:`SmokeReport`
  the caller can persist into ``final_eval.json`` alongside the LLM
  judge verdict.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, cast, runtime_checkable

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #


_PRODUCTS_FILE: Final[Path] = Path("data") / "products.json"
"""Run-relative path to the published product catalogue."""

_COLLECTIONS_FILE: Final[Path] = Path("data") / "collections.json"
"""Run-relative path to the published collection catalogue."""

_HOME_PATH: Final[str] = "/"
"""Canonical home-page URL the smoke flow opens first."""

_CART_PATH: Final[str] = "/cart"
"""Canonical cart URL used as the checkout-redirect step's seed."""

_ADD_TO_CART_SELECTOR: Final[str] = "button[name='add'], button[data-testid='add-to-cart']"
"""Selector list the browser driver clicks to trigger an add-to-cart action."""

_CHECKOUT_SELECTOR: Final[str] = "a[href*='checkout'], button[name='checkout']"
"""Selector list the browser driver clicks to trigger the checkout redirect."""

_FALLBACK_PRODUCT_HANDLE: Final[str] = "placeholder-product"
"""Used when ``products.json`` is missing or empty (defensive — Phase 2 fills it)."""

_FALLBACK_COLLECTION_HANDLE: Final[str] = "placeholder-collection"
"""Used when ``collections.json`` is missing or empty (defensive — Phase 2 fills it)."""


# --------------------------------------------------------------------------- #
# Value types
# --------------------------------------------------------------------------- #


class SmokeAction(enum.Enum):
    """Post-navigation action a smoke step may trigger.

    Members:
        NONE: Open the URL and capture the screenshot.
        ADD_TO_CART: Open the URL, click the add-to-cart button, then
            capture the post-action screenshot.
        CHECKOUT_REDIRECT: Open the URL, click the checkout button,
            capture both the pre-redirect screenshot and the URL the
            browser landed on.
    """

    NONE = "none"
    ADD_TO_CART = "add_to_cart"
    CHECKOUT_REDIRECT = "checkout_redirect"


@dataclass(frozen=True, slots=True)
class Viewport:
    """One viewport the smoke flow captures screenshots at.

    Attributes:
        name: Filesystem-safe label embedded in screenshot filenames
            (e.g. ``"desktop"``, ``"mobile"``).
        width: CSS pixel width.
        height: CSS pixel height.
    """

    name: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class SmokeStep:
    """One step in the smoke flow.

    Attributes:
        name: Filesystem-safe label embedded in screenshot filenames
            (e.g. ``"home"``, ``"collection"``, ``"product"``).
        url: URL path (starts with ``/``) the driver navigates to.
        action: Post-navigation action. ``NONE`` for plain page loads;
            ``ADD_TO_CART`` clicks the add-to-cart button on a product
            page; ``CHECKOUT_REDIRECT`` clicks the checkout button on
            the cart page.
        selector: CSS selector list passed to the browser driver when
            ``action`` is non-``NONE``. ``None`` for plain navigation
            steps.
    """

    name: str
    url: str
    action: SmokeAction = SmokeAction.NONE
    selector: str | None = None


@dataclass(frozen=True, slots=True)
class SmokeFlow:
    """Resolved smoke-flow definition.

    A :class:`SmokeFlow` is the immutable contract the
    :class:`BrowserDriver` walks: for every step / viewport pair the
    driver attempts navigation + the optional post-action and reports a
    :class:`Screenshot` (success) or a :class:`SmokeFailure`.

    Attributes:
        steps: Ordered tuple of smoke steps. Walked in order; a failure
            on one step does not abort the flow — the driver records a
            :class:`SmokeFailure` and continues.
        viewports: Viewports each step is repeated against.
    """

    steps: tuple[SmokeStep, ...]
    viewports: tuple[Viewport, ...]


@dataclass(frozen=True, slots=True)
class Screenshot:
    """Successful screenshot recorded by the browser driver.

    Attributes:
        step: Originating :attr:`SmokeStep.name`.
        viewport: Originating :attr:`Viewport.name`.
        path: Absolute path the screenshot was written to.
        url: Final URL the browser landed on (after any redirect or
            post-action navigation). Equals :attr:`SmokeStep.url` for
            plain navigation steps; differs for
            :data:`SmokeAction.CHECKOUT_REDIRECT`.
    """

    step: str
    viewport: str
    path: Path
    url: str


@dataclass(frozen=True, slots=True)
class SmokeFailure:
    """Failure recorded by the browser driver for one (step, viewport) pair.

    Attributes:
        step: Originating :attr:`SmokeStep.name`.
        viewport: Originating :attr:`Viewport.name`.
        error: Human-readable failure description (driver-supplied).
    """

    step: str
    viewport: str
    error: str


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """Aggregated smoke-flow result the ``final_eval`` step persists.

    The report is **advisory** — spec §5.5.5: a passing build harness
    loop is the gating signal; final eval surfaces issues for human
    review.

    Attributes:
        base_url: Base URL the dev server was reachable at during the
            run (``http://127.0.0.1:<port>``).
        flow: Smoke flow that was walked.
        screenshots: One entry per successfully captured (step,
            viewport) pair.
        failures: One entry per (step, viewport) pair the driver could
            not capture. Empty on a clean run.
    """

    base_url: str
    flow: SmokeFlow
    screenshots: tuple[Screenshot, ...] = field(default_factory=tuple)
    failures: tuple[SmokeFailure, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Return ``True`` iff every (step, viewport) pair produced a screenshot."""
        return not self.failures


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #


DEFAULT_VIEWPORTS: Final[tuple[Viewport, ...]] = (
    Viewport(name="desktop", width=1280, height=800),
    Viewport(name="mobile", width=375, height=667),
)
"""Spec §5.5.5 viewport set: one desktop, one mobile."""


DEFAULT_SMOKE_FLOW: Final[tuple[SmokeStep, ...]] = (
    SmokeStep(name="home", url=_HOME_PATH),
    SmokeStep(
        name="collection",
        url=f"/collections/{_FALLBACK_COLLECTION_HANDLE}",
    ),
    SmokeStep(
        name="product",
        url=f"/products/{_FALLBACK_PRODUCT_HANDLE}",
    ),
    SmokeStep(
        name="add_to_cart",
        url=f"/products/{_FALLBACK_PRODUCT_HANDLE}",
        action=SmokeAction.ADD_TO_CART,
        selector=_ADD_TO_CART_SELECTOR,
    ),
    SmokeStep(
        name="checkout_redirect",
        url=_CART_PATH,
        action=SmokeAction.CHECKOUT_REDIRECT,
        selector=_CHECKOUT_SELECTOR,
    ),
)
"""Canonical smoke-flow shape (spec §5.5.5).

The product / collection URLs use placeholder handles; production
callers should resolve real handles via :func:`resolve_smoke_flow`.
"""


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


@runtime_checkable
class DevServerFactory(Protocol):
    """Boots a transient hydrogen dev server, yields its base URL.

    The returned context manager owns the subprocess lifecycle: it
    starts the server on entry, yields ``http://127.0.0.1:<port>`` once
    the server is reachable, and tears the process down on exit
    (including on exception).

    Mirrors :class:`shop_gen.build.verifiers.routes_200.DevServerFactory`
    so the same factory can be reused for both verifiers and final
    eval. Production wiring (a ``pnpm dev`` driver) lands with the
    ``final_eval`` step in T6.3; v0.1 callers (and tests) inject a
    factory of their choice.
    """

    def __call__(self, hydrogen_dir: Path) -> AbstractContextManager[str]:
        """Start a dev server bound to ``hydrogen_dir`` and yield its base URL.

        Args:
            hydrogen_dir: Filesystem path the dev server should be
                rooted at (typically the freshly built hydrogen tree).

        Returns:
            A context manager whose ``__enter__`` returns
            ``"http://127.0.0.1:<port>"``.
        """
        ...


@runtime_checkable
class BrowserDriver(Protocol):
    """Drives one smoke flow against ``base_url`` and writes screenshots.

    Production drivers wrap Playwright: they spawn a browser context
    per viewport, navigate to each step's URL, run the post-action (if
    any), capture a PNG into ``screenshots_dir``, and return the
    aggregated tuples.

    Tests inject stubs that fabricate deterministic stand-in
    screenshots so the smoke runner can be exercised without pulling
    Playwright into the test runtime.
    """

    def __call__(
        self,
        *,
        base_url: str,
        flow: SmokeFlow,
        screenshots_dir: Path,
    ) -> tuple[tuple[Screenshot, ...], tuple[SmokeFailure, ...]]:
        """Walk ``flow`` against ``base_url`` and persist screenshots.

        Args:
            base_url: Base URL the dev server is reachable at
                (``http://127.0.0.1:<port>``).
            flow: Smoke flow to walk.
            screenshots_dir: Directory the driver writes screenshots
                under. The runner pre-creates it.

        Returns:
            ``(screenshots, failures)`` — one tuple of successful
            screenshots and one tuple of failures. The driver should
            attempt every (step, viewport) pair before returning.
        """
        ...


# --------------------------------------------------------------------------- #
# Flow resolution
# --------------------------------------------------------------------------- #


def resolve_smoke_flow(
    *,
    out_dir: Path,
    viewports: Sequence[Viewport] = DEFAULT_VIEWPORTS,
) -> SmokeFlow:
    """Build the canonical smoke flow with real handles from ``out_dir``.

    Reads the first handle from ``<out_dir>/data/products.json`` and
    ``<out_dir>/data/collections.json`` and substitutes them into the
    canonical flow's product / collection / add-to-cart URLs. A missing
    or empty file falls back to a deterministic placeholder so the flow
    is still well-formed; the BrowserDriver will report a navigation
    failure against the dev server in that case, which is the desired
    advisory signal.

    Args:
        out_dir: Run workspace (``<out_dir>/data/`` is read).
        viewports: Viewports to capture each step at. Defaults to
            :data:`DEFAULT_VIEWPORTS`.

    Returns:
        Resolved :class:`SmokeFlow` ready to hand to a
        :class:`BrowserDriver`.
    """
    product_handle = _read_first_handle(
        path=out_dir / _PRODUCTS_FILE,
        fallback=_FALLBACK_PRODUCT_HANDLE,
    )
    collection_handle = _read_first_handle(
        path=out_dir / _COLLECTIONS_FILE,
        fallback=_FALLBACK_COLLECTION_HANDLE,
    )
    steps: tuple[SmokeStep, ...] = (
        SmokeStep(name="home", url=_HOME_PATH),
        SmokeStep(
            name="collection",
            url=f"/collections/{collection_handle}",
        ),
        SmokeStep(
            name="product",
            url=f"/products/{product_handle}",
        ),
        SmokeStep(
            name="add_to_cart",
            url=f"/products/{product_handle}",
            action=SmokeAction.ADD_TO_CART,
            selector=_ADD_TO_CART_SELECTOR,
        ),
        SmokeStep(
            name="checkout_redirect",
            url=_CART_PATH,
            action=SmokeAction.CHECKOUT_REDIRECT,
            selector=_CHECKOUT_SELECTOR,
        ),
    )
    return SmokeFlow(steps=steps, viewports=tuple(viewports))


# --------------------------------------------------------------------------- #
# Top-level entrypoint
# --------------------------------------------------------------------------- #


def run_playwright_smoke(
    *,
    hydrogen_dir: Path,
    screenshots_dir: Path,
    flow: SmokeFlow,
    dev_server_factory: DevServerFactory,
    browser_driver: BrowserDriver,
) -> SmokeReport:
    """Run the smoke flow end-to-end and return the aggregated report.

    Lifecycle:

    1. Validate ``hydrogen_dir`` exists (the cloned-then-built tree
       from Phase 4).
    2. Pre-create ``screenshots_dir`` so the driver can write into it
       without further mkdir plumbing.
    3. Enter ``dev_server_factory(hydrogen_dir)`` — production callers
       boot ``pnpm dev``; tests boot an in-process HTTP server.
    4. Hand the live ``base_url`` + ``flow`` + ``screenshots_dir`` to
       ``browser_driver``.
    5. On context exit the dev server is torn down; the report is
       returned regardless of whether the driver recorded failures
       (final eval is advisory per spec §5.5.5).

    Args:
        hydrogen_dir: Built hydrogen tree the dev server runs against.
        screenshots_dir: Directory screenshots are written under. The
            runner pre-creates it.
        flow: Smoke flow to walk. Production callers obtain it from
            :func:`resolve_smoke_flow`.
        dev_server_factory: Callable that boots the dev server.
        browser_driver: Callable that drives the browser.

    Returns:
        :class:`SmokeReport` — never raises on driver failures; the
        report's :attr:`SmokeReport.failures` captures them so the
        ``final_eval`` step (T6.3) can persist them as advisory
        signals.

    Raises:
        FileNotFoundError: ``hydrogen_dir`` does not exist (Phase 4
            never produced a tree to evaluate against).
        Exception: Any exception raised by ``dev_server_factory`` while
            booting the server propagates to the caller; cleanup runs
            via the context manager's ``__exit__``.
    """
    if not hydrogen_dir.is_dir():
        raise FileNotFoundError(
            f"hydrogen tree not found at {hydrogen_dir}; did Phase 4 run?",
        )
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    with dev_server_factory(hydrogen_dir) as base_url:
        screenshots, failures = browser_driver(
            base_url=base_url,
            flow=flow,
            screenshots_dir=screenshots_dir,
        )

    return SmokeReport(
        base_url=base_url,
        flow=flow,
        screenshots=tuple(screenshots),
        failures=tuple(failures),
    )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _read_first_handle(*, path: Path, fallback: str) -> str:
    """Return the ``handle`` field of the first record under ``path``.

    Mirrors the same helper in :mod:`shop_gen.build.loop`: a missing,
    unreadable, or non-list payload falls back to ``fallback`` so the
    smoke flow stays well-formed even when the dataset is incomplete
    (Phase 2 should have populated every file before Phase 5 runs, so
    the fallback only triggers in defensive scenarios).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback
    if not isinstance(raw, list) or not raw:
        return fallback
    records = cast("list[object]", raw)
    first = records[0]
    if isinstance(first, dict):
        record = cast("dict[str, Any]", first)
        handle = record.get("handle")
        if isinstance(handle, str) and handle:
            return handle
    return fallback


__all__ = [
    "DEFAULT_SMOKE_FLOW",
    "DEFAULT_VIEWPORTS",
    "BrowserDriver",
    "DevServerFactory",
    "Screenshot",
    "SmokeAction",
    "SmokeFailure",
    "SmokeFlow",
    "SmokeReport",
    "SmokeStep",
    "Viewport",
    "resolve_smoke_flow",
    "run_playwright_smoke",
]
