"""Axis A — ``cart`` probes (T1.7 — spec §5.3, §7 M1).

Five M1 ``core`` probes asserted against the storefront cart page
(``{base_url}/cart``):

* :func:`page_renders` — the ``/cart`` route returns 2xx HTML
  (rubric ``cart.page.renders``).
* :func:`shows_added_line_item` — after add-to-cart on a sample PDP, the
  cart shows the added line item (``cart.line_item.shows_after_add``).
* :func:`line_item_has_qty_editor` — cart line items expose a quantity
  editor (``cart.line_item.qty_editor``).
* :func:`line_item_has_remove` — cart line items expose a remove control
  (``cart.line_item.remove``).
* :func:`empty_state_renders` — an empty cart renders an explicit empty
  state (``cart.empty_state.present``).

The line-item probes (``shows_added_line_item``, ``line_item_has_qty_editor``,
``line_item_has_remove``) use the same flow: goto sample PDP → click ATC →
arrive on the cart → assert the relevant control. They depend on the
runner having pre-resolved a sample PDP URL; without one the probe
returns ``passed=None`` ("not_applicable").
"""

from __future__ import annotations

from urllib.parse import urljoin

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


def _cart_url(base_url: str) -> str:
    """Resolve ``base_url`` + ``/cart``, robust to trailing-slash drift."""
    return urljoin(base_url.rstrip("/") + "/", "cart")


async def page_renders(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """The ``/cart`` route renders without an HTTP error."""
    response = await page.goto(_cart_url(ctx.base_url), wait_until="domcontentloaded")
    snap = await ctx.snapshot("cart-page")
    shot = await ctx.screenshot("cart-page")
    if response is None:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no response from /cart")
    status = response.status
    body_text = (await page.locator("body").text_content()) or ""
    has_body = len(body_text.strip()) > 0
    passed = 200 <= status < 400 and has_body  # noqa: PLR2004 — HTTP success range
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"/cart returned status={status}, body_chars={len(body_text)}",
    )


async def _add_sample_to_cart(page: Page, ctx: ProbeContext) -> str | None:
    """Drive the PDP -> cart flow. Returns an error note, or None on success."""
    if ctx.sample_product_url is None:
        return "no sample_product_url provided"
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    atc = page.locator(
        'button[name="add"], button[class*="add-to-cart"], button[data-testid*="add-to-cart"], '
        'form[action*="/cart/add"] button[type="submit"]'
    ).first
    if await atc.count() == 0:
        return "no add-to-cart button on PDP"
    # Click and wait for the cart navigation. Themes may either navigate to
    # /cart or open a drawer — we explicitly land on /cart afterwards so the
    # assertion is uniform.
    await atc.click()
    await page.goto(_cart_url(ctx.base_url), wait_until="domcontentloaded")
    return None


async def shows_added_line_item(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """After clicking add-to-cart on a PDP, the cart shows the added line item."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    err = await _add_sample_to_cart(page, ctx)
    if err is not None:
        snap = await ctx.snapshot("flow-error")
        shot = await ctx.screenshot("flow-error")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes=err)
    items = page.locator(
        '[class*="cart-item"], [class*="cart__item"], [class*="line-item"], '
        '[data-testid*="cart-item"], tr[class*="cart"]'
    )
    n = await items.count()
    snap = await ctx.snapshot("cart-after-add")
    shot = await ctx.screenshot("cart-after-add")
    return ProbeOutcome(
        passed=n > 0,
        evidence=(shot, snap),
        notes=None if n > 0 else "cart shows no line items after add",
    )


async def line_item_has_qty_editor(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Cart line items expose a quantity editor."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    err = await _add_sample_to_cart(page, ctx)
    if err is not None:
        snap = await ctx.snapshot("flow-error")
        shot = await ctx.screenshot("flow-error")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes=err)
    qty = page.locator(
        'input[type="number"][name*="quantity" i], input[type="number"][name*="qty" i], '
        'input[name="updates[]"], input[aria-label*="quantity" i], '
        '[class*="qty"][role="spinbutton"], [class*="quantity-selector"] input'
    ).first
    found = await qty.count() > 0
    snap = await ctx.snapshot("qty-editor", selector="input[type=number]")
    shot = await ctx.screenshot("qty-editor", selector="input[type=number]")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no quantity editor inside cart line item",
    )


async def line_item_has_remove(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Cart line items expose a remove control."""
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    err = await _add_sample_to_cart(page, ctx)
    if err is not None:
        snap = await ctx.snapshot("flow-error")
        shot = await ctx.screenshot("flow-error")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes=err)
    remove = page.locator(
        'button[name="remove"], a[href*="/cart/change"][href*="quantity=0"], '
        'button[class*="remove"], a[class*="remove"], '
        'button[aria-label*="remove" i], a[aria-label*="remove" i], '
        '[data-testid*="remove"]'
    ).first
    found = await remove.count() > 0
    snap = await ctx.snapshot("remove", selector="[aria-label*='remove' i]")
    shot = await ctx.screenshot("remove", selector="[aria-label*='remove' i]")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no remove control inside cart line item",
    )


async def empty_state_renders(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """An empty cart renders an empty-state message rather than a blank page."""
    await page.goto(_cart_url(ctx.base_url), wait_until="domcontentloaded")
    # Check explicit empty-state markup first; fall back to text matching
    # ("empty"/"no items") inside the cart container so themes that don't
    # tag the empty state get credit.
    explicit = page.locator(
        '[class*="cart-empty"], [class*="empty-cart"], [data-testid*="empty"]'
    ).first
    if await explicit.count() > 0:
        text = (await explicit.text_content()) or ""
        snap = await ctx.snapshot("empty-state", selector='[class*="empty"]')
        shot = await ctx.screenshot("empty-state", selector='[class*="empty"]')
        passed = bool(text.strip())
        return ProbeOutcome(
            passed=passed,
            evidence=(shot, snap),
            notes=None if passed else "empty-state element has no copy",
        )
    body_text = ((await page.locator("main, body").first.text_content()) or "").lower()
    snap = await ctx.snapshot("empty-state-fallback")
    shot = await ctx.screenshot("empty-state-fallback")
    if "empty" in body_text or "no items" in body_text or "nothing in your cart" in body_text:
        return ProbeOutcome(passed=True, evidence=(shot, snap))
    return ProbeOutcome(
        passed=False,
        evidence=(shot, snap),
        notes="cart page has no recognizable empty-state copy",
    )
