"""Axis A — ``dynamics`` probes (T3.3 — spec §5.3, §7 M3).

Probes for runtime / interaction-shape signals that go beyond static
markup:

* :func:`has_toast_region` — page exposes a live ``role="status"`` /
  ``aria-live`` region for toast messages (``dynamics.toast_region``).
* :func:`url_state_sync_present` — collection filters carry their state
  in the URL via anchors or a GET form (``dynamics.url_state_sync``).
* :func:`debounced_input_present` — a search-shaped input declares an
  explicit debounce attribute (``dynamics.debounced_input``).
* :func:`ajax_cart_endpoint_discoverable` — ``/cart.js`` (or equivalent)
  returns a JSON cart payload (``dynamics.ajax_cart_endpoint``).
* :func:`cart_count_badge_present` — header carries an updatable
  cart-count badge (``dynamics.cart_count_badge``).
"""

from __future__ import annotations

import json

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


async def has_toast_region(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Page exposes a live region for toast / snackbar messages."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    region = page.locator(
        '[role="status"][aria-live], [role="alert"][aria-live], '
        '[class*="toast"][aria-live], [data-toast-region]'
    ).first
    found = await region.count() > 0
    snap = await ctx.snapshot("toast-region")
    shot = await ctx.screenshot("toast-region")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no role=status/alert + aria-live toast region found",
    )


async def url_state_sync_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection filters carry state in the URL (anchor or GET form)."""
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    anchors = page.locator('[class*="filter"] a[href*="?"], [class*="filter"] a[href*="&"]')
    has_anchors = await anchors.count() > 0
    get_form = page.locator(
        'form[method="get" i][class*="filter"], form[method="get" i] [name*="filter"], '
        '[class*="filter"] form[method="get" i]'
    ).first
    has_get_form = await get_form.count() > 0
    snap = await ctx.snapshot("url-state-sync")
    shot = await ctx.screenshot("url-state-sync")
    passed = has_anchors or has_get_form
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None
        if passed
        else "filters do not encode state in URL (no ?query anchor or form[method=get])",
    )


async def debounced_input_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """A search-shaped input declares an explicit debounce attribute."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    debounced = page.locator(
        "input[data-debounce], input[data-debounce-time], "
        "input[data-search-debounce], "
        'input[type="search"][data-debounce]'
    ).first
    found = await debounced.count() > 0
    snap = await ctx.snapshot("debounced-input")
    shot = await ctx.screenshot("debounced-input")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no input carries a data-debounce* attribute",
    )


async def ajax_cart_endpoint_discoverable(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """``/cart.js`` returns a JSON cart payload."""
    base = ctx.base_url.rstrip("/")
    response = await page.request.get(f"{base}/cart.js")
    snap = await ctx.snapshot("ajax-cart")
    shot = await ctx.screenshot("ajax-cart")
    if not response.ok:
        return ProbeOutcome(
            passed=False,
            evidence=(shot, snap),
            notes=f"/cart.js returned status={response.status}",
        )
    body = await response.text()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="/cart.js body is not JSON")
    passed = isinstance(payload, dict) and ("item_count" in payload or "items" in payload)
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else "/cart.js JSON missing item_count/items keys",
    )


async def cart_count_badge_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Header carries an updatable cart-count badge."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    badge = page.locator(
        'header [data-cart-count], header [class*="cart-count"], '
        'header [aria-label*="cart count" i]'
    ).first
    found = await badge.count() > 0
    snap = await ctx.snapshot("cart-count-badge")
    shot = await ctx.screenshot("cart-count-badge")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no header cart-count badge",
    )
