"""Capture the per-shop 5-page bundle for the v2 capture-judge tier.

The bundle is the input to :func:`shop_probe.agent.judge.run_capture_judge`:
each :class:`PageCapture` row carries a screenshot path + aria-snapshot
path on disk, plus an ``applicable`` flag the dispatcher uses to skip
pages we couldn't reach.

URL resolution per :data:`shop_probe.rubric.schema.PageRef` (spec §5.3.3):

* ``home``       → ``base_url``
* ``collection`` → ``sample_collection_url`` (``None`` ⇒ ``applicable=False``)
* ``product``    → ``sample_product_url`` (``None`` ⇒ ``applicable=False``)
* ``cart``       → ``urljoin(base_url, "/cart")``
* ``search``     → ``urljoin(base_url, "/search?q=test")``

:func:`capture_bundle` never raises — navigation timeouts, 4xx/5xx, and
aria-snapshot exceptions all materialise as ``applicable=False`` rows so
one slow page cannot fail the whole shop's probe pass.

The module is import-safe — it performs no I/O at import time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urljoin

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome, ProbeRunner
from shop_probe.rubric.schema import PageRef

_BUNDLE_PROBE_PREFIX: Final[str] = "_bundle"
"""Probe-id prefix the bundle uses when calling :meth:`ProbeRunner.run`.

The runner namespaces evidence files under ``evidence_root/<probe_id>/``;
bundle captures live under ``evidence_root/_bundle/<page>/`` so they are
visually distinct from rubric-leaf evidence.
"""

_BUNDLE_NAV_TIMEOUT_MS: Final[int] = 15_000
"""Per-page ``page.goto`` timeout in milliseconds.

Spec §5.3.3 budget: 5 pages × 15 s worst case = ~75 s when every page
hangs. Real-world cohort runs land in ~10 s total per shop.
"""

_NOTES_MAX_LEN: Final[int] = 200
"""Cap on the ``notes`` string we record on a failed PageCapture.

Playwright errors can be very long (full DOM dumps); 200 chars is enough
to identify the failure mode without bloating ``ProbeReport`` size.
"""


@dataclass(frozen=True, slots=True)
class PageCapture:
    """One row of a per-shop :class:`PageBundle`.

    Attributes:
        page_ref: Which fixed page this row represents.
        url: URL the runner navigated to (or attempted to). Stored even
            when ``applicable=False`` so the operator can see what was
            tried.
        screenshot_rel: Path to the captured PNG, relative to the bundle
            root. ``None`` when no screenshot was written (capture
            failed before screenshot or never started).
        accessibility_rel: Path to the aria-snapshot JSON file, relative
            to the bundle root. ``None`` when the aria snapshot was
            never persisted.
        applicable: ``True`` iff both the screenshot and the aria-snapshot
            files are on disk. ``False`` when navigation failed, the
            page returned an error, the aria snapshot threw, or the
            sample URL was undiscovered.
        notes: Optional one-line failure reason. ``None`` on the happy
            path; capped at :data:`_NOTES_MAX_LEN` chars otherwise.
    """

    page_ref: PageRef
    url: str
    screenshot_rel: str | None
    accessibility_rel: str | None
    applicable: bool
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class PageBundle:
    """Per-shop 5-row bundle keyed by :data:`PageRef` (spec §5.3.3).

    Always carries exactly five captures (one per :data:`PageRef`); some
    of them may have ``applicable=False`` when the underlying page was
    unreachable. The judge dispatcher slices the bundle by the rubric
    entry's :attr:`shop_probe.rubric.schema.CaptureJudgeTask.pages`
    tuple before issuing the Messages-API call.

    Attributes:
        captures: All five page captures, in :data:`PageRef` order.
    """

    captures: tuple[PageCapture, ...]

    def get(self, page_ref: PageRef) -> PageCapture | None:
        """Return the :class:`PageCapture` for ``page_ref``, or ``None``.

        Args:
            page_ref: The page to look up.

        Returns:
            The matching capture, or ``None`` if the bundle does not
            carry that page (which should not happen — :func:`capture_bundle`
            always emits all 5 — but the lookup is safe regardless).
        """
        for cap in self.captures:
            if cap.page_ref == page_ref:
                return cap
        return None


def _resolve_url(
    page_ref: PageRef,
    *,
    base_url: str,
    sample_collection_url: str | None,
    sample_product_url: str | None,
) -> str | None:
    """Map a :data:`PageRef` to the URL the runner should navigate to.

    Returns ``None`` when the page requires a sample URL we never
    discovered — the caller turns that into a non-applicable capture
    without issuing a navigation.
    """
    if page_ref == "home":
        return base_url
    if page_ref == "collection":
        return sample_collection_url
    if page_ref == "product":
        return sample_product_url
    if page_ref == "cart":
        return urljoin(base_url, "/cart")
    if page_ref == "search":
        return urljoin(base_url, "/search?q=test")
    msg = f"unknown PageRef {page_ref!r}"
    raise ValueError(msg)


def _short(text: str) -> str:
    """Truncate ``text`` to :data:`_NOTES_MAX_LEN` chars for the notes field."""
    return text if len(text) <= _NOTES_MAX_LEN else text[: _NOTES_MAX_LEN - 1] + "…"


async def _capture_one(
    page: Page,
    *,
    page_ref: PageRef,
    url: str,
    bundle_root: Path,
) -> PageCapture:
    """Navigate ``page`` to ``url`` and persist screenshot + aria-snapshot.

    Failures inside this coroutine are caught one level up by
    :func:`capture_bundle` so a single broken page does not abort the
    bundle. Screenshots and aria-snapshot files land under
    ``bundle_root/<page_ref>/`` with the names ``screenshot.png`` and
    ``a11y.json`` respectively.

    Args:
        page: The Playwright :class:`Page` to drive.
        page_ref: Which bundle slot we are capturing.
        url: The resolved URL to navigate to.
        bundle_root: Directory under which the per-page subfolder is
            created.

    Returns:
        A populated :class:`PageCapture`. ``applicable`` is ``True`` iff
        navigation succeeded and both files were written.
    """
    page_dir = bundle_root / page_ref
    page_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = page_dir / "screenshot.png"
    a11y_path = page_dir / "a11y.json"
    rel_screenshot = f"{page_ref}/screenshot.png"
    rel_a11y = f"{page_ref}/a11y.json"
    await page.goto(url, wait_until="domcontentloaded", timeout=_BUNDLE_NAV_TIMEOUT_MS)
    await page.screenshot(path=str(screenshot_path), full_page=False)
    snapshot = await page.locator("body").aria_snapshot()
    a11y_path.write_text(
        json.dumps({"aria_snapshot": snapshot or ""}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return PageCapture(
        page_ref=page_ref,
        url=url,
        screenshot_rel=rel_screenshot,
        accessibility_rel=rel_a11y,
        applicable=True,
        notes=None,
    )


async def capture_bundle(
    runner: ProbeRunner,
    *,
    base_url: str,
    sample_collection_url: str | None,
    sample_product_url: str | None,
    bundle_root: Path,
    reuse_existing: bool = True,
) -> PageBundle:
    """Capture the 5-page bundle for one shop (spec §5.3.3).

    For each :data:`PageRef`:

    1. Resolve the URL via :func:`_resolve_url`. Pages that require a
       sample URL we never discovered yield ``applicable=False`` rows
       *without* a navigation attempt.
    2. **If ``reuse_existing`` is set and both ``screenshot.png`` and
       ``a11y.json`` are already on disk under
       ``bundle_root/<page_ref>/``, emit a reused** :class:`PageCapture`
       (``applicable=True``, ``notes="reused"``) **without launching a
       new browser context**. Lets iterative judge / prompt work skip
       the ~10 s Playwright pass between runs.
    3. Otherwise, dispatch through :meth:`ProbeRunner.run` so the
       isolated-context / pinned-UA / fixed-viewport discipline applies
       to every bundle capture, exactly the same as a deterministic
       probe.
    4. Wrap the per-page coroutine so timeouts, navigation errors, and
       aria-snapshot exceptions surface as ``applicable=False`` rows
       rather than aborting the bundle.

    Bundle files persist under ``bundle_root/<page_ref>/`` with the
    canonical names ``screenshot.png`` + ``a11y.json``. The directory
    is created lazily.

    Args:
        runner: A live :class:`ProbeRunner` (already inside its
            ``async with`` block).
        base_url: Storefront under test.
        sample_collection_url: Pre-resolved sample collection URL from
            ``_discover_sample_urls`` (``None`` when discovery failed).
        sample_product_url: Pre-resolved sample product URL from
            ``_discover_sample_urls`` (``None`` when discovery failed).
        bundle_root: Directory to write the bundle into. Usually
            ``evidence_root / "_bundle"`` so the captures live alongside
            rubric-leaf evidence.
        reuse_existing: When ``True`` (the default) and a per-page
            subdirectory already contains both ``screenshot.png`` and
            ``a11y.json``, skip the navigation and reuse the on-disk
            artifacts. Set to ``False`` to force a fresh capture
            (e.g. when the storefront has changed).

    Returns:
        A :class:`PageBundle` with exactly 5 :class:`PageCapture` rows
        in :data:`PageRef` order.
    """
    bundle_root.mkdir(parents=True, exist_ok=True)
    pages: tuple[PageRef, ...] = ("home", "collection", "product", "cart", "search")
    captures: list[PageCapture] = []

    for page_ref in pages:
        url = _resolve_url(
            page_ref,
            base_url=base_url,
            sample_collection_url=sample_collection_url,
            sample_product_url=sample_product_url,
        )
        if url is None:
            captures.append(
                PageCapture(
                    page_ref=page_ref,
                    url="",
                    screenshot_rel=None,
                    accessibility_rel=None,
                    applicable=False,
                    notes="sample URL not discovered",
                )
            )
            continue

        if reuse_existing:
            page_dir = bundle_root / page_ref
            screenshot_path = page_dir / "screenshot.png"
            a11y_path = page_dir / "a11y.json"
            if screenshot_path.is_file() and a11y_path.is_file():
                captures.append(
                    PageCapture(
                        page_ref=page_ref,
                        url=url,
                        screenshot_rel=f"{page_ref}/screenshot.png",
                        accessibility_rel=f"{page_ref}/a11y.json",
                        applicable=True,
                        notes="reused",
                    )
                )
                continue

        result_holder: dict[str, PageCapture] = {}

        async def _capture_probe(
            page: Page,
            ctx: ProbeContext,
            *,
            _page_ref: PageRef = page_ref,
            _url: str = url,
        ) -> ProbeOutcome:
            del ctx
            result_holder["capture"] = await _capture_one(
                page,
                page_ref=_page_ref,
                url=_url,
                bundle_root=bundle_root,
            )
            return ProbeOutcome(passed=True)

        outcome = await runner.run(
            _capture_probe,
            base_url=base_url,
            probe_id=f"{_BUNDLE_PROBE_PREFIX}/{page_ref}",
            sample_product_url=sample_product_url,
            sample_collection_url=sample_collection_url,
        )

        if "capture" in result_holder and outcome.passed:
            captures.append(result_holder["capture"])
        else:
            note = outcome.notes or "capture failed"
            captures.append(
                PageCapture(
                    page_ref=page_ref,
                    url=url,
                    screenshot_rel=None,
                    accessibility_rel=None,
                    applicable=False,
                    notes=_short(note),
                )
            )

    return PageBundle(captures=tuple(captures))
