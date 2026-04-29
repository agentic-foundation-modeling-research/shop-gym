"""Unit tests for :mod:`shop_explore.prefetch`.

Covers T1.3 and T6.4 of ``docs/impl/shop_explore_implementation.md``:

* Happy path — every URL in §5.9's plan is fetched, persisted under
  ``dest_dir`` per the §5.4 layout, and summarized in
  ``prefetch.json``.
* ``/`` returning ``403`` raises :class:`ShopUnreachableError` with the
  ``http_status`` reason.
* ``/`` body containing a Cloudflare challenge marker raises with the
  ``cloudflare_challenge`` reason.
* ``robots.txt`` disallowing ``*`` on ``/`` raises with the
  ``robots_disallow`` reason and aborts before fetching any other URL.
* T6.4 — paginated ``/products.json`` walk merges every page into
  ``products.json`` and stops on the first short page.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx

from shop_explore.capabilities import Capabilities
from shop_explore.prefetch import (
    DEFAULT_USER_AGENT,
    PRODUCTS_PAGE_LIMIT,
    PrefetchResult,
    ShopUnreachableError,
    run,
)
from shop_explore.stats import compute as compute_stats

BASE_URL = "https://example-shop.com"
EXPECTED_FETCH_COUNT = 16
"""15 static plan URLs + 1 ``/products.json`` page (terminates immediately
when the storefront has zero products). See ``_FETCH_PLAN`` and
``_fetch_products_paginated`` in ``shop_explore.prefetch.runner``."""

# Constants for the multi-page pagination test. Picked so that:
# - page 1 returns exactly PRODUCTS_PAGE_LIMIT products → the runner
#   schedules another page;
# - page 2 returns < PRODUCTS_PAGE_LIMIT products → the runner stops.
_PAGE_TWO_PRODUCT_START_ID = 10_000
_PAGE_TWO_PRODUCT_COUNT = 50
_EXPECTED_PAGES_FETCHED = 2


def _ok(content: str | bytes, *, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    """Return a 200 response with the given body and content type."""
    body = content.encode("utf-8") if isinstance(content, str) else content
    return httpx.Response(200, content=body, headers={"content-type": content_type})


def _stub_storefront(
    mock: respx.MockRouter,
    *,
    robots_txt: str = "User-agent: *\nAllow: /\n",
    index_html: str = "<!doctype html><html><body>welcome</body></html>",
) -> None:
    """Wire up a default 200-response for every URL the prefetch plan hits.

    Any URL not explicitly overridden returns a small valid placeholder so
    that the tests focus on bot-block detection paths rather than every
    individual endpoint.
    """
    mock.get(f"{BASE_URL}/robots.txt").mock(return_value=_ok(robots_txt, content_type="text/plain"))
    mock.get(f"{BASE_URL}/").mock(return_value=_ok(index_html))
    mock.get(f"{BASE_URL}/sitemap.xml").mock(
        return_value=_ok(
            "<?xml version='1.0'?><urlset></urlset>",
            content_type="application/xml",
        )
    )
    mock.get(
        f"{BASE_URL}/products.json",
        params={"page": "1", "limit": str(PRODUCTS_PAGE_LIMIT)},
    ).mock(return_value=_ok('{"products": []}', content_type="application/json"))
    mock.get(f"{BASE_URL}/collections.json", params={"limit": "50"}).mock(
        return_value=_ok('{"collections": []}', content_type="application/json")
    )
    mock.get(
        f"{BASE_URL}/search/suggest.json",
        params={"q": "a", "resources[type]": "product"},
    ).mock(return_value=_ok('{"resources": {}}', content_type="application/json"))
    mock.get(f"{BASE_URL}/cart.js").mock(
        return_value=_ok('{"items": []}', content_type="application/json")
    )
    mock.get(f"{BASE_URL}/cart").mock(return_value=_ok("<html>cart</html>"))
    mock.get(f"{BASE_URL}/search").mock(return_value=_ok("<html>search</html>"))
    for slug in ("refund-policy", "privacy-policy", "terms-of-service", "shipping-policy"):
        mock.get(f"{BASE_URL}/policies/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))
    for slug in ("about", "contact", "faq"):
        mock.get(f"{BASE_URL}/pages/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))


@respx.mock
def test_run_happy_path_writes_full_layout(tmp_path: Path) -> None:
    _stub_storefront(respx.mock)

    result = run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0)

    # PrefetchResult shape.
    assert isinstance(result, PrefetchResult)
    assert result.base_url == BASE_URL
    assert result.user_agent == DEFAULT_USER_AGENT
    assert len(result.entries) == EXPECTED_FETCH_COUNT
    assert all(entry.status == HTTPStatus.OK for entry in result.entries)
    assert all(entry.error is None for entry in result.entries)

    # §5.4 layout — top-level files.
    for name in (
        "robots.txt",
        "index.html",
        "sitemap.xml",
        "products.json",
        "collections.json",
        "search_suggest.json",
        "cart.js",
        "cart.html",
        "search.html",
    ):
        assert (tmp_path / name).is_file(), name

    # Policies + pages subdirectories.
    for slug in ("refund-policy", "privacy-policy", "terms-of-service", "shipping-policy"):
        assert (tmp_path / "policies" / f"{slug}.html").is_file()
    for slug in ("about", "contact", "faq"):
        assert (tmp_path / "pages" / f"{slug}.html").is_file()

    # prefetch.json summary is valid JSON and matches the returned model.
    summary = json.loads((tmp_path / "prefetch.json").read_text())
    assert summary["base_url"] == BASE_URL
    assert summary["user_agent"] == DEFAULT_USER_AGENT
    assert len(summary["entries"]) == EXPECTED_FETCH_COUNT
    paths_in_order = [entry["path"] for entry in summary["entries"]]
    assert paths_in_order[0] == "/robots.txt"
    assert paths_in_order[1] == "/"


@respx.mock
def test_run_user_agent_is_sent_on_every_request(tmp_path: Path) -> None:
    _stub_storefront(respx.mock)

    run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0, user_agent="TestUA/1.0")

    for call in respx.mock.calls:
        assert call.request.headers["user-agent"] == "TestUA/1.0"


@respx.mock
def test_run_raises_on_403_index(tmp_path: Path) -> None:
    _stub_storefront(respx.mock)
    respx.mock.get(f"{BASE_URL}/").mock(return_value=httpx.Response(403))

    with pytest.raises(ShopUnreachableError) as exc_info:
        run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0)
    assert exc_info.value.reason == "http_status"
    assert "403" in exc_info.value.detail


@respx.mock
def test_run_raises_on_cloudflare_marker(tmp_path: Path) -> None:
    _stub_storefront(
        respx.mock,
        index_html="<html><head><title>Just a moment...</title></head></html>",
    )

    with pytest.raises(ShopUnreachableError) as exc_info:
        run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0)
    assert exc_info.value.reason == "cloudflare_challenge"


@respx.mock
def test_run_raises_on_robots_disallow(tmp_path: Path) -> None:
    _stub_storefront(respx.mock, robots_txt="User-agent: *\nDisallow: /\n")

    with pytest.raises(ShopUnreachableError) as exc_info:
        run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0)
    assert exc_info.value.reason == "robots_disallow"

    # Aborted before fetching the homepage or anything else.
    fetched_paths = [call.request.url.path for call in respx.mock.calls]
    assert fetched_paths == ["/robots.txt"]


@respx.mock
def test_run_raises_on_network_error_for_robots(tmp_path: Path) -> None:
    respx.mock.get(f"{BASE_URL}/robots.txt").mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(ShopUnreachableError) as exc_info:
        run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0)
    assert exc_info.value.reason == "network_error"


@respx.mock
def test_run_records_non_fatal_errors_for_optional_endpoints(tmp_path: Path) -> None:
    _stub_storefront(respx.mock)
    respx.mock.get(f"{BASE_URL}/cart.js").mock(return_value=httpx.Response(404))
    respx.mock.get(f"{BASE_URL}/pages/faq").mock(side_effect=httpx.ConnectError("nope"))

    result = run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0)

    by_path = {entry.path: entry for entry in result.entries}
    cart_js = by_path["/cart.js"]
    assert cart_js.status == HTTPStatus.NOT_FOUND
    assert cart_js.saved_to is None
    assert not (tmp_path / "cart.js").exists()

    faq = by_path["/pages/faq"]
    assert faq.status is None
    assert faq.error is not None
    assert "ConnectError" in faq.error


def test_run_rejects_negative_rate_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rate_limit_ms"):
        run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=-1)


def _make_products(start: int, count: int) -> list[dict[str, Any]]:
    """Build ``count`` product dicts, ids starting at ``start``."""
    return [
        {
            "id": start + i,
            "title": f"Product {start + i}",
            "options": [{"name": "Title"}],
            "variants": [{"id": (start + i) * 10, "price": "9.99"}],
        }
        for i in range(count)
    ]


@respx.mock
def test_run_paginates_products_until_short_page(tmp_path: Path) -> None:
    """T6.4 — paginated walk merges every page and stops on the first short page."""
    _stub_storefront(respx.mock)

    page_one = _make_products(start=1, count=PRODUCTS_PAGE_LIMIT)
    page_two = _make_products(start=_PAGE_TWO_PRODUCT_START_ID, count=_PAGE_TWO_PRODUCT_COUNT)
    expected_total = PRODUCTS_PAGE_LIMIT + _PAGE_TWO_PRODUCT_COUNT
    expected_last_id = _PAGE_TWO_PRODUCT_START_ID + _PAGE_TWO_PRODUCT_COUNT - 1

    respx.mock.get(
        f"{BASE_URL}/products.json",
        params={"page": "1", "limit": str(PRODUCTS_PAGE_LIMIT)},
    ).mock(return_value=_ok(json.dumps({"products": page_one}), content_type="application/json"))
    respx.mock.get(
        f"{BASE_URL}/products.json",
        params={"page": "2", "limit": str(PRODUCTS_PAGE_LIMIT)},
    ).mock(return_value=_ok(json.dumps({"products": page_two}), content_type="application/json"))

    result = run(BASE_URL, dest_dir=tmp_path, rate_limit_ms=0)

    # The merged file on disk has every product from both pages.
    merged_raw: Any = json.loads((tmp_path / "products.json").read_text(encoding="utf-8"))
    merged_products = cast(list[dict[str, Any]], merged_raw["products"])
    assert len(merged_products) == expected_total
    assert merged_products[0]["id"] == 1
    assert merged_products[-1]["id"] == expected_last_id

    # Both pages appear as their own entries in prefetch.json. Only the
    # first page is the on-disk origin; later pages have saved_to=None.
    page_entries = [e for e in result.entries if e.path.startswith("/products.json?")]
    assert [e.path for e in page_entries] == [
        f"/products.json?page=1&limit={PRODUCTS_PAGE_LIMIT}",
        f"/products.json?page=2&limit={PRODUCTS_PAGE_LIMIT}",
    ]
    assert page_entries[0].saved_to == "products.json"
    assert page_entries[1].saved_to is None
    assert all(e.status == HTTPStatus.OK for e in page_entries)

    # No third page request — the short page two ended pagination.
    fetched_paths = [call.request.url.path for call in respx.mock.calls]
    assert fetched_paths.count("/products.json") == _EXPECTED_PAGES_FETCHED

    # stats.compute reads the merged file and reports the exact total.
    stats = compute_stats(tmp_path, Capabilities())
    assert stats.products_total == expected_total
