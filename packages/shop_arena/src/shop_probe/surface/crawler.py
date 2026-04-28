"""Axis B — surface-area crawler (T2.2 — spec §5.4 + §7 M2).

Crawls a Shopify-shaped storefront in a Playwright runtime and computes
the descriptive metrics enumerated in
:class:`shop_probe.surface.metrics.SurfaceMetrics`.

Per spec §5.4 the crawl is:

* depth-2 BFS from ``/`` (default; configurable);
* full enumeration of every ``/collections/*`` route discovered;
* sampled ``/products/*`` set capped at ``N=20`` (default; configurable);
* same Playwright runtime guarantees as the axis-A probes — isolated
  context, fixed ``1280x800`` viewport, pinned UA, headless Chromium,
  hard 10 s default timeout, ``retries=0``.

Surface metrics are *descriptive, not normative* (spec §5.4): they are
reported alongside the axis-A coverage rollup, not folded into a
headline fidelity score. The crawler is therefore lenient — pages that
404 or fail to load are skipped rather than aborting the run; observed
pages contribute to the per-template aggregations.

This module performs no I/O at import time; the Playwright lifecycle is
bound to :meth:`SurfaceCrawler.__aenter__`.
"""

from __future__ import annotations

import collections
import contextlib
import gzip
import hashlib
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, cast
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import Browser, BrowserContext, async_playwright

from shop_probe.probes._runner import (
    DEFAULT_PROBE_TIMEOUT_S,
    PINNED_USER_AGENT,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
)
from shop_probe.surface.metrics import SurfaceMetrics

DEFAULT_MAX_DEPTH: Final[int] = 2
"""Depth-2 BFS from ``/`` (spec §5.4)."""

DEFAULT_MAX_PRODUCTS: Final[int] = 20
"""Sampling cap on ``/products/*`` URLs visited (spec §5.4)."""

DEFAULT_MAX_ROUTES: Final[int] = 200
"""Defensive hard cap on total HTML pages visited (defends against
faceted-URL explosions on real merchant storefronts)."""

_FINGERPRINT_DEPTH: Final[int] = 4
"""Tag-tree depth used to compute the structural template fingerprint."""

_HTTP_OK_MIN: Final[int] = 200
_HTTP_OK_MAX: Final[int] = 299
_FILTER_GROUP_EXP_CAP: Final[int] = 16
"""Per-group exponent cap for checkbox filter contributions."""

_STATE_SPACE_TOTAL_CAP: Final[int] = 1_000_000_000
"""Aggregate cap for ``filter_x_sort_state_space`` to keep the metric
finite on real-world storefronts with deep faceted navigation."""

_PRODUCTS_PREFIX: Final[str] = "/products/"
_COLLECTIONS_PREFIX: Final[str] = "/collections/"

_PROBE_PAGE_JS: Final[str] = r"""
(args) => {
    const {
        fingerprintDepth, interactableSelector, formFieldSelector, a11ySelector,
    } = args;
    if (!document.body) {
        return {
            fingerprint: '', interactables: 0, forms: 0,
            formFields: 0, a11yNodes: 0, links: [],
        };
    }
    const tagTree = (el, depth) => {
        if (!el || depth === 0) return el ? el.tagName : '';
        const out = [];
        for (const c of el.children) out.push(tagTree(c, depth - 1));
        return el.tagName + '(' + out.join(',') + ')';
    };
    return {
        fingerprint: tagTree(document.body, fingerprintDepth),
        interactables: document.querySelectorAll(interactableSelector).length,
        forms: document.querySelectorAll('form').length,
        formFields: document.querySelectorAll(formFieldSelector).length,
        a11yNodes: document.querySelectorAll(a11ySelector).length,
        links: Array.from(document.querySelectorAll('a[href]')).map(a => a.href),
    };
}
"""

_INTERACTABLE_SELECTOR: Final[str] = (
    'a[href], button, input:not([type="hidden"]), select, textarea, '
    '[role="button"], [role="tab"], [role="link"], [role="checkbox"], '
    '[role="radio"], [role="combobox"], [contenteditable=""], [contenteditable="true"]'
)

_FORM_FIELD_SELECTOR: Final[str] = (
    'form input:not([type="hidden"]), form select, form textarea, '
    'form [contenteditable=""], form [contenteditable="true"]'
)

_A11Y_NODE_SELECTOR: Final[str] = (
    # DOM-side proxy for accessibility-tree node count (spec §5.4): every
    # element a screen reader is likely to surface as a node — semantic
    # landmarks, headings, lists, form fields, links, buttons, images
    # with alt text, and elements with an explicit ARIA role.
    'a, button, input:not([type="hidden"]), select, textarea, label, '
    "h1, h2, h3, h4, h5, h6, nav, main, header, footer, section, article, "
    "aside, form, fieldset, legend, ul, ol, li, dl, dt, dd, dialog, "
    "table, tr, td, th, caption, figure, figcaption, img[alt], details, "
    "summary, [role]"
)

_PROBE_COLLECTION_FILTERS_JS: Final[str] = r"""
() => {
    // Prefer <fieldset> as the canonical filter-group container; fall
    // back to [class*="filter"] only when the page has no fieldsets, so
    // we never double-count nested wrappers (e.g.
    // <aside class="filters"><fieldset>...).
    let containers = Array.from(document.querySelectorAll('fieldset'));
    if (containers.length === 0) {
        containers = Array.from(document.querySelectorAll('[class*="filter"]'));
    }
    const groups = [];
    for (const c of containers) {
        const checkboxes = c.querySelectorAll('input[type="checkbox"]').length;
        const radios = c.querySelectorAll('input[type="radio"]').length;
        if (checkboxes > 0) groups.push({ kind: 'checkbox', n: checkboxes });
        if (radios > 0) groups.push({ kind: 'radio', n: radios });
    }
    let sortOptions = 0;
    const sortSelect = document.querySelector(
        'select[id*="sort" i], select[name*="sort" i], '
        + 'select[aria-label*="sort" i]'
    );
    if (sortSelect) sortOptions = sortSelect.querySelectorAll('option').length;
    if (sortOptions === 0) {
        sortOptions = document.querySelectorAll(
            'button[aria-label*="sort" i]'
        ).length;
    }
    return { groups, sortOptions };
}
"""

_PROBE_PRODUCT_VARIANTS_JS: Final[str] = r"""
() => {
    const form = document.querySelector(
        'form[action*="/cart/add"], form.product-form, '
        + 'form[class*="product"]'
    ) || document.body;
    if (!form) return 0;
    let total = 1;
    let groupCount = 0;
    const variantSelects = form.querySelectorAll(
        'select[name*="option" i], select[name*="variant" i]'
    );
    for (const sel of variantSelects) {
        const n = sel.querySelectorAll('option').length;
        if (n > 1) { total *= n; groupCount++; }
    }
    const radiosByName = {};
    for (const r of form.querySelectorAll('input[type="radio"]')) {
        if (!radiosByName[r.name]) radiosByName[r.name] = 0;
        radiosByName[r.name]++;
    }
    for (const n of Object.values(radiosByName)) {
        if (n > 1) { total *= n; groupCount++; }
    }
    if (groupCount === 0) {
        const swatches = form.querySelectorAll(
            '[class*="swatch"], [data-variant]'
        );
        if (swatches.length > 1) { total *= swatches.length; groupCount++; }
    }
    return groupCount === 0 ? 0 : total;
}
"""


@dataclass(frozen=True, slots=True)
class _PageObservation:
    """Per-page snapshot used to roll up :class:`SurfaceMetrics`."""

    url: str
    template_id: str
    interactables: int
    forms: int
    form_fields: int
    dom_kb_gz: float
    a11y_nodes: int
    outgoing_links: tuple[str, ...]


@dataclass(slots=True)
class _CrawlState:
    """Mutable bookkeeping shared by the BFS / enumeration / sampling phases."""

    observations: list[_PageObservation]
    visited_urls: set[str]
    discovered_products: dict[str, str]
    discovered_collections: dict[str, str]
    collection_state_spaces: list[int]
    product_variant_totals: list[int]
    products_visited: int


class SurfaceCrawler:
    """Walk a Shopify-shaped storefront and emit a :class:`SurfaceMetrics`.

    Use as an async context manager; Playwright + Chromium are launched on
    enter and torn down on exit::

        async with SurfaceCrawler() as crawler:
            metrics = await crawler.crawl("https://shop.example.com")
    """

    def __init__(
        self,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_products: int = DEFAULT_MAX_PRODUCTS,
        max_routes: int = DEFAULT_MAX_ROUTES,
        viewport: tuple[int, int] = (VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
        user_agent: str = PINNED_USER_AGENT,
        timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
        headless: bool = True,
    ) -> None:
        """Initialize the crawler.

        Args:
            max_depth: Maximum BFS depth from the homepage (spec §5.4
                default = 2).
            max_products: Cap on ``/products/*`` URLs sampled
                (spec §5.4 default = 20).
            max_routes: Defensive cap on total HTML pages visited.
            viewport: ``(width, height)`` viewport in CSS pixels.
            user_agent: Pinned UA string (defaults to
                :data:`shop_probe.probes._runner.PINNED_USER_AGENT`).
            timeout_s: Hard per-page timeout in seconds.
            headless: Whether to launch Chromium headless.
        """
        self.max_depth = max_depth
        self.max_products = max_products
        self.max_routes = max_routes
        self.viewport = viewport
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.headless = headless
        self._stack: contextlib.AsyncExitStack | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> SurfaceCrawler:
        """Launch Playwright + Chromium for the crawl."""
        stack = contextlib.AsyncExitStack()
        await stack.__aenter__()
        try:
            playwright = await stack.enter_async_context(async_playwright())
            browser = await playwright.chromium.launch(headless=self.headless)
            stack.push_async_callback(browser.close)
        except BaseException:
            await stack.aclose()
            raise
        self._browser = browser
        self._stack = stack
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close Chromium and stop Playwright."""
        stack, self._stack = self._stack, None
        self._browser = None
        if stack is not None:
            await stack.__aexit__(exc_type, exc, tb)

    async def crawl(self, base_url: str) -> SurfaceMetrics:
        """Walk ``base_url`` and return a :class:`SurfaceMetrics` snapshot.

        Raises:
            RuntimeError: If called outside the ``async with`` block.
            ValueError: If ``base_url`` cannot be parsed as ``http(s)://``.
        """
        if self._browser is None:
            msg = "SurfaceCrawler must be used as an async context manager"
            raise RuntimeError(msg)
        normalized_base = _normalize_url(base_url, base_url)
        if normalized_base is None:
            msg = f"invalid base_url: {base_url!r}"
            raise ValueError(msg)

        state = _CrawlState(
            observations=[],
            visited_urls=set(),
            discovered_products={},
            discovered_collections={},
            collection_state_spaces=[],
            product_variant_totals=[],
            products_visited=0,
        )
        await self._bfs(normalized_base, state)
        await self._enumerate_collections(state)
        await self._sample_products(state)

        return _aggregate(
            observations=state.observations,
            collection_state_spaces=state.collection_state_spaces,
            product_variants=state.product_variant_totals,
            catalog_products=len(state.discovered_products),
            catalog_collections=len(state.discovered_collections),
        )

    # --- BFS / enumeration / sampling phases ----------------------------- #

    async def _bfs(self, root_url: str, state: _CrawlState) -> None:
        """Phase 1 — BFS from ``root_url`` up to :attr:`max_depth`."""
        queue: collections.deque[tuple[str, int]] = collections.deque()
        queue.append((root_url, 0))
        while queue and len(state.visited_urls) < self.max_routes:
            url, depth = queue.popleft()
            if url in state.visited_urls:
                continue
            path = urlparse(url).path
            is_product = path.startswith(_PRODUCTS_PREFIX)
            if is_product and state.products_visited >= self.max_products:
                continue
            state.visited_urls.add(url)
            obs = await self._visit(url)
            if obs is None:
                continue
            await self._record_observation(obs, path, state)
            if depth + 1 > self.max_depth:
                continue
            for link in obs.outgoing_links:
                _classify_link(link, state)
                if link not in state.visited_urls:
                    queue.append((link, depth + 1))

    async def _enumerate_collections(self, state: _CrawlState) -> None:
        """Phase 2 — visit every discovered ``/collections/*`` not yet seen."""
        for url in sorted(set(state.discovered_collections.values()) - state.visited_urls):
            if len(state.visited_urls) >= self.max_routes:
                break
            state.visited_urls.add(url)
            obs = await self._visit(url)
            if obs is None:
                continue
            await self._record_observation(obs, urlparse(url).path, state)
            for link in obs.outgoing_links:
                _classify_link(link, state)

    async def _sample_products(self, state: _CrawlState) -> None:
        """Phase 3 — sample remaining ``/products/*`` up to :attr:`max_products`."""
        budget = self.max_products - state.products_visited
        if budget <= 0:
            return
        remaining = sorted(set(state.discovered_products.values()) - state.visited_urls)
        for url in remaining[:budget]:
            if len(state.visited_urls) >= self.max_routes:
                break
            state.visited_urls.add(url)
            obs = await self._visit(url)
            if obs is None:
                continue
            await self._record_observation(obs, urlparse(url).path, state)

    async def _record_observation(
        self, obs: _PageObservation, path: str, state: _CrawlState
    ) -> None:
        """Append ``obs`` to ``state`` and run the per-route side metrics."""
        state.observations.append(obs)
        if path.startswith(_PRODUCTS_PREFIX):
            state.products_visited += 1
            state.discovered_products.setdefault(path, obs.url)
            state.product_variant_totals.append(await self._count_product_variants(obs.url))
        elif path.startswith(_COLLECTIONS_PREFIX):
            state.discovered_collections.setdefault(path, obs.url)
            state.collection_state_spaces.append(await self._collection_state_space(obs.url))

    # --- Per-page evaluation helpers ------------------------------------- #

    async def _new_context(self) -> BrowserContext:
        """Open a fresh isolated browser context with the pinned runtime."""
        if self._browser is None:  # pragma: no cover — guarded by `crawl`.
            msg = "SurfaceCrawler must be used as an async context manager"
            raise RuntimeError(msg)
        return await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
        )

    async def _visit(self, url: str) -> _PageObservation | None:
        """Visit ``url`` in a fresh isolated context; ``None`` on any error."""
        context = await self._new_context()
        try:
            return await self._capture_observation(context, url)
        finally:
            await context.close()

    async def _capture_observation(
        self, context: BrowserContext, url: str
    ) -> _PageObservation | None:
        """Drive ``context`` to ``url`` and return one :class:`_PageObservation`."""
        page = await context.new_page()
        page.set_default_timeout(self.timeout_s * 1000.0)
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
        except Exception:
            return None
        if response is None or not (_HTTP_OK_MIN <= response.status <= _HTTP_OK_MAX):
            return None
        try:
            raw: object = await page.evaluate(
                _PROBE_PAGE_JS,
                {
                    "fingerprintDepth": _FINGERPRINT_DEPTH,
                    "interactableSelector": _INTERACTABLE_SELECTOR,
                    "formFieldSelector": _FORM_FIELD_SELECTOR,
                    "a11ySelector": _A11Y_NODE_SELECTOR,
                },
            )
            html = await page.content()
        except Exception:
            return None
        if not isinstance(raw, Mapping):
            return None
        raw_map = cast("Mapping[str, Any]", raw)
        fingerprint = str(raw_map.get("fingerprint", "") or "")
        seed = fingerprint or html
        template_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        outgoing = _normalize_links(raw_map.get("links"), url)
        return _PageObservation(
            url=url,
            template_id=template_id,
            interactables=_coerce_int(raw_map.get("interactables")),
            forms=_coerce_int(raw_map.get("forms")),
            form_fields=_coerce_int(raw_map.get("formFields")),
            dom_kb_gz=_gzipped_kb(html),
            a11y_nodes=_coerce_int(raw_map.get("a11yNodes")),
            outgoing_links=outgoing,
        )

    async def _collection_state_space(self, url: str) -> int:
        """Compute ``filter x sort`` state-space size on a collection page."""
        context = await self._new_context()
        try:
            page = await context.new_page()
            page.set_default_timeout(self.timeout_s * 1000.0)
            try:
                await page.goto(url, wait_until="domcontentloaded")
                raw: object = await page.evaluate(_PROBE_COLLECTION_FILTERS_JS)
            except Exception:
                return 1
        finally:
            await context.close()
        if not isinstance(raw, Mapping):
            return 1
        raw_map = cast("Mapping[str, Any]", raw)
        groups = _parse_filter_groups(raw_map.get("groups"))
        sort_options = _coerce_int(raw_map.get("sortOptions"))
        return _state_space(groups, sort_options)

    async def _count_product_variants(self, url: str) -> int:
        """Compute the number of distinct variants on a product page."""
        context = await self._new_context()
        try:
            page = await context.new_page()
            page.set_default_timeout(self.timeout_s * 1000.0)
            try:
                await page.goto(url, wait_until="domcontentloaded")
                raw: object = await page.evaluate(_PROBE_PRODUCT_VARIANTS_JS)
            except Exception:
                return 0
        finally:
            await context.close()
        return max(_coerce_int(raw), 0)


def _classify_link(link: str, state: _CrawlState) -> None:
    """Index ``link`` under products / collections so the cohort sees it."""
    link_path = urlparse(link).path
    if link_path.startswith(_PRODUCTS_PREFIX):
        state.discovered_products.setdefault(link_path, link)
    elif link_path.startswith(_COLLECTIONS_PREFIX):
        state.discovered_collections.setdefault(link_path, link)


def _parse_filter_groups(value: object) -> list[tuple[str, int]]:
    """Convert the JS ``groups`` array into ``[(kind, n), ...]``."""
    if not isinstance(value, list):
        return []
    out: list[tuple[str, int]] = []
    for entry in cast("list[object]", value):
        if isinstance(entry, Mapping):
            entry_map = cast("Mapping[str, Any]", entry)
            out.append((str(entry_map.get("kind", "")), _coerce_int(entry_map.get("n"))))
    return out


def _normalize_url(href: str | None, base_url: str) -> str | None:
    """Resolve ``href`` against ``base_url`` and constrain to base origin.

    Returns ``None`` for empty hrefs, non-``http(s)`` schemes, off-origin
    hosts, and unparseable URLs. The fragment is stripped; query params
    and trailing slash are preserved.
    """
    if not href:
        return None
    try:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        base_parsed = urlparse(base_url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc != base_parsed.netloc:
        return None
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )


def _normalize_links(value: object, base_url: str) -> tuple[str, ...]:
    """Cast a JS array of hrefs to a deduped tuple of normalized URLs."""
    raw_links: Iterable[str] = ()
    if isinstance(value, list):
        raw_links = (item for item in cast("list[object]", value) if isinstance(item, str))
    seen: set[str] = set()
    out: list[str] = []
    for href in raw_links:
        normalized = _normalize_url(href, base_url)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return tuple(out)


def _coerce_int(value: object) -> int:
    """Cast a JS-evaluated ``object`` to ``int``; non-numeric → 0."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _gzipped_kb(html: str) -> float:
    """Return the gzipped DOM size in kilobytes."""
    return len(gzip.compress(html.encode("utf-8"))) / 1024.0


def _state_space(filter_groups: list[tuple[str, int]], sort_options: int) -> int:
    """Cartesian filter x sort state-space size, capped to keep finite.

    Per spec §5.4 ``filter_x_sort_state_space`` is the size of the
    cartesian filter x sort URL state space exposed by the collection
    page. Each checkbox group contributes ``2**n`` (independent toggles);
    each radio/select group contributes ``n + 1`` (one option active at a
    time, plus the "none" state). The aggregate is capped at
    :data:`_STATE_SPACE_TOTAL_CAP` so deep faceted catalogs do not produce
    pathological metrics.
    """
    total = 1
    for kind, n in filter_groups:
        if n <= 0:
            continue
        if kind == "checkbox":
            total *= 2 ** min(n, _FILTER_GROUP_EXP_CAP)
        else:
            total *= n + 1
        total = min(total, _STATE_SPACE_TOTAL_CAP)
    return total * max(sort_options, 1)


def _percentile(values: list[float], pct: float) -> float:
    """Return the ``pct`` percentile of ``values`` via linear interpolation.

    For 0/1-element inputs we degrade gracefully to ``0.0`` / the single
    value. ``statistics.quantiles`` requires N>=2 with a divisor argument,
    so we hand-roll the standard interpolation to keep the surface
    aggregator robust for the localhost fixture (only 4 distinct templates).
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + frac * (ordered[hi] - ordered[lo])


def _aggregate(
    *,
    observations: list[_PageObservation],
    collection_state_spaces: list[int],
    product_variants: list[int],
    catalog_products: int,
    catalog_collections: int,
) -> SurfaceMetrics:
    """Roll per-page observations into the closed :class:`SurfaceMetrics`."""
    if not observations:
        return SurfaceMetrics(
            distinct_templates=0,
            routes_crawled=0,
            interactables_per_template_median=0.0,
            interactables_per_template_p95=0.0,
            forms_total=0,
            form_fields_total=0,
            catalog_products=catalog_products,
            catalog_collections=catalog_collections,
            catalog_variants=sum(product_variants),
            filter_x_sort_state_space=max(collection_state_spaces, default=0),
            median_dom_kb_gz=0.0,
            accessibility_nodes_per_template_median=0.0,
        )
    by_template: dict[str, list[_PageObservation]] = {}
    for obs in observations:
        by_template.setdefault(obs.template_id, []).append(obs)

    interactables_per_template = [
        statistics.median(o.interactables for o in obs_list) for obs_list in by_template.values()
    ]
    dom_kb_per_template = [
        statistics.median(o.dom_kb_gz for o in obs_list) for obs_list in by_template.values()
    ]
    a11y_per_template = [
        statistics.median(o.a11y_nodes for o in obs_list) for obs_list in by_template.values()
    ]

    return SurfaceMetrics(
        distinct_templates=len(by_template),
        routes_crawled=len(observations),
        interactables_per_template_median=float(statistics.median(interactables_per_template)),
        interactables_per_template_p95=float(_percentile(interactables_per_template, 95.0)),
        forms_total=sum(o.forms for o in observations),
        form_fields_total=sum(o.form_fields for o in observations),
        catalog_products=catalog_products,
        catalog_collections=catalog_collections,
        catalog_variants=sum(product_variants),
        filter_x_sort_state_space=max(collection_state_spaces, default=0),
        median_dom_kb_gz=float(statistics.median(dom_kb_per_template)),
        accessibility_nodes_per_template_median=float(statistics.median(a11y_per_template)),
    )


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_PRODUCTS",
    "DEFAULT_MAX_ROUTES",
    "SurfaceCrawler",
]
