"""Unit tests for ``shop_arena.env_eval.pages`` (impl plan M1).

Covers the core spec §5.2 contract:

* :func:`normalize_base_url` strips path/query/fragment and forces a
  trailing slash.
* :func:`discover_pages` walks the five-bucket flow against a fake
  discovery driver — homepage failure aborts loud, collection picks the
  first non-``/all`` href, product falls back through collection then
  homepage, policy uses the convention then footer fallback, cart_and_search
  derives a query from the product title and visits ``/search?q=...``.
* :func:`write_pages_json` / :func:`read_pages_json` round-trip a
  :class:`PagesDoc` byte-stably.
* :func:`load_or_discover` reuses ``pages.json`` on the second call and
  re-runs discovery when ``rediscover=True``.

The richer edge-case matrix (404 nuances, raw-source recording, scheme
filtering, link-text nav labels) is exercised in the dedicated edge-case
tests at the bottom of this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shop_arena.env_eval.errors import PageDiscoveryError, ShopUnreachableError
from shop_arena.env_eval.pages import (
    PAGES_JSON_FILENAME,
    CartAndSearch,
    PageNotFound,
    PageOk,
    PagesDoc,
    SearchPageOk,
    discover_pages,
    load_or_discover,
    normalize_base_url,
    read_pages_json,
    write_pages_json,
)

# ---------------------------------------------------------------------------
# Fake discovery driver.
# ---------------------------------------------------------------------------


@dataclass
class _FakeBrowser:
    """Hand-rolled :class:`DiscoveryBrowser` for hermetic tests.

    ``hrefs_by_path`` and ``texts_by_path`` are keyed by the *path* part
    of the URL (everything after the host) so callers don't have to
    concatenate the base URL into every fixture entry.
    """

    base_url: str
    hrefs_by_path: dict[str, list[str]]
    texts_by_path: dict[tuple[str, str], str | None] = field(default_factory=lambda: {})
    link_texts_by_path: dict[str, list[tuple[str, str]]] = field(
        default_factory=lambda: {},
    )
    status_by_path: dict[str, int] = field(default_factory=lambda: {})
    goto_log: list[str] = field(default_factory=lambda: [])
    current_path: str = "/"

    def _path_of(self, url: str) -> str:
        # Strip the configured base so lookups are path-keyed.
        if url.startswith(self.base_url):
            tail = url[len(self.base_url) :]
            return "/" + tail if not tail.startswith("/") else tail
        return url

    def goto(self, url: str) -> int | None:
        path = self._path_of(url)
        self.goto_log.append(path)
        self.current_path = path
        return self.status_by_path.get(path)

    def hrefs(self, selector: str = "a[href]") -> list[str]:
        del selector  # Not exercised by these tests.
        return list(self.hrefs_by_path.get(self.current_path, []))

    def link_texts(self, selector: str) -> list[tuple[str, str]]:
        del selector  # The fake browser only models ``a[href]`` selectors.
        configured = self.link_texts_by_path.get(self.current_path)
        if configured is not None:
            return list(configured)
        # Default: pair each href with an empty label so existing tests
        # that only set ``hrefs_by_path`` keep working unchanged.
        return [(h, "") for h in self.hrefs_by_path.get(self.current_path, [])]

    def text(self, selector: str) -> str | None:
        return self.texts_by_path.get((self.current_path, selector))


def _abs(base: str, path: str) -> str:
    """Concat helper so test fixtures can use bare paths."""
    return base.rstrip("/") + path


# ---------------------------------------------------------------------------
# normalize_base_url
# ---------------------------------------------------------------------------


def test_normalize_base_url_strips_path_query_fragment() -> None:
    """``scheme://host/`` is the only normalised shape (spec §5.2)."""
    normalised = normalize_base_url("https://example-shop.com/collections/men?x=1#frag")
    assert normalised == "https://example-shop.com/"


def test_normalize_base_url_preserves_port() -> None:
    """Non-default ports stay attached to the netloc."""
    assert normalize_base_url("http://localhost:8080/cart") == "http://localhost:8080/"


def test_normalize_base_url_rejects_input_without_scheme() -> None:
    """A bare hostname is not a usable storefront URL."""
    with pytest.raises(ValueError, match="invalid storefront URL"):
        normalize_base_url("example-shop.com")


# ---------------------------------------------------------------------------
# discover_pages — happy path
# ---------------------------------------------------------------------------


def _build_happy_browser() -> _FakeBrowser:
    """Storefront with: men/women collections, a product, privacy policy, cart, search."""
    base = "https://example-shop.com/"
    return _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                _abs(base, "/collections/all"),
                _abs(base, "/collections/men"),
                _abs(base, "/products/loose-shirt"),
                _abs(base, "/policies/privacy-policy"),
            ],
            "/collections/men": [
                _abs(base, "/products/linen-shirt"),
                _abs(base, "/products/loose-shirt"),
            ],
            "/products/linen-shirt": [],
            "/policies/privacy-policy": [],
            "/cart": [],
            "/search?q=linen+shirt": [],
        },
        texts_by_path={
            ("/products/linen-shirt", "h1"): "Linen Shirt",
        },
    )


def test_discover_pages_picks_expected_buckets_on_happy_path() -> None:
    """Every bucket is ``ok`` and selection rules match spec §5.2."""
    browser = _build_happy_browser()

    doc = discover_pages(session=None, base_url=browser.base_url, browser=browser)  # type: ignore[arg-type]

    assert doc.base_url == "https://example-shop.com/"
    assert isinstance(doc.homepage, PageOk)
    assert doc.homepage.url == "/"
    assert doc.homepage.selected_by == "input"

    assert isinstance(doc.collection, PageOk)
    assert doc.collection.url == "/collections/men"
    assert doc.collection.canonical_url == "/collections/<*>"
    assert doc.collection.selected_by == "first_href"

    assert isinstance(doc.product, PageOk)
    assert doc.product.url == "/products/linen-shirt"
    assert doc.product.canonical_url == "/products/<*>"
    assert doc.product.selected_by == "first_href"

    assert isinstance(doc.policy, PageOk)
    assert doc.policy.url == "/policies/privacy-policy"
    assert doc.policy.canonical_url == "/policies/<*>"
    assert doc.policy.selected_by == "convention"

    assert isinstance(doc.cart_and_search.cart, PageOk)
    assert doc.cart_and_search.cart.url == "/cart"

    assert isinstance(doc.cart_and_search.search, SearchPageOk)
    assert doc.cart_and_search.search.url == "/search?q=linen+shirt"
    assert doc.cart_and_search.search.query == "linen shirt"
    assert doc.cart_and_search.search.selected_by == "product_title"
    assert doc.cart_and_search.search.raw_source == "Linen Shirt"


def test_discover_pages_collection_falls_back_to_all_when_no_specific_link() -> None:
    """No ``/collections/<slug>`` other than ``/all`` → fallback path is used."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={"/": [_abs(base, "/collections/all")], "/collections/all": []},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.collection, PageOk)
    assert doc.collection.url == "/collections/all"
    assert doc.collection.selected_by == "fallback_path"


def test_discover_pages_product_falls_back_to_homepage_link() -> None:
    """No product link on collection → scan homepage hrefs."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                _abs(base, "/collections/men"),
                _abs(base, "/products/homepage-product"),
            ],
            "/collections/men": [],  # Empty — no product on collection.
            "/products/homepage-product": [],
        },
        texts_by_path={("/products/homepage-product", "h1"): "Homepage Product"},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.product, PageOk)
    assert doc.product.url == "/products/homepage-product"


def test_discover_pages_marks_product_not_found_when_no_link_anywhere() -> None:
    """No ``/products/<*>`` on either page → ``not_found`` with reason."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [_abs(base, "/collections/men")],
            "/collections/men": [],
        },
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.product, PageNotFound)
    assert doc.product.reason == "no_product_link"


def test_discover_pages_policy_falls_back_to_footer_href_on_404() -> None:
    """``/policies/privacy-policy`` 404 → first ``/policies/<*>`` from homepage."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                _abs(base, "/collections/men"),
                _abs(base, "/policies/terms-of-service"),
            ],
            "/collections/men": [],
            "/policies/terms-of-service": [],
        },
        status_by_path={"/policies/privacy-policy": 404},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.policy, PageOk)
    assert doc.policy.url == "/policies/terms-of-service"
    assert doc.policy.selected_by == "first_href"


def test_discover_pages_marks_policy_not_found_when_nothing_works() -> None:
    """No convention path and no footer policy hrefs → ``not_found``."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={"/": [_abs(base, "/collections/men")], "/collections/men": []},
        status_by_path={"/policies/privacy-policy": 404},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.policy, PageNotFound)
    assert doc.policy.reason == "no_policy_link"


def test_discover_pages_search_query_uses_product_slug_when_no_title() -> None:
    """Title text missing → fall through to ``product_slug``."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                _abs(base, "/collections/men"),
                _abs(base, "/products/blue-suede-shoes"),
            ],
            "/collections/men": [_abs(base, "/products/blue-suede-shoes")],
            "/products/blue-suede-shoes": [],
        },
        # No h1 text registered → the title candidate fails.
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.cart_and_search.search, SearchPageOk)
    search = doc.cart_and_search.search
    assert search.selected_by == "product_slug"
    # Generic words like "shop" are dropped; "blue-suede-shoes" → 3 tokens.
    assert search.query == "blue suede shoes"
    assert search.url == "/search?q=blue+suede+shoes"


def test_discover_pages_marks_search_not_found_when_no_query_inferable() -> None:
    """No product, no collection, no nav labels → ``no_search_query``."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={"/": [], "/collections/all": []},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.cart_and_search.search, PageNotFound)
    assert doc.cart_and_search.search.reason == "no_search_query"


def test_discover_pages_aborts_when_homepage_returns_4xx() -> None:
    """Homepage 503 → :class:`ShopUnreachableError` (spec §5.2 step 1)."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={"/": []},
        status_by_path={"/": 503},
    )

    with pytest.raises(ShopUnreachableError, match="HTTP 503"):
        discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]


def test_discover_pages_filters_cross_host_hrefs() -> None:
    """Off-domain hrefs are skipped during selection."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                "https://other-cdn.example/collections/external",
                _abs(base, "/collections/men"),
            ],
            "/collections/men": [],
        },
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.collection, PageOk)
    assert doc.collection.url == "/collections/men"


# ---------------------------------------------------------------------------
# pages.json round-trip
# ---------------------------------------------------------------------------


def _sample_doc() -> PagesDoc:
    return PagesDoc(
        base_url="https://example-shop.com/",
        homepage=PageOk(url="/", selected_by="input"),
        collection=PageOk(
            url="/collections/men",
            canonical_url="/collections/<*>",
            selected_by="first_href",
        ),
        product=PageOk(
            url="/products/linen-shirt",
            canonical_url="/products/<*>",
            selected_by="first_href",
        ),
        policy=PageOk(
            url="/policies/privacy-policy",
            canonical_url="/policies/<*>",
            selected_by="convention",
        ),
        cart_and_search=CartAndSearch(
            cart=PageOk(url="/cart", selected_by="convention"),
            search=SearchPageOk(
                url="/search?q=linen+shirt",
                query="linen shirt",
                selected_by="product_title",
                raw_source="Linen Shirt",
            ),
        ),
    )


def test_write_then_read_pages_json_round_trips(tmp_path: Path) -> None:
    """``write`` / ``read`` are byte-stable inverses."""
    doc = _sample_doc()

    path = write_pages_json(doc, tmp_path)

    assert path == tmp_path / PAGES_JSON_FILENAME
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert read_pages_json(tmp_path) == doc


def test_read_pages_json_rejects_unknown_keys(tmp_path: Path) -> None:
    """Closed schema: unknown top-level keys raise :class:`PageDiscoveryError`."""
    payload: dict[str, Any] = _sample_doc().model_dump(mode="json")
    payload["bogus_key"] = 1
    target = tmp_path / PAGES_JSON_FILENAME
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PageDiscoveryError, match="schema validation"):
        read_pages_json(tmp_path)


def test_read_pages_json_raises_on_missing_file(tmp_path: Path) -> None:
    """Missing file → :class:`PageDiscoveryError`, never bare ``OSError``."""
    with pytest.raises(PageDiscoveryError, match="cannot read"):
        read_pages_json(tmp_path)


# ---------------------------------------------------------------------------
# load_or_discover reuse
# ---------------------------------------------------------------------------


def test_load_or_discover_reuses_existing_pages_json(tmp_path: Path) -> None:
    """Existing ``pages.json`` short-circuits discovery (spec §5.7)."""
    doc = _sample_doc()
    write_pages_json(doc, tmp_path)
    browser = _FakeBrowser(base_url="https://example-shop.com/", hrefs_by_path={"/": []})

    out = load_or_discover(
        session=None,  # type: ignore[arg-type]
        base_url="https://example-shop.com/",
        run_dir=tmp_path,
        browser=browser,
    )

    assert out == doc
    # No navigation happened — discovery was skipped entirely.
    assert browser.goto_log == []


def test_load_or_discover_rediscovers_when_flag_is_set(tmp_path: Path) -> None:
    """``rediscover=True`` ignores the cached file and overwrites it."""
    # Seed cache with a doc that points at /collections/old.
    cached = _sample_doc().model_copy(
        update={
            "collection": PageOk(
                url="/collections/old",
                canonical_url="/collections/<*>",
                selected_by="first_href",
            ),
        },
    )
    write_pages_json(cached, tmp_path)

    browser = _build_happy_browser()
    out = load_or_discover(
        session=None,  # type: ignore[arg-type]
        base_url=browser.base_url,
        run_dir=tmp_path,
        rediscover=True,
        browser=browser,
    )

    assert isinstance(out.collection, PageOk)
    assert out.collection.url == "/collections/men"
    # Cache was overwritten.
    on_disk = read_pages_json(tmp_path)
    assert on_disk == out


# ---------------------------------------------------------------------------
# Edge cases: scheme filtering, query/fragment stripping, 4xx handling,
# link-text nav labels, relative href resolution.
# ---------------------------------------------------------------------------


def test_discover_pages_strips_query_and_fragment_from_bucket_urls() -> None:
    """Tracking params + fragments on hrefs do not leak into ``pages.json``."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                _abs(base, "/collections/men?utm_source=ig#hero"),
                _abs(base, "/products/linen-shirt?variant=42#reviews"),
                _abs(base, "/policies/privacy-policy?ref=footer"),
            ],
            "/collections/men": [],
            "/products/linen-shirt": [],
            "/policies/privacy-policy": [],
        },
        texts_by_path={("/products/linen-shirt", "h1"): "Linen Shirt"},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.collection, PageOk)
    assert doc.collection.url == "/collections/men"
    assert isinstance(doc.product, PageOk)
    assert doc.product.url == "/products/linen-shirt"
    assert isinstance(doc.policy, PageOk)
    assert doc.policy.url == "/policies/privacy-policy"
    # Buckets navigated without the tracking params.
    assert "/collections/men" in browser.goto_log
    assert "/products/linen-shirt" in browser.goto_log


def test_discover_pages_filters_disallowed_scheme_hrefs() -> None:
    """``mailto:``/``tel:``/``javascript:`` hrefs never enter selection."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                "mailto:hello@example-shop.com",
                "tel:+15555555555",
                "javascript:void(0)",
                _abs(base, "/collections/men"),
            ],
            "/collections/men": [
                "javascript:openModal()",
                _abs(base, "/products/linen-shirt"),
            ],
            "/products/linen-shirt": [],
        },
        texts_by_path={("/products/linen-shirt", "h1"): "Linen Shirt"},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.collection, PageOk)
    assert doc.collection.url == "/collections/men"
    assert isinstance(doc.product, PageOk)
    assert doc.product.url == "/products/linen-shirt"


def test_discover_pages_resolves_relative_hrefs_against_base() -> None:
    """Relative hrefs (no leading slash, no host) resolve to the base host."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            # Bare path-relative hrefs (e.g. ``collections/men``) are what
            # ``urljoin(base, …)`` is meant to resolve.
            "/": ["collections/men", "products/linen-shirt"],
            "/collections/men": ["products/linen-shirt"],
            "/products/linen-shirt": [],
        },
        texts_by_path={("/products/linen-shirt", "h1"): "Linen Shirt"},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.collection, PageOk)
    assert doc.collection.url == "/collections/men"
    assert isinstance(doc.product, PageOk)
    assert doc.product.url == "/products/linen-shirt"


def test_discover_pages_collection_returns_not_found_on_4xx() -> None:
    """First-href collection that returns 404 is recorded as ``not_found``."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [_abs(base, "/collections/seasonal")],
            "/collections/seasonal": [],
        },
        status_by_path={"/collections/seasonal": 404},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.collection, PageNotFound)
    assert doc.collection.reason == "collection_http_404"


def test_discover_pages_cart_returns_not_found_on_4xx() -> None:
    """Cart 503 is recorded as ``cart_http_503`` and search still resolves."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [
                _abs(base, "/collections/men"),
                _abs(base, "/products/linen-shirt"),
            ],
            "/collections/men": [_abs(base, "/products/linen-shirt")],
            "/products/linen-shirt": [],
        },
        texts_by_path={("/products/linen-shirt", "h1"): "Linen Shirt"},
        status_by_path={"/cart": 503},
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.cart_and_search.cart, PageNotFound)
    assert doc.cart_and_search.cart.reason == "cart_http_503"
    # Search bucket is independent of cart status.
    assert isinstance(doc.cart_and_search.search, SearchPageOk)
    assert doc.cart_and_search.search.query == "linen shirt"


def test_discover_pages_uses_link_text_for_nav_label_raw_source() -> None:
    """With no product/collection, ``nav_label`` raw_source is the link text."""
    base = "https://example-shop.com/"
    browser = _FakeBrowser(
        base_url=base,
        hrefs_by_path={
            "/": [_abs(base, "/pages/lookbook")],
            "/collections/all": [],
        },
        link_texts_by_path={
            "/": [
                # Generic word "Shop" filtered by stopwords → first link
                # contributes nothing; second wins on its label.
                (_abs(base, "/collections/all"), "Shop"),
                (_abs(base, "/pages/lookbook"), "Lookbook 2024"),
            ],
        },
    )

    doc = discover_pages(session=None, base_url=base, browser=browser)  # type: ignore[arg-type]

    assert isinstance(doc.cart_and_search.search, SearchPageOk)
    search = doc.cart_and_search.search
    assert search.selected_by == "nav_label"
    assert search.query == "lookbook 2024"
    assert search.raw_source == "Lookbook 2024"
