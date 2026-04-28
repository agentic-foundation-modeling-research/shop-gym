"""Axis A — ``i18n`` probes (T3.3 — spec §5.3, §7 M3).

Probes for internationalization affordances:

* :func:`has_locale_switcher` — a language / locale selector exists
  (``i18n.locale_switcher``).
* :func:`has_currency_switcher` — a currency selector exists
  (``i18n.currency_switcher``).
* :func:`has_country_list` — a country / market selector exists
  (``i18n.country_list``).

These are all merchant-controlled affordances; storefronts without
them legitimately fail the probe.
"""

from __future__ import annotations

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


async def has_locale_switcher(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Storefront exposes a language / locale switcher."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    switcher = page.locator(
        'select[name*="locale" i], select[aria-label*="language" i], '
        'select[aria-label*="locale" i], '
        '[class*="locale-switcher"], [class*="language-switcher"], '
        "[data-locale-switcher]"
    ).first
    found = await switcher.count() > 0
    snap = await ctx.snapshot("locale-switcher")
    shot = await ctx.screenshot("locale-switcher")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no locale / language switcher found",
    )


async def has_currency_switcher(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Storefront exposes a currency switcher."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    switcher = page.locator(
        'select[name*="currency" i], select[aria-label*="currency" i], '
        '[class*="currency-switcher"], [data-currency-switcher]'
    ).first
    found = await switcher.count() > 0
    snap = await ctx.snapshot("currency-switcher")
    shot = await ctx.screenshot("currency-switcher")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no currency switcher found",
    )


async def has_country_list(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Storefront exposes a country / market selector."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    selector = page.locator(
        'select[name*="country" i], select[aria-label*="country" i], '
        '[class*="country-selector"], [class*="market-selector"], '
        "[data-country-selector]"
    ).first
    found = await selector.count() > 0
    snap = await ctx.snapshot("country-list")
    shot = await ctx.screenshot("country-list")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no country / market selector found",
    )
