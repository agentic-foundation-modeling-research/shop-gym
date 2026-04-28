"""Axis A — ``media`` probes (T3.3 — spec §5.3, §7 M3).

Probes for the storefront's media surface (mostly PDP-bound):

* :func:`lazy_loaded_images` — at least one image declares ``loading="lazy"``
  (``media.lazy_load_images``).
* :func:`responsive_srcset` — at least one image declares ``srcset``
  (``media.responsive_srcset``).
* :func:`lightbox_or_zoom` — PDP exposes a lightbox / zoom affordance
  (``media.lightbox_or_zoom``).
* :func:`swatch_image_swap` — variant swatches carry an image-source
  hint that supports swapping the main gallery image
  (``media.swatch_image_swap``).
"""

from __future__ import annotations

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


async def lazy_loaded_images(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """At least one image on the homepage declares ``loading="lazy"``."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    lazy = page.locator('img[loading="lazy"]').first
    found = await lazy.count() > 0
    snap = await ctx.snapshot("lazy")
    shot = await ctx.screenshot("lazy")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no img[loading=lazy] on homepage",
    )


async def responsive_srcset(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """At least one image declares ``srcset`` (responsive sources)."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    srcset = page.locator("img[srcset], source[srcset]").first
    found = await srcset.count() > 0
    snap = await ctx.snapshot("srcset")
    shot = await ctx.screenshot("srcset")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no img/source carries a srcset attribute",
    )


async def lightbox_or_zoom(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """PDP exposes a lightbox / zoom affordance for the gallery."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    affordance = page.locator(
        "[data-lightbox], [data-zoom], "
        '[class*="lightbox"], [class*="zoom"], '
        'button[aria-label*="zoom" i], button[aria-label*="enlarge" i]'
    ).first
    found = await affordance.count() > 0
    snap = await ctx.snapshot("lightbox")
    shot = await ctx.screenshot("lightbox")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no lightbox / zoom affordance on PDP",
    )


async def swatch_image_swap(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Variant swatches carry image-source hints (``data-swatch-image`` etc.).

    Detects the *capability* — a swap-on-click handler usually depends on
    JS that needs an explicit hint on each swatch — without exercising
    the swap itself (which can be flaky across themes).
    """
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    swatch = page.locator(
        "[data-swatch-image], [data-variant-image], "
        '[class*="swatch"][data-image], [class*="swatch"][data-thumb-src]'
    ).first
    found = await swatch.count() > 0
    snap = await ctx.snapshot("swatch")
    shot = await ctx.screenshot("swatch")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no variant swatch carries a data-* image hint",
    )
