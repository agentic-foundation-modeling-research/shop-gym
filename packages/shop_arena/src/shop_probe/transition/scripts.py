"""Per-page-type transition scripts.

Each script returns a :class:`shop_probe.report.TransitionResult`. The
scripts use ``page.get_by_role`` locators (role+name) — the same
discovery surface an LLM agent would use — so a passing transition
implies the page is genuinely operable, not just that it has the right
markup.

For v1 minimal we ship one script per page type:

* ``homepage_nav_collection`` — click a navigation link to a collection.
* ``collection_click_product`` — click a product card on a collection page.
* ``product_add_to_cart`` — click an "Add to cart" control on a PDP.
* ``cart_checkout`` — click a "Checkout" control from the cart page.
* ``search_submit_query`` — type a query into the search input and submit.

Each script is fault-tolerant: any exception is folded into the
``TransitionResult`` (the bits already record finer-grained outcomes).
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Final

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from shop_probe.report import TransitionResult

_LOCATOR_TIMEOUT_MS: Final[int] = 4_000
"""Per-locator wait, separate from PlaywrightRunner page timeout."""

TransitionScript = Callable[
    ["TransitionContext"], Awaitable[TransitionResult]
]


class TransitionContext:
    """Context passed to each script.

    Attributes:
        page: Live Playwright page.
        base_url: Storefront under test.
        sample_collection_url: Pre-resolved collection URL or ``None``.
        sample_product_url: Pre-resolved product URL or ``None``.
    """

    def __init__(
        self,
        *,
        page: Page,
        base_url: str,
        sample_collection_url: str | None,
        sample_product_url: str | None,
    ) -> None:
        self.page = page
        self.base_url = base_url
        self.sample_collection_url = sample_collection_url
        self.sample_product_url = sample_product_url


def _empty_result(*, latency_ms: int = 0, notes: str | None = None) -> TransitionResult:
    return TransitionResult(
        action_found=False,
        action_executed=False,
        state_changed=False,
        state_changed_as_expected=False,
        latency_ms=latency_ms,
        notes=notes,
    )


async def _navigate(page: Page, url: str) -> bool:
    try:
        await page.goto(url, wait_until="domcontentloaded")
        return True
    except (PlaywrightTimeoutError, Exception):  # noqa: BLE001
        return False


async def homepage_nav_collection(ctx: TransitionContext) -> TransitionResult:
    """Click a primary-nav link to a collection page from the homepage."""
    start = time.perf_counter()
    if not await _navigate(ctx.page, ctx.base_url):
        return _empty_result(notes="homepage navigation failed")

    locator = ctx.page.locator('a[href*="/collections/"]').first
    try:
        if await locator.count() == 0:
            return _empty_result(
                latency_ms=int((time.perf_counter() - start) * 1000),
                notes="no collection link on homepage",
            )
        await locator.wait_for(state="visible", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return _empty_result(notes="collection link not visible")

    before_url = ctx.page.url
    try:
        await locator.click(timeout=_LOCATOR_TIMEOUT_MS)
        await ctx.page.wait_for_load_state("domcontentloaded", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError as err:
        return TransitionResult(
            action_found=True,
            action_executed=False,
            state_changed=False,
            state_changed_as_expected=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
            notes=f"click timeout: {err}",
        )

    after_url = ctx.page.url
    state_changed = after_url != before_url
    expected = "/collections/" in after_url
    return TransitionResult(
        action_found=True,
        action_executed=True,
        state_changed=state_changed,
        state_changed_as_expected=expected,
        latency_ms=int((time.perf_counter() - start) * 1000),
        notes=None,
    )


async def collection_click_product(ctx: TransitionContext) -> TransitionResult:
    """Click a product card on a collection page → land on a PDP."""
    if ctx.sample_collection_url is None:
        return _empty_result(notes="no sample collection URL")
    start = time.perf_counter()
    if not await _navigate(ctx.page, ctx.sample_collection_url):
        return _empty_result(notes="collection navigation failed")

    locator = ctx.page.locator('a[href*="/products/"]').first
    try:
        if await locator.count() == 0:
            return _empty_result(
                latency_ms=int((time.perf_counter() - start) * 1000),
                notes="no product card on collection",
            )
        await locator.wait_for(state="visible", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return _empty_result(notes="product card not visible")

    before_url = ctx.page.url
    try:
        await locator.click(timeout=_LOCATOR_TIMEOUT_MS)
        await ctx.page.wait_for_load_state("domcontentloaded", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError as err:
        return TransitionResult(
            action_found=True,
            action_executed=False,
            state_changed=False,
            state_changed_as_expected=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
            notes=f"click timeout: {err}",
        )

    after_url = ctx.page.url
    state_changed = after_url != before_url
    expected = "/products/" in after_url
    return TransitionResult(
        action_found=True,
        action_executed=True,
        state_changed=state_changed,
        state_changed_as_expected=expected,
        latency_ms=int((time.perf_counter() - start) * 1000),
        notes=None,
    )


async def product_add_to_cart(ctx: TransitionContext) -> TransitionResult:
    """Click "Add to cart" on a PDP → cart count or drawer changes.

    State-change detection is heuristic: we read a cart-count token from
    the visible page text before and after the click. A drawer opening
    or a redirect to /cart also count as state_changed.
    """
    if ctx.sample_product_url is None:
        return _empty_result(notes="no sample product URL")
    start = time.perf_counter()
    if not await _navigate(ctx.page, ctx.sample_product_url):
        return _empty_result(notes="product navigation failed")

    button = ctx.page.get_by_role("button", name=re.compile(r"add to (cart|bag)", re.I)).first
    try:
        if await button.count() == 0:
            # Fall back to form-submit button.
            button = ctx.page.locator('form[action*="/cart"] button[type="submit"]').first
            if await button.count() == 0:
                return _empty_result(
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    notes="no add-to-cart button",
                )
        await button.wait_for(state="visible", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return _empty_result(notes="add-to-cart not visible")

    before_url = ctx.page.url
    before_body = await ctx.page.locator("body").inner_text(timeout=_LOCATOR_TIMEOUT_MS)
    try:
        await button.click(timeout=_LOCATOR_TIMEOUT_MS)
        # A small grace window for AJAX cart drawers / redirects.
        await ctx.page.wait_for_timeout(1_000)
    except PlaywrightTimeoutError as err:
        return TransitionResult(
            action_found=True,
            action_executed=False,
            state_changed=False,
            state_changed_as_expected=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
            notes=f"click timeout: {err}",
        )

    after_url = ctx.page.url
    after_body = await ctx.page.locator("body").inner_text(timeout=_LOCATOR_TIMEOUT_MS)

    state_changed = (after_url != before_url) or (after_body != before_body)
    cart_signal = ("/cart" in after_url) or _cart_token_increased(before_body, after_body)
    return TransitionResult(
        action_found=True,
        action_executed=True,
        state_changed=state_changed,
        state_changed_as_expected=cart_signal,
        latency_ms=int((time.perf_counter() - start) * 1000),
        notes=None,
    )


_CART_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\((\d+)\)|cart[:\s]+(\d+)", re.I)


def _cart_token_increased(before: str, after: str) -> bool:
    """Heuristic: did a number-in-parentheses near 'cart' increase?"""
    def _max_token(text: str) -> int:
        nums: list[int] = []
        for match in _CART_TOKEN_RE.finditer(text):
            for grp in match.groups():
                if grp is not None and grp.isdigit():
                    nums.append(int(grp))
        return max(nums) if nums else 0

    return _max_token(after) > _max_token(before)


async def cart_checkout(ctx: TransitionContext) -> TransitionResult:
    """Click "Checkout" from the cart → URL changes (typically to /checkout)."""
    start = time.perf_counter()
    cart_url = ctx.base_url.rstrip("/") + "/cart"
    if not await _navigate(ctx.page, cart_url):
        return _empty_result(notes="cart navigation failed")

    button = ctx.page.get_by_role("button", name=re.compile(r"checkout|check out", re.I)).first
    if await button.count() == 0:
        button = ctx.page.get_by_role("link", name=re.compile(r"checkout|check out", re.I)).first
    try:
        if await button.count() == 0:
            return _empty_result(
                latency_ms=int((time.perf_counter() - start) * 1000),
                notes="no checkout control",
            )
        await button.wait_for(state="visible", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return _empty_result(notes="checkout control not visible")

    before_url = ctx.page.url
    try:
        await button.click(timeout=_LOCATOR_TIMEOUT_MS)
        await ctx.page.wait_for_load_state("domcontentloaded", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError as err:
        return TransitionResult(
            action_found=True,
            action_executed=False,
            state_changed=False,
            state_changed_as_expected=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
            notes=f"click timeout: {err}",
        )

    after_url = ctx.page.url
    state_changed = after_url != before_url
    expected = state_changed and ("checkout" in after_url.lower())
    return TransitionResult(
        action_found=True,
        action_executed=True,
        state_changed=state_changed,
        state_changed_as_expected=expected,
        latency_ms=int((time.perf_counter() - start) * 1000),
        notes=None,
    )


async def search_submit_query(ctx: TransitionContext) -> TransitionResult:
    """Submit a query through the homepage search → results page."""
    start = time.perf_counter()
    if not await _navigate(ctx.page, ctx.base_url):
        return _empty_result(notes="homepage navigation failed")

    box = ctx.page.get_by_role("searchbox").first
    if await box.count() == 0:
        box = ctx.page.locator('input[type="search"], input[name="q"]').first
    try:
        if await box.count() == 0:
            return _empty_result(
                latency_ms=int((time.perf_counter() - start) * 1000),
                notes="no search input",
            )
        await box.wait_for(state="visible", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return _empty_result(notes="search input not visible")

    before_url = ctx.page.url
    try:
        await box.fill("test", timeout=_LOCATOR_TIMEOUT_MS)
        await box.press("Enter", timeout=_LOCATOR_TIMEOUT_MS)
        await ctx.page.wait_for_load_state("domcontentloaded", timeout=_LOCATOR_TIMEOUT_MS)
    except PlaywrightTimeoutError as err:
        return TransitionResult(
            action_found=True,
            action_executed=False,
            state_changed=False,
            state_changed_as_expected=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
            notes=f"submit timeout: {err}",
        )

    after_url = ctx.page.url
    state_changed = after_url != before_url
    expected = state_changed and (("/search" in after_url) or ("q=" in after_url))
    return TransitionResult(
        action_found=True,
        action_executed=True,
        state_changed=state_changed,
        state_changed_as_expected=expected,
        latency_ms=int((time.perf_counter() - start) * 1000),
        notes=None,
    )


SCRIPTS: Final[dict[str, TransitionScript]] = {
    "homepage_nav_collection": homepage_nav_collection,
    "collection_click_product": collection_click_product,
    "product_add_to_cart": product_add_to_cart,
    "cart_checkout": cart_checkout,
    "search_submit_query": search_submit_query,
}
"""Registry: ``rubric.script`` → callable."""
