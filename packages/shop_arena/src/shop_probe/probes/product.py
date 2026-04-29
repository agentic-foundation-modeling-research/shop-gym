"""Axis A — ``product`` probes (T1.7 — spec §5.3, §7 M1; v1.2 advanced tier).

Presence probes asserted against a sample PDP URL handed to the runner
via :attr:`ProbeContext.sample_product_url`:

* :func:`gallery_has_image` — at least one product image renders
  (rubric ``product.gallery.image``).
* :func:`has_title` — the product title (``<h1>``) renders
  (``product.title.present``).
* :func:`has_price` — a product price renders (``product.price.present``).
* :func:`has_add_to_cart_button` — an enabled add-to-cart button is present
  (``product.add_to_cart.button``).
* :func:`has_description` — a product description block renders
  (``product.description.present``).
* :func:`gallery_has_thumbnails` — gallery thumbnail strip ≥ 2 thumbnails.
* :func:`has_variant_selector` — radio / select / swatch variant control.
* :func:`has_quantity_spinner` — numeric quantity spinner.
* :func:`has_breadcrumbs` — breadcrumb trail.
* :func:`has_recommendations` — "you may also like" section.

v1.2 ``advanced`` tier — behavioral probes (spec
``web_probe_v1_2_advanced.md`` §Proposal §2):

* :func:`variant_swap_updates_state` — clicking the second variant changes
  price text or main gallery image (``product.variant.swap_updates_state``).
* :func:`qty_spinner_increments` — incrementing the qty spinner raises its
  value (``product.qty.spinner_increments``).

Advanced probes return ``passed=None`` when the storefront does not expose
the surface required to drive the interaction (e.g. a single-variant PDP
cannot exercise variant swap).
"""

from __future__ import annotations

import contextlib

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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


async def gallery_has_thumbnails(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """PDP gallery exposes a thumbnail strip (spec §8.1 example).

    A gallery counts as "having thumbnails" when at least two thumbnail
    triggers exist — a one-image gallery has nothing to swap to.
    """
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    thumbs = page.locator(
        '[role="tablist"] [role="tab"], '
        '[class*="product-gallery"] [class*="thumb"], '
        '[class*="gallery__thumbnails"] button, '
        '[class*="gallery__thumbnails"] li'
    )
    n = await thumbs.count()
    snap = await ctx.snapshot("thumbnails")
    shot = await ctx.screenshot("thumbnails")
    passed = n >= 2  # noqa: PLR2004 — gallery needs at least two thumbs to swap
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"only {n} thumbnails (need at least 2)",
    )


async def has_variant_selector(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """PDP exposes a variant selector (radio swatches / select / dropdown)."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    # Accept the common shapes: radio group, swatch fieldset, variant <select>.
    selector = page.locator(
        'fieldset[class*="variant"], [data-variant-selector], '
        'input[type="radio"][name*="variant" i], input[type="radio"][name*="option" i], '
        'select[name*="variant" i], select[name*="option" i], '
        '[class*="swatch"] input[type="radio"]'
    )
    found = await selector.count() > 0
    snap = await ctx.snapshot("variant-selector")
    shot = await ctx.screenshot("variant-selector")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no variant selector (radio/select/swatch) on PDP",
    )


async def has_quantity_spinner(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """PDP exposes a numeric quantity spinner."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    qty = page.locator(
        'input[type="number"][name*="quantity" i], input[type="number"][name*="qty" i], '
        '[class*="quantity-selector"] input[type="number"], '
        '[class*="qty"][role="spinbutton"]'
    ).first
    found = await qty.count() > 0
    snap = await ctx.snapshot("qty-spinner")
    shot = await ctx.screenshot("qty-spinner")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no quantity spinner on PDP",
    )


async def has_breadcrumbs(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """PDP renders a breadcrumb trail."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    crumbs = page.locator(
        'nav[aria-label*="breadcrumb" i], [class*="breadcrumb"], [itemtype$="BreadcrumbList"]'
    ).first
    found = await crumbs.count() > 0
    snap = await ctx.snapshot("breadcrumbs")
    shot = await ctx.screenshot("breadcrumbs")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no breadcrumb nav on PDP",
    )


async def has_recommendations(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """PDP renders a "you may also like" / recommendations section."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    section = page.locator(
        '[class*="recommend"], [class*="related-product"], '
        'section[aria-label*="recommend" i], section[aria-label*="related" i]'
    ).first
    if await section.count() == 0:
        snap = await ctx.snapshot("no-recommendations")
        shot = await ctx.screenshot("no-recommendations")
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="no recommendations section on PDP"
        )
    n_cards = await section.locator('[class*="product-card"], a[href*="/products/"]').count()
    snap = await ctx.snapshot("recommendations")
    shot = await ctx.screenshot("recommendations")
    passed = n_cards > 0
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else "recommendations section is empty",
    )


# --------------------------------------------------------------------------- #
# v1.2 advanced (behavioral) tier
# --------------------------------------------------------------------------- #

_BEHAVIORAL_WAIT_MS: int = 3000
"""Hard ceiling on per-interaction waits in advanced probes (3 s).

Stays well under the 10-s default probe timeout in
:mod:`shop_probe.probes._runner` so a missing UI event bubbles up as a
clean ``False`` rather than a timeout."""

_VARIANT_OPTION_SELECTOR: str = (
    'input[type="radio"][name*="variant" i], input[type="radio"][name*="option" i], '
    '[class*="swatch"] input[type="radio"], '
    'fieldset[class*="variant"] label, [class*="swatch"] label'
)
"""Selector union for clickable variant options (radio inputs / swatch labels).

Mirrors :func:`has_variant_selector` so the behavioral probe agrees with
the presence probe about what counts as a variant control."""


async def variant_swap_updates_state(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Clicking a second variant updates the price text or gallery image.

    v1.2 advanced — exercises the variant behaviour that
    :func:`has_variant_selector` only asserts the *presence* of. Returns
    ``passed=None`` when the PDP exposes fewer than 2 variant options.
    """
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    options = page.locator(_VARIANT_OPTION_SELECTOR)
    n_options = await options.count()
    if n_options < 2:  # noqa: PLR2004 — need at least 2 options to swap
        return ProbeOutcome(
            passed=None,
            notes=f"only {n_options} variant option(s); cannot exercise swap",
        )
    price = page.locator('[class*="price"], [data-testid*="price"], [itemprop="price"]').first
    gallery_img = page.locator(
        'main img, [class*="product-gallery"] img, [class*="product-media"] img'
    ).first
    before_price = ((await price.text_content()) or "").strip() if await price.count() else ""
    before_src = (await gallery_img.get_attribute("src")) or "" if await gallery_img.count() else ""
    if not before_price and not before_src:
        return ProbeOutcome(
            passed=None,
            notes="PDP exposes neither a price nor a gallery image to compare against",
        )
    before_shot = await ctx.screenshot("before-variant-swap")
    before_snap = await ctx.snapshot("before-variant-swap")
    target = options.nth(1)
    try:
        async with page.expect_navigation(
            wait_until="domcontentloaded", timeout=_BEHAVIORAL_WAIT_MS
        ):
            await target.click(timeout=_BEHAVIORAL_WAIT_MS)
    except PlaywrightTimeoutError:
        # Most modern variant pickers re-render in place; wait briefly.
        await page.wait_for_timeout(500)
    after_price = ((await price.text_content()) or "").strip() if await price.count() else ""
    after_src = (await gallery_img.get_attribute("src")) or "" if await gallery_img.count() else ""
    after_shot = await ctx.screenshot("after-variant-swap")
    after_snap = await ctx.snapshot("after-variant-swap")
    price_changed = before_price != after_price
    src_changed = before_src != after_src
    passed = price_changed or src_changed
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=None
        if passed
        else (
            f"variant click had no effect "
            f"(price {before_price[:30]!r}→{after_price[:30]!r}, "
            f"img src unchanged)"
        ),
    )


async def qty_spinner_increments(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Incrementing the qty spinner raises its numeric value.

    v1.2 advanced — exercises the qty-spinner behaviour that
    :func:`has_quantity_spinner` only asserts the *presence* of. Tries the
    visible ``+`` button first; falls back to ``HTMLInputElement.stepUp()``
    so themes with a custom button shape still pass. Returns
    ``passed=None`` when no qty input is present.
    """
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    qty_input = page.locator(
        'input[type="number"][name*="quantity" i], input[type="number"][name*="qty" i], '
        '[class*="quantity-selector"] input[type="number"], '
        '[class*="qty"][role="spinbutton"]'
    ).first
    if await qty_input.count() == 0:
        return ProbeOutcome(passed=None, notes="no quantity spinner on PDP")
    before_value_str = (await qty_input.input_value()) or ""
    try:
        before_value = int(before_value_str.strip() or "1")
    except ValueError:
        return ProbeOutcome(
            passed=None,
            notes=f"qty spinner value {before_value_str!r} is not numeric",
        )
    before_shot = await ctx.screenshot("before-qty")
    before_snap = await ctx.snapshot("before-qty")
    plus_button = page.locator(
        'button[name="plus"], button[class*="quantity__button"][class*="plus"], '
        'button[aria-label*="increase" i], button[data-action="increment"], '
        '[class*="quantity-selector"] button:has-text("+")'
    ).first
    if await plus_button.count() > 0 and await plus_button.is_enabled():
        with contextlib.suppress(PlaywrightTimeoutError):
            await plus_button.click(timeout=_BEHAVIORAL_WAIT_MS)
    else:
        # No clickable + button: drive the input via stepUp() so themes that
        # only ship the bare <input type="number"> can still satisfy the probe.
        await qty_input.evaluate("(el) => el.stepUp()")
        await qty_input.dispatch_event("change")
    after_value_str = (await qty_input.input_value()) or ""
    after_shot = await ctx.screenshot("after-qty")
    after_snap = await ctx.snapshot("after-qty")
    try:
        after_value = int(after_value_str.strip() or "0")
    except ValueError:
        return ProbeOutcome(
            passed=False,
            evidence=(before_shot, before_snap, after_shot, after_snap),
            notes=f"qty value after increment is non-numeric: {after_value_str!r}",
        )
    passed = after_value > before_value
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=None if passed else f"qty value did not increase ({before_value} → {after_value})",
    )
