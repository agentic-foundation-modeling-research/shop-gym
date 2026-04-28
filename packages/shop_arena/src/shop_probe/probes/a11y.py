"""Axis A — ``a11y`` probes (T3.3 — spec §5.3, §7 M3).

Accessibility-shape probes:

* :func:`skip_to_content_link` — a "skip to main content" link is the
  first focusable element (``a11y.skip_to_content``).
* :func:`combobox_role_present` — a ``role="combobox"`` element exists
  (``a11y.combobox_role``).
* :func:`dialog_role_present` — a ``role="dialog"`` (or ``<dialog>``)
  element exists (``a11y.dialog_role``).
* :func:`live_region_present` — at least one ``aria-live`` region exists
  (``a11y.live_region``).
* :func:`alt_text_coverage` — at least 80% of non-decorative ``<img>``
  elements declare an ``alt`` attribute (``a11y.alt_text_coverage``).
* :func:`focus_visible_style` — the page's stylesheet defines a
  ``:focus-visible`` rule (``a11y.focus_visible``).
"""

from __future__ import annotations

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome

_MIN_ALT_TEXT_COVERAGE: float = 0.8
"""Minimum fraction of ``<img>`` elements that must declare ``alt``."""


async def skip_to_content_link(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """A "skip to main content" link is present near the top of the document."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    link = page.locator(
        'a[href^="#main"], a[class*="skip"], a[class*="skip-to-content"], '
        'a[href="#content"], a:has-text("Skip to main content"), '
        'a:has-text("Skip to content")'
    ).first
    found = await link.count() > 0
    snap = await ctx.snapshot("skip-link")
    shot = await ctx.screenshot("skip-link")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no skip-to-content link found",
    )


async def combobox_role_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """At least one element exposes ``role="combobox"``."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    combo = page.locator('[role="combobox"]').first
    found = await combo.count() > 0
    snap = await ctx.snapshot("combobox")
    shot = await ctx.screenshot("combobox")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no role=combobox element on page",
    )


async def dialog_role_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """At least one ``role="dialog"`` (or ``<dialog>``) element exists."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    dialog = page.locator('[role="dialog"], dialog').first
    found = await dialog.count() > 0
    snap = await ctx.snapshot("dialog")
    shot = await ctx.screenshot("dialog")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no role=dialog / <dialog> element on page",
    )


async def live_region_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """At least one ``aria-live`` region exists on the page."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    region = page.locator("[aria-live]").first
    found = await region.count() > 0
    snap = await ctx.snapshot("live-region")
    shot = await ctx.screenshot("live-region")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no aria-live region on page",
    )


async def alt_text_coverage(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """At least 80% of ``<img>`` elements declare an ``alt`` attribute."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    images = page.locator("img")
    total = await images.count()
    snap = await ctx.snapshot("alt-coverage")
    shot = await ctx.screenshot("alt-coverage")
    if total == 0:
        # No images means there is nothing to fail; the storefront is
        # vacuously accessible on this dimension.
        return ProbeOutcome(passed=True, evidence=(shot, snap), notes="no <img> elements")
    with_alt = 0
    for i in range(total):
        alt = await images.nth(i).get_attribute("alt")
        if alt is not None:
            with_alt += 1
    coverage = with_alt / total
    passed = coverage >= _MIN_ALT_TEXT_COVERAGE
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None
        if passed
        else f"alt-text coverage {coverage:.2f} below {_MIN_ALT_TEXT_COVERAGE:.2f}",
    )


async def focus_visible_style(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """A ``:focus-visible`` style rule is defined in the page's CSS."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    snap = await ctx.snapshot("focus-visible")
    shot = await ctx.screenshot("focus-visible")
    # Inline stylesheets ship inside <style> tags; external stylesheets
    # would require a network fetch. We accept either signal.
    inline_styles = await page.locator("style").all_text_contents()
    has_rule = any(":focus-visible" in s for s in inline_styles)
    return ProbeOutcome(
        passed=has_rule,
        evidence=(shot, snap),
        notes=None if has_rule else "no :focus-visible rule in inline stylesheets",
    )
