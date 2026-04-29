"""Axis A — ``collection`` probes (T1.7 — spec §5.3, §7 M1; v1.2 advanced tier).

Presence probes asserted against a sample collection listing URL handed to
the runner via :attr:`ProbeContext.sample_collection_url`:

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
* :func:`has_sidebar_filter_layout` — filters live in an aside / sidebar.
* :func:`filters_sync_to_url_state` — filters are link- or GET-form-shaped.
* :func:`has_active_filter_chips` — page exposes an active-filter chip area.

v1.2 ``advanced`` tier — behavioral probes that drive the interaction and
assert page state changes (spec ``web_probe_v1_2_advanced.md`` §Proposal §2):

* :func:`sort_changes_order` — toggling the sort control changes the first
  product card's title (``collection.sort.changes_order``).
* :func:`filters_apply_to_results` — clicking a filter changes the visible
  card count or URL (``collection.filters.applies_to_results``).
* :func:`pagination_advances` — clicking pagination next / load-more loads
  different cards (``collection.pagination.advances``).
* :func:`filter_click_advances_url` — clicking a filter mutates ``page.url``
  (``collection.filters.url_state_advances``).

All probes capture a screenshot + DOM snapshot before returning. When the
runner could not pre-resolve a sample collection URL, or the storefront
does not expose the surface required to drive the interaction (no sort
``<select>``, < 2 product cards, etc.), advanced probes return
``passed=None`` ("not_applicable") per the contract on
:class:`ProbeContext`.
"""

from __future__ import annotations

from urllib.parse import urlparse

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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


async def has_sidebar_filter_layout(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection page renders filters inside an ``<aside>`` / sidebar layout.

    Distinct from :func:`has_filters` — this asserts the *shape* of the
    filter UI (sidebar) rather than only the presence of filter inputs.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    sidebar = page.locator(
        'aside[class*="filter"], aside[aria-label*="filter" i], '
        '[class*="sidebar-filters"], [class*="filters-sidebar"]'
    ).first
    found = await sidebar.count() > 0
    snap = await ctx.snapshot("sidebar")
    shot = await ctx.screenshot("sidebar")
    return ProbeOutcome(
        passed=found,
        evidence=(shot, snap),
        notes=None if found else "no sidebar/aside-shaped filter container",
    )


async def filters_sync_to_url_state(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection filters expose URL-state-sync (link-based or form GET).

    Spec §5.3 calls this out explicitly. Themes implement it via either
    a) anchors that point to the same path with a query string, or
    b) a ``<form method="get">`` whose action lands on the same path.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    # Anchor-based filter (e.g. <a href="?type=t-shirt">).
    filter_anchors = page.locator('[class*="filter"] a[href*="?"], [class*="filter"] a[href*="&"]')
    has_anchors = await filter_anchors.count() > 0
    # Form-based filter using GET.
    get_form = page.locator(
        'form[method="get" i][class*="filter"], form[method="get" i] [name*="filter"], '
        'form[method="get" i] [class*="filter"]'
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
        else "no URL-state-sync filter (anchor with ?query nor form[method=get])",
    )


async def has_active_filter_chips(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Collection page exposes active-filter chips when filters are applied.

    The fixture exposes them by default; on a real storefront this is
    only visible after a filter is applied. We probe for the presence of
    a chip-shaped container (``[class*="active-filter"]`` or an
    ``aria-label`` match) — themes that lack them legitimately fail.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    chips = page.locator(
        '[class*="active-filter"], [class*="filter-chip"], '
        '[aria-label*="active filter" i], [data-active-filter]'
    )
    n = await chips.count()
    snap = await ctx.snapshot("active-chips")
    shot = await ctx.screenshot("active-chips")
    return ProbeOutcome(
        passed=n > 0,
        evidence=(shot, snap),
        notes=None if n > 0 else "no active-filter chip container found",
    )


# --------------------------------------------------------------------------- #
# v1.2 advanced (behavioral) tier
# --------------------------------------------------------------------------- #

_PRODUCT_CARD_SELECTOR: str = (
    '[class*="product-card"], article[class*="card"], '
    'li[class*="grid__item"]:has(a[href*="/products/"])'
)
"""Selector union for product cards on a collection listing.

Reused by :func:`has_product_cards` and the v1.2 advanced behavioral
probes. Centralised so the union does not drift between presence and
behavioral checks (the latter return ``passed=None`` when this returns
< 2, so consistency matters)."""

_BEHAVIORAL_WAIT_MS: int = 3000
"""Hard ceiling on per-interaction waits in advanced probes (3 s).

Stays well under the 10-s default probe timeout in
:mod:`shop_probe.probes._runner` so a missing UI event bubbles up as a
clean ``False`` rather than a timeout."""


async def sort_changes_order(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Toggling the collection sort control changes the first card's title.

    v1.2 advanced — exercises the sort behaviour that
    :func:`has_sort_control` only asserts the *presence* of. Returns
    ``passed=None`` when the sample collection has < 2 cards or no
    ``<select>``-shaped sort control with at least 2 options.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    cards = page.locator(_PRODUCT_CARD_SELECTOR)
    n_cards = await cards.count()
    if n_cards < 2:  # noqa: PLR2004 — need at least 2 cards to detect a swap
        return ProbeOutcome(
            passed=None,
            notes=f"only {n_cards} product card(s); cannot exercise sort",
        )
    sort_select = page.locator(
        'select[id*="sort" i], select[name*="sort" i], select[aria-label*="sort" i]'
    ).first
    if await sort_select.count() == 0:
        return ProbeOutcome(passed=None, notes="no <select>-shaped sort control")
    options = sort_select.locator("option")
    n_options = await options.count()
    if n_options < 2:  # noqa: PLR2004 — need at least 2 options to toggle
        return ProbeOutcome(
            passed=None,
            notes=f"sort <select> has {n_options} option(s); cannot toggle",
        )
    current_value = await sort_select.input_value()
    target_value: str | None = None
    for i in range(n_options):
        value = await options.nth(i).get_attribute("value")
        if value and value != current_value:
            target_value = value
            break
    if target_value is None:
        return ProbeOutcome(
            passed=None,
            notes="sort <select> options share a single value; cannot toggle",
        )
    before_text = ((await cards.first.inner_text()) or "").strip()
    before_shot = await ctx.screenshot("before-sort")
    before_snap = await ctx.snapshot("before-sort")
    try:
        async with page.expect_navigation(
            wait_until="domcontentloaded", timeout=_BEHAVIORAL_WAIT_MS
        ):
            await sort_select.select_option(target_value, timeout=_BEHAVIORAL_WAIT_MS)
    except PlaywrightTimeoutError:
        # Some themes do not navigate (in-place re-render). Fall through and
        # let the assertion below decide based on DOM diff.
        await page.wait_for_timeout(500)
    after_text = ((await cards.first.inner_text()) or "").strip()
    after_shot = await ctx.screenshot("after-sort")
    after_snap = await ctx.snapshot("after-sort")
    passed = before_text != after_text and bool(after_text)
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=None if passed else f"first card unchanged after sort: {before_text[:60]!r}",
    )


async def filters_apply_to_results(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Clicking a filter changes either the visible card count or the URL.

    v1.2 advanced — exercises the filter behaviour that :func:`has_filters`
    only asserts the *presence* of. Passes when either the product card
    count changed or the URL gained a filter param. Returns ``passed=None``
    when there is no clickable filter input.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    cards = page.locator(_PRODUCT_CARD_SELECTOR)
    before_count = await cards.count()
    before_url = page.url
    filter_input = page.locator(
        'fieldset input[type="checkbox"], '
        '[class*="filter"] input[type="checkbox"], '
        '[class*="filter"] a[href*="?"]:not([class*="active"])'
    ).first
    if await filter_input.count() == 0:
        return ProbeOutcome(
            passed=None,
            notes="no checkable filter input or filter anchor on collection page",
        )
    before_shot = await ctx.screenshot("before-filter")
    before_snap = await ctx.snapshot("before-filter")
    try:
        async with page.expect_navigation(
            wait_until="domcontentloaded", timeout=_BEHAVIORAL_WAIT_MS
        ):
            await filter_input.click(timeout=_BEHAVIORAL_WAIT_MS)
    except PlaywrightTimeoutError:
        # In-place filter (no full nav) — wait briefly for re-render.
        await page.wait_for_timeout(500)
    after_count = await cards.count()
    after_url = page.url
    after_shot = await ctx.screenshot("after-filter")
    after_snap = await ctx.snapshot("after-filter")
    url_changed = after_url != before_url
    count_changed = after_count != before_count
    passed = url_changed or count_changed
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=None
        if passed
        else (f"filter click had no effect (cards {before_count}→{after_count}, url unchanged)"),
    )


async def pagination_advances(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Clicking pagination next / load-more loads a different first card.

    v1.2 advanced — exercises the pagination behaviour that
    :func:`has_pagination_or_infinite_scroll` only asserts the
    *presence* of. Returns ``passed=None`` when no pagination control
    exists.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    cards = page.locator(_PRODUCT_CARD_SELECTOR)
    if await cards.count() == 0:
        return ProbeOutcome(passed=None, notes="no product cards on collection page")
    pagination = page.locator(
        'a[rel="next"], '
        'nav[aria-label*="pagination" i] a:not([aria-current]):not([class*="active"]), '
        'button:has-text("Load more"), button:has-text("Show more"), '
        '[data-testid*="load-more"], [class*="load-more"]'
    ).first
    if await pagination.count() == 0:
        return ProbeOutcome(
            passed=None,
            notes="no pagination next / load-more control",
        )
    before_href = await cards.first.locator("a[href*='/products/']").first.get_attribute("href")
    before_count = await cards.count()
    before_shot = await ctx.screenshot("before-pagination")
    before_snap = await ctx.snapshot("before-pagination")
    try:
        async with page.expect_navigation(
            wait_until="domcontentloaded", timeout=_BEHAVIORAL_WAIT_MS
        ):
            await pagination.click(timeout=_BEHAVIORAL_WAIT_MS)
    except PlaywrightTimeoutError:
        # Load-more shape: same URL, more cards appended in place.
        await page.wait_for_timeout(500)
    after_href = await cards.first.locator("a[href*='/products/']").first.get_attribute("href")
    after_count = await cards.count()
    after_shot = await ctx.screenshot("after-pagination")
    after_snap = await ctx.snapshot("after-pagination")
    href_changed = before_href != after_href and after_href is not None
    count_grew = after_count > before_count
    passed = href_changed or count_grew
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=None
        if passed
        else (
            f"pagination click did not advance "
            f"(first href {before_href!r} unchanged, count {before_count}→{after_count})"
        ),
    )


async def filter_click_advances_url(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Clicking a filter input mutates ``page.url`` to encode the state.

    v1.2 advanced — functionally backs the structural URL-state-sync probe
    (:func:`filters_sync_to_url_state` / :func:`dynamics.url_state_sync_present`)
    by asserting the URL actually mutates after a click. Returns
    ``passed=None`` when no filter input is present.
    """
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    filter_input = page.locator(
        'fieldset input[type="checkbox"], '
        '[class*="filter"] input[type="checkbox"], '
        '[class*="filter"] a[href*="?"]:not([class*="active"])'
    ).first
    if await filter_input.count() == 0:
        return ProbeOutcome(
            passed=None,
            notes="no checkable filter input or filter anchor on collection page",
        )
    before_url = page.url
    before_shot = await ctx.screenshot("before-url")
    before_snap = await ctx.snapshot("before-url")
    try:
        async with page.expect_navigation(
            wait_until="domcontentloaded", timeout=_BEHAVIORAL_WAIT_MS
        ):
            await filter_input.click(timeout=_BEHAVIORAL_WAIT_MS)
    except PlaywrightTimeoutError:
        await page.wait_for_timeout(500)
    after_url = page.url
    after_shot = await ctx.screenshot("after-url")
    after_snap = await ctx.snapshot("after-url")
    passed = after_url != before_url
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=None if passed else f"page.url unchanged after filter click ({before_url!r})",
    )
