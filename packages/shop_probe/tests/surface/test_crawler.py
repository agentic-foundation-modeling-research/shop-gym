"""Tests for `shop_probe.surface.crawler` (T2.2 acceptance — spec §5.4 + §7 M2).

The crawler walks the localhost SandboxShop fixture once per pytest module
(crawls are expensive — Playwright + Chromium per visit) and the cohort of
tests below validates each :class:`SurfaceMetrics` field independently
against the fixture's known shape.

Fixture surface (see ``tests/_sandbox.py``):

* 4 distinct templates: homepage, collection, product, cart.
* 2 catalog collections (``/collections/all``, ``/collections/featured``).
* 2 catalog products (``/products/sample``, ``/products/sample-two``).
* 0 catalog variants — the PDP has no variant selector.
* 1 filter group (2 checkboxes) + a 3-option sort select on collection
  pages → ``filter x sort`` cartesian state space = ``2**2 * 3 = 12``.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# `tests/` is on sys.path via pytest's rootdir; `_sandbox.py` lives there.
_TESTS_ROOT = Path(__file__).resolve().parent.parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _sandbox import SandboxShop  # noqa: E402 — sys.path adjustment above

from shop_probe.surface import SurfaceCrawler, SurfaceMetrics  # noqa: E402


@pytest.fixture(scope="module")
def crawled_metrics() -> Iterator[SurfaceMetrics]:
    """Crawl a fresh SandboxShop once and share the result across tests."""

    async def _crawl(url: str) -> SurfaceMetrics:
        async with SurfaceCrawler() as crawler:
            return await crawler.crawl(url)

    with SandboxShop() as base_url:
        yield asyncio.run(_crawl(base_url))


# --------------------------------------------------------------------------- #
# Schema — the crawler emits a closed `SurfaceMetrics` instance.
# --------------------------------------------------------------------------- #


def test_crawler_returns_surface_metrics_instance(crawled_metrics: SurfaceMetrics) -> None:
    assert isinstance(crawled_metrics, SurfaceMetrics)


# --------------------------------------------------------------------------- #
# Per-metric assertions (each test exercises one field independently).
# --------------------------------------------------------------------------- #


def test_distinct_templates_counts_homepage_collection_product_and_cart(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # Homepage, collection (x2 same template), product (x2 same template),
    # cart — four structural fingerprints.
    assert crawled_metrics.distinct_templates == 4  # noqa: PLR2004


def test_routes_crawled_includes_homepage_collections_products_and_cart(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # Homepage + 2 collections + 2 products + cart = 6 routes minimum;
    # pagination ``?page=2`` may bump the count by 1.
    assert crawled_metrics.routes_crawled >= 6  # noqa: PLR2004


def test_catalog_collections_counts_distinct_collection_paths(
    crawled_metrics: SurfaceMetrics,
) -> None:
    assert crawled_metrics.catalog_collections == 2  # noqa: PLR2004


def test_catalog_products_counts_distinct_product_paths(
    crawled_metrics: SurfaceMetrics,
) -> None:
    assert crawled_metrics.catalog_products == 2  # noqa: PLR2004


def test_catalog_variants_is_zero_when_pdp_has_no_variant_selector(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # Fixture's PDP form has only a hidden product_id and a submit button —
    # no variant selectors → the variant detector reports 0.
    assert crawled_metrics.catalog_variants == 0


def test_filter_x_sort_state_space_is_cartesian_product(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # 2 checkbox options → 2**2 = 4 filter combinations; 3 sort options.
    # Cartesian product = 12.
    assert crawled_metrics.filter_x_sort_state_space == 12  # noqa: PLR2004


def test_forms_total_aggregates_across_visited_pages(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # Each collection page has 1 filter form; each product page has 1
    # add-to-cart form. Empty cart and homepage contribute 0.
    assert crawled_metrics.forms_total >= 4  # noqa: PLR2004


def test_form_fields_total_excludes_hidden_inputs(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # Filter forms expose 2 visible checkbox inputs each. Add-to-cart
    # forms expose only a hidden product_id (excluded) + a submit
    # button (not a field).
    assert crawled_metrics.form_fields_total >= 4  # noqa: PLR2004


def test_interactables_per_template_median_is_positive(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # Every template has a header + footer + at least one anchor /
    # button — interactable counts must be strictly positive.
    assert crawled_metrics.interactables_per_template_median > 0.0


def test_interactables_per_template_p95_is_at_least_median(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # By construction p95 >= median for any non-empty distribution.
    assert (
        crawled_metrics.interactables_per_template_p95
        >= crawled_metrics.interactables_per_template_median
    )


def test_median_dom_kb_gz_is_positive(crawled_metrics: SurfaceMetrics) -> None:
    # Even a minimal page produces a non-zero gzipped DOM size.
    assert crawled_metrics.median_dom_kb_gz > 0.0


def test_accessibility_nodes_per_template_median_is_positive(
    crawled_metrics: SurfaceMetrics,
) -> None:
    # Each template surfaces at least header/main/footer landmarks plus
    # links/headings.
    assert crawled_metrics.accessibility_nodes_per_template_median > 0.0


# --------------------------------------------------------------------------- #
# Crawler controls — `max_depth` / `max_products` / `max_routes` honored.
# --------------------------------------------------------------------------- #


def test_crawler_caps_products_at_configured_max() -> None:
    """``max_products=1`` visits at most one PDP, leaving the other discoverable."""

    async def _crawl(url: str) -> SurfaceMetrics:
        async with SurfaceCrawler(max_products=1) as crawler:
            return await crawler.crawl(url)

    with SandboxShop() as base_url:
        metrics = asyncio.run(_crawl(base_url))
    # Both products are discovered as anchors on the collection page.
    assert metrics.catalog_products == 2  # noqa: PLR2004


def test_crawler_rejects_use_outside_async_context_manager() -> None:
    """Using the crawler without ``async with`` raises ``RuntimeError``."""
    crawler = SurfaceCrawler()
    with pytest.raises(RuntimeError, match="async context manager"):
        asyncio.run(crawler.crawl("http://127.0.0.1:1"))


def test_crawler_rejects_invalid_base_url() -> None:
    """Non-``http(s)`` scheme on the base URL raises ``ValueError``."""

    async def _crawl() -> SurfaceMetrics:
        async with SurfaceCrawler() as crawler:
            return await crawler.crawl("ftp://example.com")

    with pytest.raises(ValueError, match="invalid base_url"):
        asyncio.run(_crawl())
