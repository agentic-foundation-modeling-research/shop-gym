"""Axis A — ``dynamics`` probes (T3.3 — spec §5.3, §7 M3; v1.2 advanced tier).

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

v1.2 ``advanced`` tier — behavioral probes (spec
``web_probe_v1_2_advanced.md`` §Proposal §2):

* :func:`cart_count_badge_updates` — adding to cart updates the header
  cart-count badge text (``dynamics.cart_count_badge_updates``).
"""

from __future__ import annotations

import json

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome
from shop_probe.probes.cart import _add_sample_to_cart


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


# --------------------------------------------------------------------------- #
# v1.2 advanced (behavioral) tier
# --------------------------------------------------------------------------- #

_CART_COUNT_BADGE_SELECTOR: str = (
    'header [data-cart-count], header [class*="cart-count"], header [aria-label*="cart count" i]'
)
"""Selector union shared with :func:`cart_count_badge_present` so the
behavioral probe agrees on what counts as a badge."""


def _parse_badge_count(text: str) -> int | None:
    """Extract a non-negative integer from badge text (``"3 items"`` → 3)."""
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


async def cart_count_badge_updates(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Adding to cart updates the header cart-count badge text.

    v1.2 advanced — exercises the badge-update behaviour that
    :func:`cart_count_badge_present` only asserts the *presence* of.
    Reuses :func:`shop_probe.probes.cart._add_sample_to_cart` to drive
    the ATC flow. Returns ``passed=None`` when the storefront has no
    sample PDP or no header badge.
    """
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    badge = page.locator(_CART_COUNT_BADGE_SELECTOR).first
    if await badge.count() == 0:
        return ProbeOutcome(passed=None, notes="no header cart-count badge to observe")
    before_text = ((await badge.text_content()) or "").strip()
    before_count = _parse_badge_count(before_text)
    before_shot = await ctx.screenshot("before-badge")
    before_snap = await ctx.snapshot("before-badge")
    err = await _add_sample_to_cart(page, ctx)
    if err is not None:
        flow_shot = await ctx.screenshot("badge-flow-error")
        flow_snap = await ctx.snapshot("badge-flow-error")
        return ProbeOutcome(
            passed=False,
            evidence=(before_shot, before_snap, flow_shot, flow_snap),
            notes=f"add-to-cart flow failed: {err}",
        )
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    badge_after = page.locator(_CART_COUNT_BADGE_SELECTOR).first
    if await badge_after.count() == 0:
        after_shot = await ctx.screenshot("after-badge-missing")
        after_snap = await ctx.snapshot("after-badge-missing")
        return ProbeOutcome(
            passed=False,
            evidence=(before_shot, before_snap, after_shot, after_snap),
            notes="header badge disappeared after add-to-cart",
        )
    after_text = ((await badge_after.text_content()) or "").strip()
    after_count = _parse_badge_count(after_text)
    after_shot = await ctx.screenshot("after-badge")
    after_snap = await ctx.snapshot("after-badge")
    if before_count is not None and after_count is not None:
        passed = after_count > before_count
        notes = None if passed else f"badge count did not increase ({before_count} → {after_count})"
    else:
        passed = bool(after_text) and after_text != before_text
        notes = (
            None
            if passed
            else f"badge text unchanged after add-to-cart ({before_text!r} → {after_text!r})"
        )
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=notes,
    )
