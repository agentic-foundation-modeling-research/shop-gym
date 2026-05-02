"""Capture the per-shop 5-page bundle (one capture per :data:`PageType`).

Each :class:`PageCapture` row carries a screenshot path + aria-snapshot
JSON path on disk. The capture pipeline is the input to every family:
``observation.shape`` and ``action.space`` read the files and compute
mechanical metrics; ``observation.info_slots`` and ``action.control_slots``
hand them to a single-modality LLM judge.

URL resolution per :data:`PageType`:

* ``homepage``   → ``base_url``
* ``collection`` → ``sample_collection_url`` (``None`` ⇒ ``applicable=False``)
* ``product``    → ``sample_product_url`` (``None`` ⇒ ``applicable=False``)
* ``cart``       → ``urljoin(base_url, "/cart")``
* ``search``     → ``urljoin(base_url, "/search?q=test")``

:func:`capture_bundle` never raises — navigation timeouts, 4xx/5xx, and
aria-snapshot exceptions all materialise as ``applicable=False`` rows so
one slow page cannot fail the whole shop's pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urljoin

from playwright.async_api import Page

from shop_arena.probe.playwright_runner import PlaywrightRunner
from shop_arena.probe.rubric.schema import PageType

_BUNDLE_NAV_TIMEOUT_S: Final[float] = 15.0
_NOTES_MAX_LEN: Final[int] = 200

PAGE_TYPES: Final[tuple[PageType, ...]] = (
    "homepage",
    "collection",
    "product",
    "search",
    "cart",
)
"""Canonical capture order."""


@dataclass(frozen=True, slots=True)
class PageCapture:
    """One row of a per-shop :class:`PageBundle`.

    Attributes:
        page_type: Which fixed page this row represents.
        url: URL the runner navigated to (or attempted to). Stored even
            when ``applicable=False`` so the operator can see what was
            tried.
        screenshot_rel: Path to the captured PNG, relative to the bundle
            root. ``None`` when no screenshot was written.
        accessibility_rel: Path to the aria-snapshot JSON file, relative
            to the bundle root. ``None`` when never persisted.
        applicable: ``True`` iff both files are on disk.
        notes: Optional one-line failure reason (capped at 200 chars).
    """

    page_type: PageType
    url: str
    screenshot_rel: str | None
    accessibility_rel: str | None
    applicable: bool
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class PageBundle:
    """Per-shop 5-row bundle keyed by :data:`PageType`."""

    captures: tuple[PageCapture, ...]

    def get(self, page_type: PageType) -> PageCapture | None:
        """Return the :class:`PageCapture` for ``page_type``, or ``None``."""
        for cap in self.captures:
            if cap.page_type == page_type:
                return cap
        return None


def _resolve_url(
    page_type: PageType,
    *,
    base_url: str,
    sample_collection_url: str | None,
    sample_product_url: str | None,
) -> str | None:
    if page_type == "homepage":
        return base_url
    if page_type == "collection":
        return sample_collection_url
    if page_type == "product":
        return sample_product_url
    if page_type == "cart":
        return urljoin(base_url, "/cart")
    if page_type == "search":
        return urljoin(base_url, "/search?q=test")
    msg = f"unknown PageType {page_type!r}"
    raise ValueError(msg)


def _short(text: str) -> str:
    return text if len(text) <= _NOTES_MAX_LEN else text[: _NOTES_MAX_LEN - 1] + "…"


async def _capture_one(
    page: Page,
    *,
    page_type: PageType,
    url: str,
    bundle_root: Path,
) -> PageCapture:
    """Navigate ``page`` to ``url`` and persist screenshot + aria-snapshot.

    Files land under ``bundle_root/<page_type>/`` as ``screenshot.png``
    and ``a11y.json``.
    """
    page_dir = bundle_root / page_type
    page_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = page_dir / "screenshot.png"
    a11y_path = page_dir / "a11y.json"
    rel_screenshot = f"{page_type}/screenshot.png"
    rel_a11y = f"{page_type}/a11y.json"

    await page.goto(url, wait_until="domcontentloaded")
    await page.screenshot(path=str(screenshot_path), full_page=False)
    snapshot = await page.locator("body").aria_snapshot()
    a11y_path.write_text(
        json.dumps({"aria_snapshot": snapshot or ""}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return PageCapture(
        page_type=page_type,
        url=url,
        screenshot_rel=rel_screenshot,
        accessibility_rel=rel_a11y,
        applicable=True,
        notes=None,
    )


async def discover_sample_urls(
    runner: PlaywrightRunner, base_url: str
) -> tuple[str | None, str | None]:
    """Walk the homepage to find a sample collection URL and a sample product URL.

    Returns ``(None, None)`` on any navigation failure. Used by
    :func:`capture_bundle` and :func:`shop_arena.probe.transition.runner.run_transitions`.
    """
    discovered: dict[str, str | None] = {"collection": None, "product": None}

    async def _discover(page: Page) -> None:
        await page.goto(base_url, wait_until="domcontentloaded")
        coll_link = page.locator('a[href*="/collections/"]').first
        if await coll_link.count() > 0:
            href = await coll_link.get_attribute("href")
            if href:
                discovered["collection"] = urljoin(base_url, href)
        if discovered["collection"] is not None:
            await page.goto(discovered["collection"], wait_until="domcontentloaded")
            prod_link = page.locator('a[href*="/products/"]').first
            if await prod_link.count() > 0:
                href = await prod_link.get_attribute("href")
                if href:
                    discovered["product"] = urljoin(base_url, href)

    try:
        await runner.run(_discover, timeout_s=_BUNDLE_NAV_TIMEOUT_S)
    except (TimeoutError, Exception):  # noqa: BLE001 — same-shape failure surface
        return None, None
    return discovered["collection"], discovered["product"]


async def capture_bundle(
    runner: PlaywrightRunner,
    *,
    base_url: str,
    sample_collection_url: str | None,
    sample_product_url: str | None,
    bundle_root: Path,
    reuse_existing: bool = True,
) -> PageBundle:
    """Capture the 5-page bundle for one shop.

    For each :data:`PageType`:

    1. Resolve the URL. Pages that need a sample URL we never discovered
       yield ``applicable=False`` rows *without* a navigation attempt.
    2. **If ``reuse_existing`` is set and both files are already on disk
       under** ``bundle_root/<page_type>/``, emit a reused capture
       (``notes="reused"``) without re-running Playwright.
    3. Otherwise navigate via :class:`PlaywrightRunner`. Errors materialise
       as ``applicable=False`` rather than aborting the bundle.

    Args:
        runner: A live :class:`PlaywrightRunner` (already inside its
            ``async with`` block).
        base_url: Storefront under test.
        sample_collection_url: Pre-resolved sample collection URL
            (``None`` when discovery failed).
        sample_product_url: Pre-resolved sample product URL.
        bundle_root: Directory to write the bundle into.
        reuse_existing: When ``True`` (default) and a per-page subdir
            already contains both files, skip navigation.

    Returns:
        A :class:`PageBundle` with exactly 5 :class:`PageCapture` rows.
    """
    bundle_root.mkdir(parents=True, exist_ok=True)
    captures: list[PageCapture] = []

    for page_type in PAGE_TYPES:
        url = _resolve_url(
            page_type,
            base_url=base_url,
            sample_collection_url=sample_collection_url,
            sample_product_url=sample_product_url,
        )
        if url is None:
            captures.append(
                PageCapture(
                    page_type=page_type,
                    url="",
                    screenshot_rel=None,
                    accessibility_rel=None,
                    applicable=False,
                    notes="sample URL not discovered",
                )
            )
            continue

        if reuse_existing:
            page_dir = bundle_root / page_type
            screenshot_path = page_dir / "screenshot.png"
            a11y_path = page_dir / "a11y.json"
            if screenshot_path.is_file() and a11y_path.is_file():
                captures.append(
                    PageCapture(
                        page_type=page_type,
                        url=url,
                        screenshot_rel=f"{page_type}/screenshot.png",
                        accessibility_rel=f"{page_type}/a11y.json",
                        applicable=True,
                        notes="reused",
                    )
                )
                continue

        async def _do_capture(
            page: Page,
            *,
            _pt: PageType = page_type,
            _url: str = url,
        ) -> PageCapture:
            return await _capture_one(
                page, page_type=_pt, url=_url, bundle_root=bundle_root
            )

        try:
            capture, _outcome = await runner.run(
                _do_capture, timeout_s=_BUNDLE_NAV_TIMEOUT_S
            )
            captures.append(capture)
        except TimeoutError:
            captures.append(
                PageCapture(
                    page_type=page_type,
                    url=url,
                    screenshot_rel=None,
                    accessibility_rel=None,
                    applicable=False,
                    notes=_short(f"timeout after {_BUNDLE_NAV_TIMEOUT_S:g}s"),
                )
            )
        except Exception as err:  # noqa: BLE001 — many error classes share the path
            captures.append(
                PageCapture(
                    page_type=page_type,
                    url=url,
                    screenshot_rel=None,
                    accessibility_rel=None,
                    applicable=False,
                    notes=_short(f"{type(err).__name__}: {err}"),
                )
            )

    return PageBundle(captures=tuple(captures))
