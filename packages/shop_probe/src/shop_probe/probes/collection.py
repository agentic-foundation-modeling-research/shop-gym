"""Axis A — ``collection`` probes (T1.7 — spec §5.3, §7 M1).

Five M1 ``core`` probes asserted against a sample collection listing
URL handed to the runner via :attr:`ProbeContext.sample_collection_url`:

* :func:`has_product_cards` — at least one card with image + title + price
  (rubric ``collection.listing.product_cards``).
* :func:`product_card_links_to_pdp` — every product card links to
  ``/products/*`` (``collection.listing.product_card_links_to_pdp``).
* :func:`has_filters` — at least one filter control is present
  (``collection.listing.has_filters``).
* :func:`has_sort_control` — a sort control is present
  (``collection.listing.has_sort``).
* :func:`has_pagination_or_infinite_scroll` — pagination, infinite scroll,
  or load-more is present (``collection.pagination.present``).

All probes capture a screenshot + DOM snapshot before returning. When the
runner could not pre-resolve a sample collection URL the probe returns
``passed=None`` ("not_applicable") per the contract on
:class:`ProbeContext`.
"""

from __future__ import annotations

from urllib.parse import urlparse

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


async def has_product_cards(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection page renders at least one card with image + title + price."""
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    # Broad selector — we accept the common Shopify card class patterns plus
    # the semantic <article>/<li> shapes Dawn-derived themes expose.
    cards = page.locator(
        '[class*="product-card"], article[class*="card"], '
        'li[class*="grid__item"]:has(a[href*="/products/"])'
    )
    n_cards = await cards.count()
    snap = await ctx.snapshot("listing")
    shot = await ctx.screenshot("listing")
    if n_cards == 0:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no product cards")
    # At least one card must have all three: image, title-like text, price-like text.
    valid_cards = 0
    for i in range(n_cards):
        card = cards.nth(i)
        has_img = await card.locator("img").count() > 0
        has_title = await card.locator(":is(h1, h2, h3, h4, h5, [class*=title])").count() > 0
        has_price = await card.locator('[class*="price"]').count() > 0
        if has_img and has_title and has_price:
            valid_cards += 1
    passed = valid_cards > 0
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"{n_cards} cards, none had image+title+price",
    )


async def product_card_links_to_pdp(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Every product card on a collection page links to a ``/products/*`` URL."""
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    # Pull every anchor inside any element that looks like a product card.
    card_anchors = page.locator(
        '[class*="product-card"] a[href], article[class*="card"] a[href], '
        'li[class*="grid__item"] a[href]'
    )
    n = await card_anchors.count()
    snap = await ctx.snapshot("listing")
    shot = await ctx.screenshot("listing")
    if n == 0:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no product card anchors")
    bad: list[str] = []
    for i in range(n):
        href = await card_anchors.nth(i).get_attribute("href")
        if href is None:
            continue
        path = urlparse(href).path
        if not path.startswith("/products/"):
            bad.append(href)
    passed = len(bad) == 0
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"{len(bad)} card links not under /products/: {bad[:3]}",
    )


async def has_filters(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection page exposes at least one filter control."""
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    # Filter UIs vary widely (sidebar, accordion, popover). We look for
    # any input grouped under a fieldset or any element explicitly tagged
    # as a filter.
    filter_inputs = page.locator(
        'fieldset input[type="checkbox"], fieldset input[type="radio"], '
        '[class*="filter"] input, [data-testid*="filter"], [aria-label*="filter" i]'
    )
    n = await filter_inputs.count()
    snap = await ctx.snapshot("filters")
    shot = await ctx.screenshot("filters")
    return ProbeOutcome(
        passed=n > 0,
        evidence=(shot, snap),
        notes=None if n > 0 else "no filter controls found",
    )


async def has_sort_control(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection page exposes a sort control."""
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    # Sort UI varies: <select>, custom popover button, or any element
    # explicitly tagged as a sort. We accept any of these.
    sort_control = page.locator(
        'select[id*="sort" i], select[name*="sort" i], select[aria-label*="sort" i], '
        'button[aria-label*="sort" i], [class*="sort"]:is(select, button)'
    ).first
    found = await sort_control.count() > 0
    snap = await ctx.snapshot("sort")
    shot = await ctx.screenshot("sort")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no sort control found",
    )


async def has_pagination_or_infinite_scroll(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection page exposes pagination, infinite scroll, or load-more.

    Spec §5.3 lists pagination / infinite-scroll / load-more as the three
    alternative shapes. We accept any of them — themes pick one. The probe
    is lenient: a single positive signal passes.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    pagination = page.locator(
        'nav[aria-label*="pagination" i], nav[aria-label*="page" i], '
        '[class*="pagination"], [data-testid*="pagination"], '
        'a[rel="next"], button:has-text("Load more"), button:has-text("Show more"), '
        '[data-testid*="load-more"], [class*="load-more"], [class*="infinite-scroll"]'
    ).first
    found = await pagination.count() > 0
    snap = await ctx.snapshot("pagination")
    shot = await ctx.screenshot("pagination")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no pagination/infinite-scroll/load-more control",
    )
