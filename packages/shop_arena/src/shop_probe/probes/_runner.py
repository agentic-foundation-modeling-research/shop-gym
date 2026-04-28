"""Playwright orchestration for axis-A probes (T1.6 — spec §5.3).

The runner owns the Playwright lifecycle so the leaf probe modules
(``probes.site_shell`` …) only see a :class:`Page` plus a small
:class:`ProbeContext` that exposes:

* the storefront ``base_url`` and any sample URLs the runner pre-resolved;
* helper methods :meth:`ProbeContext.screenshot` and
  :meth:`ProbeContext.snapshot` that capture viewport + DOM artifacts
  under the report's evidence root and return :class:`EvidenceRef` rows.

Per spec §5.3 every probe runs in:

* an **isolated** Playwright context (one per probe, discarded after);
* a **fixed viewport** of ``(1280, 800)`` CSS pixels;
* a **pinned user agent** advertising ``ShopProbe/<version>``;
* **headless** Chromium;
* a **hard timeout** of 10 s by default, configurable per-call;
* with **``retries=0``** — flake is captured at the suite level via N=3
  reruns (spec §5.8), not by silently retrying inside a probe.

The runner converts probe outcomes into a structured :class:`ProbeOutcome`
(``passed``, ``evidence``, ``notes``, ``duration_ms``). A timeout or any
exception raised inside the probe lands as a failed outcome with a note
explaining why; ``duration_ms`` is always populated by the runner so
probes can ignore it.

This module performs no I/O at import time: launching Playwright happens
inside :meth:`ProbeRunner.__aenter__`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final

from playwright.async_api import Browser, Page, async_playwright

from shop_probe import __version__ as _shop_probe_version
from shop_probe.report import EvidenceRef

PINNED_USER_AGENT: Final[str] = (
    f"Mozilla/5.0 (compatible; ShopProbe/{_shop_probe_version}; "
    "+https://github.com/oss/shop-gym) Chromium HeadlessChrome"
)
"""Pinned UA string the probe context advertises (spec §5.3 + §5.8).

The shape mirrors a real browser UA prefix so storefronts that gate on
``Mozilla/5.0`` still serve their normal HTML, while the ``ShopProbe/<v>``
token makes the run identifiable in server logs.
"""

VIEWPORT_WIDTH: Final[int] = 1280
"""Fixed viewport width in CSS pixels (spec §5.3)."""

VIEWPORT_HEIGHT: Final[int] = 800
"""Fixed viewport height in CSS pixels (spec §5.3)."""

DEFAULT_PROBE_TIMEOUT_S: Final[float] = 10.0
"""Hard per-probe timeout in seconds (spec §5.3)."""


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """Structured outcome of one rubric-leaf probe (spec §5.3 + §5.6).

    Probes return this directly. The runner overwrites ``duration_ms``
    after measuring wall-clock time, so probe authors can leave the
    field at its default of 0.

    Attributes:
        passed: ``True`` on a clean assertion, ``False`` on a clean
            failure, ``None`` when the probe ran but the storefront
            does not exercise the relevant capability surface (encoded
            as "not_applicable" in :class:`shop_probe.report.ProbeResult`).
        evidence: Evidence references the probe captured. Order is
            preserved on the wire.
        notes: Optional free-form note (failure reason, observed value).
        duration_ms: Wall-clock duration of the probe call in
            milliseconds. Populated by the runner; probes leave at 0.
    """

    passed: bool | None
    evidence: tuple[EvidenceRef, ...] = ()
    notes: str | None = None
    duration_ms: int = 0


@dataclass(slots=True)
class ProbeContext:
    """Per-probe context handed to each Playwright probe (spec §5.3, §8.1).

    The runner constructs one of these per probe call. The probe receives
    ``(page, ctx)`` and uses ``ctx`` for two things:

    1. URL hints (``base_url`` plus optional sample collection / product
       URLs the runner pre-resolved during cohort setup).
    2. Evidence capture via :meth:`screenshot` and :meth:`snapshot`; the
       resulting :class:`EvidenceRef` rows are what the probe returns
       inside :class:`ProbeOutcome.evidence`.

    Attributes:
        page: The Playwright :class:`Page` for the probe's isolated
            context. Held on the context so evidence helpers can capture
            without the probe having to thread the page through.
        base_url: Storefront under test (no trailing slash assumed).
        probe_id: Rubric entry id for the probe (used to namespace
            evidence files; matches :attr:`shop_probe.report.ProbeResult.id`).
        evidence_root: Directory under which all evidence is written.
            Per-probe artifacts land in ``{evidence_root}/{probe_id}/``.
        sample_product_url: URL of a representative product, if known.
            ``None`` when the runner could not discover one (probe should
            return ``passed=None``).
        sample_collection_url: URL of a representative collection, if
            known. Same ``None`` semantics as ``sample_product_url``.
    """

    page: Page
    base_url: str
    probe_id: str
    evidence_root: Path
    sample_product_url: str | None = None
    sample_collection_url: str | None = None

    async def screenshot(self, name: str, *, selector: str | None = None) -> EvidenceRef:
        """Capture a viewport screenshot to disk and return its EvidenceRef.

        Args:
            name: Short label for the capture (e.g. ``"after-thumb-click"``).
                Sanitized into a filesystem-safe filename.
            selector: Optional CSS / ARIA-role selector recorded on the
                evidence row when the screenshot is anchored to one
                locator. ``None`` for full-viewport captures.

        Returns:
            An :class:`EvidenceRef` with ``kind="screenshot"`` and
            ``path`` relative to :attr:`evidence_root` (so reports stay
            relocatable per :class:`shop_probe.report.EvidenceRef`).
        """
        rel = Path(self.probe_id) / f"{_safe_evidence_name(name)}.png"
        absolute = self.evidence_root / rel
        absolute.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(absolute))
        return EvidenceRef(kind="screenshot", path=rel.as_posix(), selector=selector)

    async def snapshot(self, name: str, *, selector: str | None = None) -> EvidenceRef:
        """Capture the page DOM to disk and return its EvidenceRef.

        Args:
            name: Short label for the capture (sanitized into a
                filesystem-safe filename).
            selector: Optional CSS / ARIA-role selector recorded on the
                evidence row when the snapshot is anchored to one
                locator.

        Returns:
            An :class:`EvidenceRef` with ``kind="dom_snapshot"`` and
            ``path`` relative to :attr:`evidence_root`.
        """
        rel = Path(self.probe_id) / f"{_safe_evidence_name(name)}.html"
        absolute = self.evidence_root / rel
        absolute.parent.mkdir(parents=True, exist_ok=True)
        html = await self.page.content()
        absolute.write_text(html, encoding="utf-8")
        return EvidenceRef(kind="dom_snapshot", path=rel.as_posix(), selector=selector)


ProbeFn = Callable[[Page, ProbeContext], Awaitable[ProbeOutcome]]
"""Signature every leaf probe implements (spec §8.1)."""


def _safe_evidence_name(name: str) -> str:
    """Sanitize ``name`` into a filesystem-safe filename stem."""
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name)
    return cleaned or "evidence"


class ProbeRunner:
    """Orchestrates Playwright execution for axis-A probes (spec §5.3).

    Use as an async context manager so the underlying Playwright +
    Chromium lifecycle is bound to a ``with`` block::

        async with ProbeRunner(evidence_root=tmp_path) as runner:
            outcome = await runner.run(my_probe, base_url="http://localhost:4000",
                                       probe_id="site_shell.header.sticky")

    Each :meth:`run` call opens an **isolated** browser context with the
    pinned UA and (1280, 800) viewport, hands the probe a fresh
    :class:`Page` + :class:`ProbeContext`, enforces a hard timeout
    (default 10 s), and disposes the context on exit. ``retries=0``: the
    runner never retries — flake is measured at the suite level (spec §5.8).
    """

    def __init__(
        self,
        *,
        evidence_root: Path,
        timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
        user_agent: str = PINNED_USER_AGENT,
        viewport: tuple[int, int] = (VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
        headless: bool = True,
        record_har: bool = False,
    ) -> None:
        """Initialize the runner.

        Args:
            evidence_root: Directory under which probe evidence is
                written. Created on enter if it does not exist.
            timeout_s: Default hard timeout per probe call (spec §5.3).
                Individual :meth:`run` calls can override.
            user_agent: Pinned UA string (defaults to
                :data:`PINNED_USER_AGENT`).
            viewport: ``(width, height)`` viewport in CSS pixels
                (defaults to ``(1280, 800)``; spec §5.3).
            headless: Whether to launch Chromium headless (defaults to
                ``True``; spec §5.3).
            record_har: When ``True`` every probe context records its
                network traffic to ``{evidence_root}/{probe_id}/network.har``
                and the runner appends an :class:`EvidenceRef` of kind
                ``"har"`` to the probe's outcome (spec §5.8 — "Save HAR
                captures of every crawl"). Defaults to ``False`` so
                axis-A unit tests stay fast; the cohort run
                (T5.2 / spec §7 M5) flips it on via the CLI.
        """
        self.evidence_root = evidence_root
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self.viewport = viewport
        self.headless = headless
        self.record_har = record_har
        self._stack: contextlib.AsyncExitStack | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> ProbeRunner:
        """Launch Playwright + Chromium and prepare the evidence root."""
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
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def browser(self) -> Browser:
        """Return the live :class:`Browser` instance.

        Raises:
            RuntimeError: If accessed outside the ``async with`` block.
        """
        if self._browser is None:
            msg = "ProbeRunner must be used as an async context manager"
            raise RuntimeError(msg)
        return self._browser

    @property
    def chromium_version(self) -> str:
        """Browser binary version reported by Playwright (spec §5.3 + §5.8)."""
        return self.browser.version

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close Chromium and stop Playwright."""
        stack, self._stack = self._stack, None
        self._browser = None
        if stack is not None:
            await stack.__aexit__(exc_type, exc, tb)

    async def run(
        self,
        probe: ProbeFn,
        *,
        base_url: str,
        probe_id: str,
        sample_product_url: str | None = None,
        sample_collection_url: str | None = None,
        timeout_s: float | None = None,
    ) -> ProbeOutcome:
        """Run one probe in a fresh isolated browser context.

        The probe is invoked as ``await probe(page, ctx)``. If it raises
        or exceeds the timeout, the runner returns a ``passed=False``
        outcome with a diagnostic note rather than propagating; per
        spec §5.3 ``retries=0``, so the call runs exactly once.

        Args:
            probe: Async callable matching :data:`ProbeFn`.
            base_url: Storefront URL passed through on
                :class:`ProbeContext`.
            probe_id: Rubric entry id; used to namespace evidence files.
            sample_product_url: Optional pre-resolved sample PDP URL.
            sample_collection_url: Optional pre-resolved sample
                collection URL.
            timeout_s: Override the runner's default timeout for this
                call only. ``None`` uses :attr:`timeout_s`.

        Returns:
            The :class:`ProbeOutcome` returned by the probe with
            ``duration_ms`` populated by the runner.

        Raises:
            RuntimeError: If called outside the ``async with`` block.
        """
        if self._browser is None:
            msg = "ProbeRunner must be used as an async context manager"
            raise RuntimeError(msg)
        budget = timeout_s if timeout_s is not None else self.timeout_s
        start = time.perf_counter()
        har_rel_path: Path | None = None
        context_kwargs: dict[str, object] = {
            "user_agent": self.user_agent,
            "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
        }
        if self.record_har:
            har_rel_path = Path(probe_id) / "network.har"
            har_absolute = self.evidence_root / har_rel_path
            har_absolute.parent.mkdir(parents=True, exist_ok=True)
            context_kwargs["record_har_path"] = str(har_absolute)
        context = await self._browser.new_context(**context_kwargs)  # type: ignore[arg-type]
        try:
            page = await context.new_page()
            page.set_default_timeout(budget * 1000.0)
            ctx = ProbeContext(
                page=page,
                base_url=base_url,
                probe_id=probe_id,
                evidence_root=self.evidence_root,
                sample_product_url=sample_product_url,
                sample_collection_url=sample_collection_url,
            )
            try:
                outcome = await asyncio.wait_for(probe(page, ctx), timeout=budget)
            except TimeoutError:
                outcome = ProbeOutcome(
                    passed=False,
                    notes=f"timeout after {budget:g}s",
                )
            except Exception as err:
                outcome = ProbeOutcome(
                    passed=False,
                    notes=f"{type(err).__name__}: {err}",
                )
        finally:
            # context.close() finalizes the HAR file when record_har is on.
            await context.close()
        evidence = outcome.evidence
        if har_rel_path is not None:
            evidence = (
                *evidence,
                EvidenceRef(kind="har", path=har_rel_path.as_posix()),
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProbeOutcome(
            passed=outcome.passed,
            evidence=evidence,
            notes=outcome.notes,
            duration_ms=duration_ms,
        )
