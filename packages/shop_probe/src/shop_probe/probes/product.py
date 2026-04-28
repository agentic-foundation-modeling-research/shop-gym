"""Axis A — ``product`` probes (T1.7 — spec §5.3, §7 M1).

Five M1 ``core`` probes asserted against a sample PDP URL handed to the
runner via :attr:`ProbeContext.sample_product_url`:

* :func:`gallery_has_image` — at least one product image renders
  (rubric ``product.gallery.image``).
* :func:`has_title` — the product title (``<h1>``) renders
  (``product.title.present``).
* :func:`has_price` — a product price renders (``product.price.present``).
* :func:`has_add_to_cart_button` — an enabled add-to-cart button is present
  (``product.add_to_cart.button``).
* :func:`has_description` — a product description block renders
  (``product.description.present``).

All probes capture a screenshot + DOM snapshot before returning. When the
runner could not pre-resolve a sample PDP URL the probe returns
``passed=None`` ("not_applicable") per the contract on
:class:`ProbeContext`.
"""

from __future__ import annotations

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


async def gallery_has_image(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Product detail page renders at least one product image."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    # The PDP "main image" lives inside <main> (or a gallery container).
    # We accept any <img> that isn't an icon / a11y-only image: needs a src
    # and a non-zero rendered box.
    img = page.locator(
        'main img, [class*="product-gallery"] img, [class*="product-media"] img'
    ).first
    if await img.count() == 0:
        snap = await ctx.snapshot("no-image")
        shot = await ctx.screenshot("no-image")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no product gallery image")
    src = await img.get_attribute("src")
    box = await img.bounding_box()
    snap = await ctx.snapshot("gallery", selector="main img")
    shot = await ctx.screenshot("gallery", selector="main img")
    if not src:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="gallery <img> has no src")
    if box is None or box["width"] < 1 or box["height"] < 1:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="gallery <img> not rendered")
    return ProbeOutcome(passed=True, evidence=(shot, snap))


async def has_title(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Product detail page renders the product title."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    h1 = page.locator("main h1, h1[class*='product-title'], h1[class*='product__title']").first
    if await h1.count() == 0:
        snap = await ctx.snapshot("no-title")
        shot = await ctx.screenshot("no-title")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no <h1> on PDP")
    text = (await h1.text_content()) or ""
    snap = await ctx.snapshot("title", selector="h1")
    shot = await ctx.screenshot("title", selector="h1")
    if not text.strip():
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="<h1> is empty")
    return ProbeOutcome(passed=True, evidence=(shot, snap))


async def has_price(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Product detail page renders the product price."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    price = page.locator('[class*="price"], [data-testid*="price"], [itemprop="price"]').first
    if await price.count() == 0:
        snap = await ctx.snapshot("no-price")
        shot = await ctx.screenshot("no-price")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no element tagged as price")
    text = (await price.text_content()) or ""
    snap = await ctx.snapshot("price", selector='[class*="price"]')
    shot = await ctx.screenshot("price", selector='[class*="price"]')
    # Dawn's "{{ product.price | money }}" lands as e.g. "$10.00", "€10",
    # "¥100" — accept any string with a digit and at least one currency-ish
    # marker (currency symbol, ISO code, or "free").
    has_digit = any(ch.isdigit() for ch in text)
    has_money_marker = (
        any(sym in text for sym in ("$", "€", "£", "¥", "₹", "kr", "USD", "EUR", "GBP", "CAD"))
        or "free" in text.lower()
    )
    passed = has_digit and has_money_marker
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"price text={text.strip()[:40]!r} did not look like a price",
    )


async def has_add_to_cart_button(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Product detail page exposes an enabled add-to-cart button."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    atc = page.locator(
        'button[name="add"], button[class*="add-to-cart"], button[data-testid*="add-to-cart"], '
        'form[action*="/cart/add"] button[type="submit"], [data-testid="atc"]'
    ).first
    if await atc.count() == 0:
        snap = await ctx.snapshot("no-atc")
        shot = await ctx.screenshot("no-atc")
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="no add-to-cart button found"
        )
    is_disabled = await atc.is_disabled()
    snap = await ctx.snapshot("atc", selector="button[type='submit']")
    shot = await ctx.screenshot("atc", selector="button[type='submit']")
    return ProbeOutcome(
        passed=not is_disabled,
        evidence=(shot, snap),
        notes=None if not is_disabled else "add-to-cart button is disabled",
    )


async def has_description(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Product detail page renders a product description block."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    description = page.locator(
        '[class*="product-description"], [class*="product__description"], '
        '[data-testid*="description"], [itemprop="description"]'
    ).first
    if await description.count() == 0:
        snap = await ctx.snapshot("no-description")
        shot = await ctx.screenshot("no-description")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no description block found")
    text = (await description.text_content()) or ""
    snap = await ctx.snapshot("description", selector='[class*="description"]')
    shot = await ctx.screenshot("description", selector='[class*="description"]')
    if len(text.strip()) < 10:  # noqa: PLR2004 — "any non-trivial copy"
        return ProbeOutcome(
            passed=False,
            evidence=(shot, snap),
            notes=f"description block has trivial copy ({len(text.strip())} chars)",
        )
    return ProbeOutcome(passed=True, evidence=(shot, snap))
