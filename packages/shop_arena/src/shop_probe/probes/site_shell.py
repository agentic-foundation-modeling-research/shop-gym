"""Axis A — ``site_shell`` probes (T1.7 + T3.3 — spec §5.3, §7 M1+M3).

M1 ``core`` probes asserted against the storefront home page:

* :func:`header_is_sticky` — header stays in the viewport after a 600px
  homepage scroll (rubric ``site_shell.header.sticky``).
* :func:`header_logo_links_home` — the header logo link resolves to the
  storefront root (``site_shell.header.logo_links_home``).
* :func:`header_has_cart_link` — the header exposes a link or icon that
  navigates to ``/cart`` (``site_shell.header.cart_link``).
* :func:`nav_has_primary_collection_link` — primary navigation surfaces at
  least one ``/collections/*`` link (``site_shell.nav.primary_collection_link``).
* :func:`footer_has_link_group` — footer renders at least one labeled link
  group (``site_shell.footer.link_group``).

M3 ``modern`` probes (T3.3):

* :func:`nav_has_mega_menu` — primary nav exposes a grouped "mega menu"
  panel (``site_shell.nav.mega_menu``).

Every probe captures one viewport screenshot **and** one DOM snapshot
into the report's evidence root before returning, per spec §5.3 evidence
requirements.
"""

from __future__ import annotations

from urllib.parse import urljoin

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome

_STICKY_TOP_TOLERANCE_PX: float = -5.0
"""How far above the viewport the header may drift after scroll and still
be considered "sticky" (small negative tolerance accommodates sub-pixel
rounding from Playwright's bounding-box reads)."""


async def header_is_sticky(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Header remains visible after scrolling 600px down the homepage.

    Asserts the storefront header element is positioned ``sticky``/``fixed``
    by reading its bounding-box ``top`` after a 600px window scroll. A
    sticky/fixed header pins ``top`` near 0; a static header scrolls
    off-screen and reports a strongly negative ``top``.
    """
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    header = page.locator("header").first
    if await header.count() == 0:
        snap = await ctx.snapshot("no-header")
        shot = await ctx.screenshot("no-header")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no <header> element")
    top_before: float = await header.evaluate("el => el.getBoundingClientRect().top")
    await page.evaluate("window.scrollTo(0, 600)")
    # Allow the next paint to settle before re-measuring.
    await page.wait_for_function("window.scrollY >= 600")
    top_after: float = await header.evaluate("el => el.getBoundingClientRect().top")
    snap = await ctx.snapshot("after-scroll", selector="header")
    shot = await ctx.screenshot("after-scroll", selector="header")
    sticky = top_after >= _STICKY_TOP_TOLERANCE_PX
    note = None if sticky else f"header.top before={top_before:.1f}, after_scroll={top_after:.1f}"
    return ProbeOutcome(passed=sticky, evidence=(shot, snap), notes=note)


async def header_logo_links_home(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Header logo links back to the storefront root."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    # The first <a> inside the header is the canonical logo position; we
    # additionally accept any link explicitly tagged as the logo.
    candidate = page.locator(
        "header a.site-logo, header [class*=logo] a, header a:has(img[alt*=logo i]), header a"
    ).first
    if await candidate.count() == 0:
        snap = await ctx.snapshot("no-logo")
        shot = await ctx.screenshot("no-logo")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no <a> in <header>")
    href = await candidate.get_attribute("href")
    if href is None:
        snap = await ctx.snapshot("logo-no-href")
        shot = await ctx.screenshot("logo-no-href")
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="logo link has no href")
    resolved = urljoin(ctx.base_url, href)
    base = ctx.base_url.rstrip("/") + "/"
    points_home = resolved.rstrip("/") + "/" == base or resolved == ctx.base_url
    snap = await ctx.snapshot("logo", selector="header a")
    shot = await ctx.screenshot("logo", selector="header a")
    return ProbeOutcome(
        passed=points_home,
        evidence=(shot, snap),
        notes=None if points_home else f"logo href resolves to {resolved!r}",
    )


async def header_has_cart_link(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Header exposes a link or icon that navigates to ``/cart``."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    cart_link = page.locator(
        'header a[href$="/cart"], header a[href*="/cart?"], header a[aria-label*="cart" i]'
    ).first
    found = await cart_link.count() > 0
    snap = await ctx.snapshot("cart-link", selector='header a[href*="/cart"]')
    shot = await ctx.screenshot("cart-link", selector='header a[href*="/cart"]')
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no header link to /cart",
    )


async def nav_has_primary_collection_link(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Primary navigation surfaces at least one ``/collections/*`` link."""
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    nav_links = page.locator('header nav a[href*="/collections/"]')
    n = await nav_links.count()
    snap = await ctx.snapshot("primary-nav", selector="header nav")
    shot = await ctx.screenshot("primary-nav", selector="header nav")
    return ProbeOutcome(
        passed=n > 0,
        evidence=(shot, snap),
        notes=None if n > 0 else "no /collections/* link inside header nav",
    )


async def footer_has_link_group(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Footer renders at least one labeled link group.

    "Labeled" means either a ``<nav aria-label>`` inside ``<footer>`` or a
    list-of-links preceded by a heading (``h2``/``h3``/``h4``) — both the
    Dawn-style "footer link group" patterns we expect on a real storefront.
    """
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    labeled_nav = page.locator("footer nav[aria-label]").first
    headed_list = page.locator("footer :is(h2, h3, h4) ~ ul a").first
    has_labeled_nav = await labeled_nav.count() > 0
    has_headed_list = await headed_list.count() > 0
    passed = has_labeled_nav or has_headed_list
    snap = await ctx.snapshot("footer", selector="footer")
    shot = await ctx.screenshot("footer", selector="footer")
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else "no labeled link group in <footer>",
    )


async def nav_has_mega_menu(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Primary nav exposes a grouped "mega menu" panel.

    The mega-menu shape we recognize: a nav element marked with
    ``data-mega-menu`` (or a ``[class*="mega-menu"]`` container) that
    holds a panel with at least two grouped child links — i.e. more
    structure than a flat link list.
    """
    await page.goto(ctx.base_url, wait_until="domcontentloaded")
    container = page.locator(
        "header nav [data-mega-menu], header nav [class*='mega-menu'], header [data-mega-menu]"
    ).first
    if await container.count() == 0:
        snap = await ctx.snapshot("no-mega-menu")
        shot = await ctx.screenshot("no-mega-menu")
        return ProbeOutcome(
            passed=False, evidence=(shot, snap), notes="no mega-menu container in header nav"
        )
    panel_links = container.locator("[class*='panel'] a, [class*='group'] a")
    n_links = await panel_links.count()
    snap = await ctx.snapshot("mega-menu", selector="[data-mega-menu]")
    shot = await ctx.screenshot("mega-menu", selector="[data-mega-menu]")
    passed = n_links >= 2  # noqa: PLR2004 — at least two grouped links
    return ProbeOutcome(
        passed=passed,
        evidence=(shot, snap),
        notes=None if passed else f"mega-menu has only {n_links} grouped links",
    )
