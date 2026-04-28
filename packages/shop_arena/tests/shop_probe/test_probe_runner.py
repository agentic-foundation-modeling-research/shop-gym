"""Tests for `shop_probe.probes._runner` (T1.6 — spec §5.3).

Covers the runner contract:

* Pinned user agent + fixed viewport are applied to the probe's
  isolated context.
* The hard per-probe timeout converts a hung probe into a
  ``passed=False`` outcome with a "timeout" note and a populated
  ``duration_ms``.
* Probe-raised exceptions land as ``passed=False`` outcomes (no
  ``retries=0`` re-execution) with the exception type in the notes.
* :meth:`ProbeContext.screenshot` and :meth:`ProbeContext.snapshot`
  write artifacts under the evidence root and return relative
  :class:`EvidenceRef` paths.
* Calling :meth:`ProbeRunner.run` outside the ``async with`` block
  raises immediately.

Tests use the stdlib ``http.server`` running on an ephemeral port
inside a daemon thread as the localhost HTML fixture (spec §7 M1
acceptance — "localhost SandboxShop" stand-in for runner-only checks).
"""

from __future__ import annotations

import asyncio
import http.server
import socketserver
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.async_api import Page

from shop_probe.probes._runner import (
    DEFAULT_PROBE_TIMEOUT_S,
    PINNED_USER_AGENT,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    ProbeContext,
    ProbeOutcome,
    ProbeRunner,
)
from shop_probe.report import EvidenceRef

# --------------------------------------------------------------------------- #
# Localhost HTML fixture
# --------------------------------------------------------------------------- #

_FIXTURE_HTML: bytes = (
    b"<!doctype html><html><head><title>fixture</title></head>"
    b"<body><h1 id='hero'>Hello, ShopProbe</h1>"
    b"<div data-testid='probe-target'>marker</div></body></html>"
)


class _SilentHandler(http.server.BaseHTTPRequestHandler):
    """In-process HTML fixture; silences default request logging."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_FIXTURE_HTML)))
        self.end_headers()
        self.wfile.write(_FIXTURE_HTML)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — base API name
        # Keep pytest output quiet.
        del format, args


@pytest.fixture
def fixture_url() -> Iterator[str]:
    """Spin up the localhost HTML fixture for the lifetime of one test."""
    server = socketserver.TCPServer(("127.0.0.1", 0), _SilentHandler)
    port: int = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #


def test_default_timeout_matches_spec() -> None:
    """Spec §5.3: default per-probe timeout is 10 s."""
    assert DEFAULT_PROBE_TIMEOUT_S == 10.0  # noqa: PLR2004 — spec-pinned constant


def test_default_viewport_matches_spec() -> None:
    """Spec §5.3: viewport pinned at 1280x800."""
    assert (VIEWPORT_WIDTH, VIEWPORT_HEIGHT) == (1280, 800)


def test_pinned_user_agent_identifies_shop_probe() -> None:
    """Spec §5.3 + §5.8: pinned UA must be reproducible and identifiable."""
    assert "ShopProbe/" in PINNED_USER_AGENT
    assert PINNED_USER_AGENT.startswith("Mozilla/5.0")


# --------------------------------------------------------------------------- #
# ProbeOutcome shape
# --------------------------------------------------------------------------- #


def test_probe_outcome_defaults_are_minimal() -> None:
    """Probes can return just ``passed``; runner fills in the rest."""
    outcome = ProbeOutcome(passed=True)
    assert outcome.evidence == ()
    assert outcome.notes is None
    assert outcome.duration_ms == 0


# --------------------------------------------------------------------------- #
# Use-outside-context-manager error
# --------------------------------------------------------------------------- #


def test_run_outside_context_manager_raises(tmp_path: Path) -> None:
    runner = ProbeRunner(evidence_root=tmp_path / "evidence")

    async def _noop(_page: Page, _ctx: ProbeContext) -> ProbeOutcome:
        return ProbeOutcome(passed=True)

    async def _go() -> None:
        with pytest.raises(RuntimeError, match="async context manager"):
            await runner.run(_noop, base_url="http://localhost", probe_id="x.y")

    asyncio.run(_go())


# --------------------------------------------------------------------------- #
# Pinned UA + fixed viewport
# --------------------------------------------------------------------------- #


def test_runner_applies_pinned_ua_and_viewport(
    tmp_path: Path,
    fixture_url: str,
) -> None:
    """Spec §5.3: probe context uses the pinned UA + 1280x800 viewport."""
    captured: dict[str, object] = {}

    async def probe(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url)
        captured["ua"] = await page.evaluate("navigator.userAgent")
        captured["viewport"] = page.viewport_size
        return ProbeOutcome(passed=True)

    async def _go() -> None:
        async with ProbeRunner(evidence_root=tmp_path / "evidence") as runner:
            outcome = await runner.run(
                probe,
                base_url=fixture_url,
                probe_id="site_shell.header.sticky",
            )
        assert outcome.passed is True
        assert outcome.duration_ms > 0
        assert captured["ua"] == PINNED_USER_AGENT
        assert captured["viewport"] == {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}

    asyncio.run(_go())


# --------------------------------------------------------------------------- #
# Timeout path
# --------------------------------------------------------------------------- #


def test_runner_converts_timeout_to_failed_outcome(tmp_path: Path) -> None:
    """Spec §5.3: hung probes return ``passed=False`` with a timeout note."""

    async def hangs(_page: Page, _ctx: ProbeContext) -> ProbeOutcome:
        await asyncio.sleep(60.0)
        return ProbeOutcome(passed=True)  # pragma: no cover

    async def _go() -> ProbeOutcome:
        async with ProbeRunner(evidence_root=tmp_path / "evidence") as runner:
            return await runner.run(
                hangs,
                base_url="http://127.0.0.1:1/",  # never reached
                probe_id="cart.page.renders",
                timeout_s=0.25,
            )

    outcome = asyncio.run(_go())
    assert outcome.passed is False
    assert outcome.notes is not None
    assert "timeout" in outcome.notes
    assert outcome.duration_ms >= 200  # noqa: PLR2004 — lower bound = 200ms timeout budget


# --------------------------------------------------------------------------- #
# Exception path
# --------------------------------------------------------------------------- #


def test_runner_converts_exception_to_failed_outcome(
    tmp_path: Path,
    fixture_url: str,
) -> None:
    """Probe-raised exceptions land as ``passed=False`` (``retries=0``)."""
    call_count = 0

    async def boom(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        nonlocal call_count
        call_count += 1
        await page.goto(ctx.base_url)
        msg = "deliberate failure"
        raise RuntimeError(msg)

    async def _go() -> ProbeOutcome:
        async with ProbeRunner(evidence_root=tmp_path / "evidence") as runner:
            return await runner.run(
                boom,
                base_url=fixture_url,
                probe_id="product.title.present",
            )

    outcome = asyncio.run(_go())
    assert outcome.passed is False
    assert outcome.notes == "RuntimeError: deliberate failure"
    assert outcome.duration_ms > 0
    assert call_count == 1, "spec §5.3 retries=0 — runner must run exactly once"


# --------------------------------------------------------------------------- #
# Evidence capture
# --------------------------------------------------------------------------- #


def test_screenshot_and_snapshot_write_under_evidence_root(
    tmp_path: Path,
    fixture_url: str,
) -> None:
    """Evidence helpers write to disk and return ``EvidenceRef`` rows."""
    evidence_root = tmp_path / "evidence"

    async def probe(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url)
        shot = await ctx.screenshot("hero", selector="#hero")
        snap = await ctx.snapshot("dom", selector="body")
        return ProbeOutcome(passed=True, evidence=(shot, snap))

    async def _go() -> ProbeOutcome:
        async with ProbeRunner(evidence_root=evidence_root) as runner:
            return await runner.run(
                probe,
                base_url=fixture_url,
                probe_id="site_shell.header.logo_links_home",
            )

    outcome = asyncio.run(_go())
    assert outcome.passed is True
    assert len(outcome.evidence) == 2  # noqa: PLR2004 — one screenshot + one snapshot
    shot, snap = outcome.evidence
    assert isinstance(shot, EvidenceRef)
    assert shot.kind == "screenshot"
    assert shot.selector == "#hero"
    assert shot.path == "site_shell.header.logo_links_home/hero.png"
    assert (evidence_root / shot.path).is_file()
    assert (evidence_root / shot.path).stat().st_size > 0

    assert snap.kind == "dom_snapshot"
    assert snap.selector == "body"
    assert snap.path == "site_shell.header.logo_links_home/dom.html"
    snap_text = (evidence_root / snap.path).read_text(encoding="utf-8")
    assert "Hello, ShopProbe" in snap_text


def test_evidence_filename_sanitization(tmp_path: Path, fixture_url: str) -> None:
    """Capture labels with awkward characters land as filesystem-safe names."""

    async def probe(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url)
        ref = await ctx.screenshot("after click/step 1!")
        return ProbeOutcome(passed=True, evidence=(ref,))

    async def _go() -> ProbeOutcome:
        async with ProbeRunner(evidence_root=tmp_path / "evidence") as runner:
            return await runner.run(
                probe,
                base_url=fixture_url,
                probe_id="collection.listing.product_cards",
            )

    outcome = asyncio.run(_go())
    assert outcome.passed is True
    (ref,) = outcome.evidence
    # `/`, ` `, `!` are not alnum/`-`/`_`, so they collapse to `_`.
    assert ref.path == "collection.listing.product_cards/after_click_step_1_.png"
    assert (tmp_path / "evidence" / ref.path).is_file()


# --------------------------------------------------------------------------- #
# Isolation between probe calls
# --------------------------------------------------------------------------- #


def test_each_run_uses_fresh_context(tmp_path: Path, fixture_url: str) -> None:
    """Spec §5.3: every probe runs in an isolated Playwright context."""

    async def set_marker(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url)
        await page.evaluate("window.__shop_probe_marker = 'first run'")
        marker = await page.evaluate("window.__shop_probe_marker")
        return ProbeOutcome(passed=True, notes=str(marker))

    async def read_marker(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url)
        marker = await page.evaluate("window.__shop_probe_marker ?? null")
        return ProbeOutcome(passed=True, notes=f"marker={marker!r}")

    async def _go() -> tuple[ProbeOutcome, ProbeOutcome]:
        async with ProbeRunner(evidence_root=tmp_path / "evidence") as runner:
            first = await runner.run(
                set_marker,
                base_url=fixture_url,
                probe_id="cart.line_item.shows_after_add",
            )
            second = await runner.run(
                read_marker,
                base_url=fixture_url,
                probe_id="cart.line_item.qty_editor",
            )
        return first, second

    first, second = asyncio.run(_go())
    assert first.notes == "first run"
    assert second.notes == "marker=None", (
        "second probe must not see state from the first probe's isolated context"
    )


# --------------------------------------------------------------------------- #
# HAR capture (T5.2 — spec §5.8)
# --------------------------------------------------------------------------- #


def test_record_har_emits_evidence_ref_and_writes_file(
    tmp_path: Path,
    fixture_url: str,
) -> None:
    """Spec §5.8: ``record_har=True`` writes a HAR per probe context.

    The runner is responsible for closing the context (which finalizes
    the HAR file on disk) and for appending an :class:`EvidenceRef` of
    kind ``"har"`` to the outcome's evidence so reviewers can re-score
    offline against the captured network responses.
    """
    evidence_root = tmp_path / "evidence"

    async def probe(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url)
        return ProbeOutcome(passed=True)

    async def _go() -> ProbeOutcome:
        async with ProbeRunner(evidence_root=evidence_root, record_har=True) as runner:
            return await runner.run(
                probe,
                base_url=fixture_url,
                probe_id="site_shell.header.sticky",
            )

    outcome = asyncio.run(_go())
    assert outcome.passed is True
    har_refs = tuple(ev for ev in outcome.evidence if ev.kind == "har")
    assert len(har_refs) == 1, "runner must append exactly one HAR EvidenceRef"
    (har_ref,) = har_refs
    assert har_ref.path == "site_shell.header.sticky/network.har"
    har_file = evidence_root / har_ref.path
    assert har_file.is_file()
    assert har_file.stat().st_size > 0, "HAR file must contain captured traffic"


def test_record_har_default_off_emits_no_har_evidence(
    tmp_path: Path,
    fixture_url: str,
) -> None:
    """By default the runner does not record HAR (axis-A unit tests stay fast)."""
    evidence_root = tmp_path / "evidence"

    async def probe(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url)
        return ProbeOutcome(passed=True)

    async def _go() -> ProbeOutcome:
        async with ProbeRunner(evidence_root=evidence_root) as runner:
            return await runner.run(
                probe,
                base_url=fixture_url,
                probe_id="site_shell.header.sticky",
            )

    outcome = asyncio.run(_go())
    assert outcome.passed is True
    assert all(ev.kind != "har" for ev in outcome.evidence)
    assert not (evidence_root / "site_shell.header.sticky" / "network.har").exists()
