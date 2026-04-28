"""Axis A — ``checkout`` probes (T7.4 — spec §5.9, §7 M7).

Two v1.1 ``transactional: true`` probes covering the checkout surface
that v1 deliberately leaves out (spec §5.9):

* :func:`flow_initiates` — clicking the cart's checkout call-to-action
  navigates to a checkout surface (``/checkout`` on the storefront, or a
  dedicated checkout subdomain) without erroring (rubric
  ``checkout.flow.initiates``).
* :func:`page_renders` — the ``/checkout`` route renders a checkout page
  with at least an email / contact field (rubric ``checkout.page.renders``).

These probes never attempt to complete a purchase. They exercise the
public-facing transaction surface only. They are gated behind
``shop-probe run --include-auth`` because most v1 cohort runs
intentionally skip the transactional slice.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


def _cart_url(base_url: str) -> str:
    """Resolve ``base_url`` + ``/cart``, robust to trailing-slash drift."""
    return urljoin(base_url.rstrip("/") + "/", "cart")


def _checkout_url(base_url: str) -> str:
    """Resolve ``base_url`` + ``/checkout``, robust to trailing-slash drift."""
    return urljoin(base_url.rstrip("/") + "/", "checkout")


def _is_checkout_surface(url: str, base_url: str) -> bool:
    """Return ``True`` if ``url`` looks like a checkout surface.

    Accepts both same-origin ``/checkout`` paths and dedicated checkout
    subdomains (e.g. ``checkout.example.com``). Real Shopify storefronts
    redirect to ``checkout.shopify.com`` for the transaction; the
    SandboxShop fixture stays same-origin.
    """
    base_host = urlparse(base_url).hostname or ""
    parsed = urlparse(url)
    target_host = parsed.hostname or ""
    target_path = parsed.path.rstrip("/") or "/"
    same_origin_checkout = target_host == base_host and target_path.startswith("/checkout")
    checkout_subdomain = target_host.startswith("checkout.")
    return same_origin_checkout or checkout_subdomain


async def flow_initiates(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Cart's checkout CTA navigates to a checkout surface.

    Adds a sample product to the cart, clicks the checkout button, and
    asserts that the resulting URL is either a same-origin ``/checkout``
    path or a dedicated checkout subdomain. Returns ``passed=None`` when
    the runner could not pre-resolve a sample PDP URL — without one we
    can't exercise the cart -> checkout transition.
    """
    if ctx.sample_product_url is None:
        return ProbeOutcome(passed=None, notes="no sample_product_url provided")
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    atc = page.locator(
        'button[name="add"], button[class*="add-to-cart"], button[data-testid*="add-to-cart"], '
        'form[action*="/cart/add"] button[type="submit"]'
    ).first
    if await atc.count() == 0:
        snap = await ctx.snapshot("no-atc")
        shot = await ctx.screenshot("no-atc")
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="no add-to-cart button on PDP"
        )
    await atc.click()
    await page.goto(_cart_url(ctx.base_url), wait_until="domcontentloaded")
    checkout_cta = page.locator(
        'button[name="checkout"], button[class*="checkout"], '
        'a[href*="/checkout"], a[class*="checkout"], '
        '[data-testid*="checkout-button"]'
    ).first
    if await checkout_cta.count() == 0:
        snap = await ctx.snapshot("no-checkout-cta")
        shot = await ctx.screenshot("no-checkout-cta")
        return ProbeOutcome(
            passed=False,
            evidence=(shot, snap),
            notes="no checkout CTA on cart page",
        )
    await checkout_cta.click()
    await page.wait_for_load_state("domcontentloaded")
    final_url = page.url
    snap = await ctx.snapshot("after-checkout-click")
    shot = await ctx.screenshot("after-checkout-click")
    is_checkout = _is_checkout_surface(final_url, ctx.base_url)
    return ProbeOutcome(
        passed=is_checkout,
        evidence=(shot, snap),
        notes=None if is_checkout else f"checkout CTA landed on {final_url!r}",
    )


async def page_renders(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """``/checkout`` renders a checkout page with at least an email field."""
    response = await page.goto(_checkout_url(ctx.base_url), wait_until="domcontentloaded")
    snap = await ctx.snapshot("checkout-page")
    shot = await ctx.screenshot("checkout-page")
    if response is None:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no response from /checkout")
    status = response.status
    email = page.locator(
        'input[type="email"], input[name*="email" i], input[autocomplete="email"]'
    ).first
    has_email = await email.count() > 0
    passed = 200 <= status < 400 and has_email  # noqa: PLR2004 — HTTP success range
    note = None if passed else f"/checkout status={status}, has_email_field={has_email}"
    return ProbeOutcome(passed=passed, evidence=(shot, snap), notes=note)
