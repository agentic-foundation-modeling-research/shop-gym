"""Axis A — ``homepage`` probes (T3.3 — spec §5.3, §7 M3).

Probes asserted against the storefront home page (``/``):

* :func:`has_hero_section` — homepage opens with a hero banner
  (``homepage.hero.present``).
* :func:`has_cta_to_collection` — homepage links to a ``/collections/*``
  destination via a labeled CTA (``homepage.cta_to_collection``).
* :func:`has_feature_grid` — homepage renders a feature / product grid
  with at least two cards (``homepage.feature_grid``).
* :func:`has_testimonial_section` — homepage renders a testimonials /
  reviews block (``homepage.testimonials``).
* :func:`multiple_section_types` — homepage renders ≥ 3 distinct section
  types (``homepage.multiple_section_types``).

All probes capture a screenshot + DOM snapshot before returning.
"""

from __future__ import annotations

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome

_MIN_SECTION_TYPES: int = 3
"""Minimum distinct ``data-section-type`` / ``[class*=section-]`` types
to count as a multi-section homepage (spec §5.3 example)."""


async def has_hero_section(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Homepage opens with a hero banner section."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    hero = page.locator(
        'section[class*="hero"], [data-section-type="hero"], section[class*="banner"]'
    ).first
    if await hero.count() == 0:
        snap = await ctx.snapshot("no-hero")
        shot = await ctx.screenshot("no-hero")
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="no hero section on homepage"
        )
    has_heading = await hero.locator(":is(h1, h2)").count() > 0
    has_image = await hero.locator("img").count() > 0
    snap = await ctx.snapshot("hero", selector="section[class*=hero]")
    shot = await ctx.screenshot("hero", selector="section[class*=hero]")
    passed = has_heading or has_image
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else "hero section has no heading or image",
    )


async def has_cta_to_collection(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Homepage exposes a labeled call-to-action linking to ``/collections/*``."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    cta = page.locator(
        'main a[href*="/collections/"], main [class*="cta"][href*="/collections/"]'
    ).first
    if await cta.count() == 0:
        snap = await ctx.snapshot("no-cta")
        shot = await ctx.screenshot("no-cta")
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="no homepage CTA to /collections/*"
        )
    text = ((await cta.text_content()) or "").strip()
    snap = await ctx.snapshot("cta", selector='main a[href*="/collections/"]')
    shot = await ctx.screenshot("cta", selector='main a[href*="/collections/"]')
    if not text:
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="homepage CTA has no link text"
        )
    return ProbeOutcome(passed=True, evidence=(shot, snap))


async def has_feature_grid(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Homepage renders a feature / featured-product grid with ≥ 2 cards."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    grid = page.locator(
        'main [class*="feature-grid"], main [class*="featured-collection"], '
        'main [class*="feature__grid"], '
        'main section[class*="featured"] ul'
    ).first
    if await grid.count() == 0:
        snap = await ctx.snapshot("no-feature-grid")
        shot = await ctx.screenshot("no-feature-grid")
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="no feature grid on homepage"
        )
    cards = grid.locator('[class*="card"], [class*="grid__item"], li, a[href*="/products/"]')
    n = await cards.count()
    snap = await ctx.snapshot("feature-grid")
    shot = await ctx.screenshot("feature-grid")
    passed = n >= 2  # noqa: PLR2004 — a "grid" needs at least two cells
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"feature grid has only {n} cards",
    )


async def has_testimonial_section(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Homepage renders a testimonials / reviews / quotes section."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    section = page.locator(
        'section[class*="testimonial"], section[class*="review"], '
        'section[class*="quote"], [data-section-type*="testimonial"], '
        "main blockquote"
    ).first
    found = await section.count() > 0
    snap = await ctx.snapshot("testimonial")
    shot = await ctx.screenshot("testimonial")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no testimonial / review section on homepage",
    )


async def multiple_section_types(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Homepage renders ≥ 3 distinct section types (spec §5.3 example)."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    section_types: set[str] = set()
    # Shopify's section blocks expose ``data-section-type``; theme variants
    # expose distinct ``class`` tokens — we collect both.
    for marker in await page.locator("main [data-section-type]").all():
        marker_type = await marker.get_attribute("data-section-type")
        if marker_type:
            section_types.add(f"data:{marker_type}")
    for section in await page.locator("main section").all():
        klass = (await section.get_attribute("class")) or ""
        if klass:
            section_types.add(f"class:{klass.split()[0]}")
    snap = await ctx.snapshot("sections")
    shot = await ctx.screenshot("sections")
    passed = len(section_types) >= _MIN_SECTION_TYPES
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"only {len(section_types)} distinct section types",
    )
