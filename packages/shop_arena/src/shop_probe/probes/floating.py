"""Axis A — ``floating`` probes (T3.3 — spec §5.3, §7 M3).

Probes for the floating overlay layer that real-world storefronts
typically render on top of the main shell:

* :func:`has_cookie_consent` — cookie / privacy consent banner is
  present (``floating.cookie_consent``).
* :func:`has_newsletter_popup` — newsletter signup popup / dialog is
  present (``floating.newsletter_popup``).
* :func:`has_chat_widget` — a chat-widget launcher is present
  (``floating.chat_widget``).
"""

from __future__ import annotations

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


async def has_cookie_consent(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Storefront renders a cookie / privacy consent affordance."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    banner = page.locator(
        '[class*="cookie"], [data-cookie-consent], '
        '[aria-label*="cookie" i], [aria-label*="privacy" i], '
        '[id*="cookie"][role="dialog"]'
    ).first
    found = await banner.count() > 0
    snap = await ctx.snapshot("cookie-banner")
    shot = await ctx.screenshot("cookie-banner")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no cookie / privacy consent affordance found",
    )


async def has_newsletter_popup(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Storefront renders a newsletter signup popup / dialog."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    popup = page.locator(
        '[class*="newsletter"], [data-newsletter-popup], '
        '[aria-label*="newsletter" i], [aria-label*="subscribe" i], '
        'dialog[class*="newsletter"]'
    ).first
    found = await popup.count() > 0
    snap = await ctx.snapshot("newsletter-popup")
    shot = await ctx.screenshot("newsletter-popup")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no newsletter popup / dialog found",
    )


async def has_chat_widget(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Storefront renders a chat-widget launcher."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    launcher = page.locator(
        '[class*="chat-widget"], [class*="chat-launcher"], '
        "[data-chat-widget], "
        '[aria-label*="chat" i], [id*="chat-launcher"]'
    ).first
    found = await launcher.count() > 0
    snap = await ctx.snapshot("chat-widget")
    shot = await ctx.screenshot("chat-widget")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no chat-widget launcher found",
    )
