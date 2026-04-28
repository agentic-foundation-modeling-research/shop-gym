"""Axis A — ``search`` probes (T3.3 — spec §5.3, §7 M3).

Probes asserted against the storefront search surface — both the
header trigger and the dedicated ``/search`` results page:

* :func:`header_has_search_trigger` — the header exposes a search input
  or trigger (``search.header.trigger``).
* :func:`results_page_renders` — ``/search?q=…`` returns a 2xx HTML page
  (``search.results_page.renders``).
* :func:`results_page_echoes_query` — the results page surfaces the
  submitted query string (``search.query_echo``).
* :func:`no_results_state` — ``/search?q=zzznoresults`` renders an
  explicit empty-state (``search.no_results_state``).
* :func:`predictive_listbox_present` — the header search exposes a
  ``role="combobox"`` + ``role="listbox"`` predictive UI
  (``search.predictive_listbox``).
"""

from __future__ import annotations

from urllib.parse import urljoin

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome

_NO_RESULTS_QUERY: str = "zzznoresults"
"""Sentinel query used by :func:`no_results_state`. Storefronts that do
not gate on this value should still render an empty-state for any query
with no matches."""

_SAMPLE_QUERY: str = "sample"
"""Query used to probe the positive search results path."""


def _search_url(base_url: str, query: str) -> str:
    """Resolve ``base_url`` + ``/search?q=<query>``."""
    return urljoin(base_url.rstrip("/") + "/", f"search?q={query}")


async def header_has_search_trigger(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Header exposes a search input or trigger button."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    trigger = page.locator(
        'header input[type="search"], header [role="search"] input, '
        'header [role="search"] button, '
        'header button[aria-label*="search" i], header a[href*="/search"]'
    ).first
    found = await trigger.count() > 0
    snap = await ctx.snapshot("search-trigger")
    shot = await ctx.screenshot("search-trigger")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no search input or trigger in header",
    )


async def results_page_renders(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """``/search?q=…`` returns 2xx HTML."""
    response = await page.goto(
        _search_url(ctx.base_url, _SAMPLE_QUERY), wait_until="domcontentloaded"
    )
    snap = await ctx.snapshot("search-results")
    shot = await ctx.screenshot("search-results")
    if response is None:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no response from /search")
    body_text = (await page.locator("body").text_content()) or ""
    has_body = len(body_text.strip()) > 0
    passed = 200 <= response.status < 400 and has_body  # noqa: PLR2004
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"/search returned status={response.status}",
    )


async def results_page_echoes_query(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Results page surfaces the submitted query string in body copy."""
    await page.goto(_search_url(ctx.base_url, _SAMPLE_QUERY), wait_until="domcontentloaded")
    body_text = ((await page.locator("body").text_content()) or "").lower()
    snap = await ctx.snapshot("query-echo")
    shot = await ctx.screenshot("query-echo")
    passed = _SAMPLE_QUERY in body_text
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"query {_SAMPLE_QUERY!r} not echoed in results body",
    )


async def no_results_state(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """``/search?q=<unmatched>`` renders an explicit empty-state."""
    await page.goto(_search_url(ctx.base_url, _NO_RESULTS_QUERY), wait_until="domcontentloaded")
    snap = await ctx.snapshot("no-results")
    shot = await ctx.screenshot("no-results")
    explicit = page.locator(
        '[class*="no-results"], [class*="empty-results"], '
        '[data-testid*="no-results"], [aria-label*="no results" i]'
    ).first
    if await explicit.count() > 0:
        return ProbeOutcome(passed=True, evidence=(shot, snap))
    body_text = ((await page.locator("body").text_content()) or "").lower()
    passed = (
        "no results" in body_text
        or "no matches" in body_text
        or "didn't find" in body_text
        or "did not find" in body_text
    )
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else "no explicit empty-state on unmatched search query",
    )


async def predictive_listbox_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Header search exposes an ARIA combobox + listbox pair."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    combo = page.locator('header [role="combobox"]').first
    listbox = page.locator('header [role="listbox"]').first
    has_combo = await combo.count() > 0
    has_listbox = await listbox.count() > 0
    snap = await ctx.snapshot("predictive")
    shot = await ctx.screenshot("predictive")
    passed = has_combo and has_listbox
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None
        if passed
        else f"missing predictive UI (combobox={has_combo}, listbox={has_listbox})",
    )
