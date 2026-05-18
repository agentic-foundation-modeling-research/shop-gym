"""Unit tests for :mod:`shop_arena.env_eval.transition.canonicalize` (M4).

Spec §5.5.1 demands a fully deterministic href → graph-node mapping.
These tests pin every documented rule:

* relative href resolution against the run's base URL,
* same-host filtering (cross-host links rejected),
* non-HTTP scheme rejection (``mailto:``, ``tel:``, ``javascript:``),
* fragment + query dropped from the canonical id and representative URL,
* template prefix collapsing for ``/products/``, ``/collections/``,
  ``/policies/`` (but the bare index pages are left alone),
* ``/pages/<rest>`` collapses only when ``rest`` is in the explicit
  ``collapse_pages`` set the caller threads through.
"""

from __future__ import annotations

import pytest

from shop_arena.env_eval.transition.canonicalize import (
    DISALLOWED_PATH_PREFIXES,
    DISALLOWED_PATH_SUFFIXES,
    DISALLOWED_SCHEMES,
    TEMPLATE_PREFIXES,
    CanonicalLink,
    canonical_id_for_path,
    canonical_id_for_url,
    canonicalize_href,
    is_in_domain,
)

BASE: str = "https://shop.example.com/"


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_disallowed_schemes_match_spec() -> None:
    """Spec §5.5.1 lists exactly three disallowed schemes."""
    assert frozenset({"mailto", "tel", "javascript"}) == DISALLOWED_SCHEMES


def test_template_prefixes_match_spec() -> None:
    """Spec §5.5.1 collapses these five Shopify URL families."""
    assert set(TEMPLATE_PREFIXES) == {
        "/products/",
        "/collections/",
        "/policies/",
        "/blogs/",
        "/account/",
    }


def test_disallowed_path_prefixes_match_spec() -> None:
    """Spec §5.5.1 rejects in-domain asset endpoints before the BFS sees them."""
    assert set(DISALLOWED_PATH_PREFIXES) == {"/fast-image/", "/cdn/"}


def test_disallowed_path_suffixes_match_spec() -> None:
    """Spec §5.5.1 rejects file-extension URLs before the BFS sees them."""
    assert set(DISALLOWED_PATH_SUFFIXES) == {
        ".xml",
        ".json",
        ".txt",
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
    }


# ---------------------------------------------------------------------------
# canonical_id_for_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "/"),
        ("", "/"),
        ("/cart", "/cart"),
        ("/search", "/search"),
        ("/account", "/account"),
        ("/products/linen-shirt", "/products/<*>"),
        ("/products/linen-shirt/", "/products/<*>"),
        ("/collections/men", "/collections/<*>"),
        ("/policies/privacy-policy", "/policies/<*>"),
        # Bare index paths must NOT be collapsed (no slug after prefix).
        ("/products/", "/products/"),
        ("/collections/", "/collections/"),
        ("/policies/", "/policies/"),
        ("/blogs/", "/blogs/"),
        ("/account/", "/account/"),
        # Query and fragment are dropped before collapsing.
        ("/products/x?ref=hp", "/products/<*>"),
        ("/products/x#reviews", "/products/<*>"),
        ("/cart?utm=x", "/cart"),
        ("/cart#open", "/cart"),
        # /blogs/ subtree collapses for posts and the blog index alike.
        ("/blogs/news", "/blogs/<*>"),
        ("/blogs/news/some-post-slug", "/blogs/<*>"),
        # /account/ subtree collapses for every authenticated subpath.
        ("/account/orders/12345", "/account/<*>"),
        ("/account/addresses", "/account/<*>"),
    ],
)
def test_canonical_id_for_path_collapses_template_prefixes(path: str, expected: str) -> None:
    """Each template prefix gets exactly one slug segment collapsed."""
    assert canonical_id_for_path(path) == expected


# ---------------------------------------------------------------------------
# canonical_id_for_path — /pages/ behaviour is driven by collapse_pages
# ---------------------------------------------------------------------------


def test_canonical_id_for_path_preserves_pages_slug_by_default() -> None:
    """With no ``collapse_pages`` set, every ``/pages/<rest>`` stays verbatim."""
    assert canonical_id_for_path("/pages/anything-here") == "/pages/anything-here"
    assert canonical_id_for_path("/pages/warranty") == "/pages/warranty"
    assert (
        canonical_id_for_path("/pages/gift-bundle/coming-home-set")
        == "/pages/gift-bundle/coming-home-set"
    )


def test_canonical_id_for_path_collapses_pages_when_in_set() -> None:
    """Single-segment slugs in ``collapse_pages`` collapse to ``/pages/<*>``."""
    collapse = frozenset({"foo-bar"})
    assert canonical_id_for_path("/pages/foo-bar", collapse_pages=collapse) == "/pages/<*>"
    # Slugs not in the set still pass through.
    assert canonical_id_for_path("/pages/warranty", collapse_pages=collapse) == "/pages/warranty"


def test_canonical_id_for_path_collapses_subpath_when_in_set() -> None:
    """Multi-segment ``/pages/<a>/<b>`` collapses when the full ``rest`` is in the set."""
    collapse = frozenset({"gift-bundle/coming-home-set"})
    assert (
        canonical_id_for_path(
            "/pages/gift-bundle/coming-home-set",
            collapse_pages=collapse,
        )
        == "/pages/<*>"
    )


def test_canonical_id_for_path_pages_index_untouched() -> None:
    """The bare ``/pages/`` index path is never collapsed regardless of ``collapse_pages``."""
    collapse = frozenset({"warranty", "faq"})
    assert canonical_id_for_path("/pages/", collapse_pages=collapse) == "/pages/"
    assert canonical_id_for_path("/pages/") == "/pages/"


def test_canonical_id_for_path_trailing_slash_normalized() -> None:
    """Trailing ``/`` after the slug is stripped before the ``collapse_pages`` lookup."""
    collapse = frozenset({"foo"})
    assert canonical_id_for_path("/pages/foo/", collapse_pages=collapse) == "/pages/<*>"
    # The set keys remain canonical: a slug with a trailing slash in the
    # set itself does not change the lookup result for the unsuffixed form.
    assert canonical_id_for_path("/pages/foo", collapse_pages=collapse) == "/pages/<*>"


# ---------------------------------------------------------------------------
# canonical_id_for_url
# ---------------------------------------------------------------------------


def test_canonical_id_for_url_strips_host_and_query() -> None:
    """Absolute URLs collapse to host-relative canonical ids."""
    assert canonical_id_for_url("https://shop.example.com/products/x?ref=1#x") == "/products/<*>"


def test_canonical_id_for_url_handles_relative_input() -> None:
    """Host-relative input is accepted unchanged."""
    assert canonical_id_for_url("/collections/men") == "/collections/<*>"


def test_canonical_id_for_url_empty_path_is_root() -> None:
    """A URL with no path component (``https://x``) maps to ``/``."""
    assert canonical_id_for_url("https://shop.example.com") == "/"


def test_canonical_id_for_url_threads_collapse_pages() -> None:
    """The ``collapse_pages`` kwarg propagates through ``canonical_id_for_url``."""
    collapse = frozenset({"foo-bar"})
    assert (
        canonical_id_for_url(
            "https://shop.example.com/pages/foo-bar?ref=hp",
            collapse_pages=collapse,
        )
        == "/pages/<*>"
    )
    # Without the kwarg the path is preserved verbatim.
    assert (
        canonical_id_for_url("https://shop.example.com/pages/foo-bar?ref=hp")
        == "/pages/foo-bar"
    )


# ---------------------------------------------------------------------------
# is_in_domain
# ---------------------------------------------------------------------------


def test_is_in_domain_true_for_same_host() -> None:
    """Same scheme + host means in-domain."""
    assert is_in_domain("https://shop.example.com/cart", BASE) is True


def test_is_in_domain_false_for_cross_host() -> None:
    """Different host is rejected."""
    assert is_in_domain("https://other.example.com/", BASE) is False


def test_is_in_domain_distinguishes_subdomains() -> None:
    """A subdomain has a different ``netloc`` and is therefore out-of-domain."""
    assert is_in_domain("https://www.shop.example.com/", BASE) is False


# ---------------------------------------------------------------------------
# canonicalize_href — happy path
# ---------------------------------------------------------------------------


def test_canonicalize_href_resolves_relative_path() -> None:
    """Relative hrefs are resolved against ``base_url``."""
    link = canonicalize_href("/products/linen-shirt", BASE)
    assert link == CanonicalLink(
        canonical_id="/products/<*>",
        representative_url="https://shop.example.com/products/linen-shirt",
        relative_path="/products/linen-shirt",
    )


def test_canonicalize_href_drops_query_and_fragment() -> None:
    """Both ``?query`` and ``#fragment`` are stripped (spec §5.5.1)."""
    link = canonicalize_href("/products/x?ref=hp#reviews", BASE)
    assert link is not None
    assert link.canonical_id == "/products/<*>"
    assert link.representative_url == "https://shop.example.com/products/x"
    assert link.relative_path == "/products/x"


def test_canonicalize_href_handles_absolute_in_domain_url() -> None:
    """Absolute URLs to the same host are accepted."""
    link = canonicalize_href("https://shop.example.com/cart", BASE)
    assert link is not None
    assert link.canonical_id == "/cart"
    assert link.representative_url == "https://shop.example.com/cart"


def test_canonicalize_href_resolves_dotted_relative_paths() -> None:
    """``../`` segments resolve via :func:`urllib.parse.urljoin`."""
    base = "https://shop.example.com/collections/men/"
    link = canonicalize_href("../women", base)
    assert link is not None
    assert link.canonical_id == "/collections/<*>"
    assert link.relative_path == "/collections/women"


def test_canonicalize_href_threads_collapse_pages() -> None:
    """``collapse_pages`` propagates from ``canonicalize_href`` to the canonical id."""
    collapse = frozenset({"foo-bar"})
    link = canonicalize_href("/pages/foo-bar?utm=hp", BASE, collapse_pages=collapse)
    assert link is not None
    assert link.canonical_id == "/pages/<*>"
    # ``relative_path`` keeps the concrete path (no template collapsing).
    assert link.relative_path == "/pages/foo-bar"
    # Default empty set leaves the path verbatim.
    plain = canonicalize_href("/pages/foo-bar", BASE)
    assert plain is not None
    assert plain.canonical_id == "/pages/foo-bar"


def test_canonicalize_href_homepage_root_normalises_to_slash() -> None:
    """An empty-path absolute URL yields canonical id ``"/"``."""
    link = canonicalize_href("https://shop.example.com", BASE)
    assert link is not None
    assert link.canonical_id == "/"
    assert link.relative_path == "/"
    assert link.representative_url == "https://shop.example.com/"


def test_canonicalize_href_strips_surrounding_whitespace() -> None:
    """Real-world hrefs sometimes carry stray whitespace; trim before parsing."""
    link = canonicalize_href("  /cart  ", BASE)
    assert link is not None
    assert link.canonical_id == "/cart"


# ---------------------------------------------------------------------------
# canonicalize_href — rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href",
    [
        "mailto:hello@shop.example.com",
        "tel:+15551234567",
        "javascript:void(0)",
        "JavaScript:alert(1)",  # case-insensitive scheme match
    ],
)
def test_canonicalize_href_rejects_disallowed_schemes(href: str) -> None:
    """``mailto:``, ``tel:``, ``javascript:`` are dropped."""
    assert canonicalize_href(href, BASE) is None


def test_canonicalize_href_rejects_cross_host() -> None:
    """Cross-host links are not enqueued."""
    assert canonicalize_href("https://cdn.other.com/x", BASE) is None


def test_canonicalize_href_rejects_non_http_schemes() -> None:
    """Non-HTTP schemes (``data:``, ``ftp:``) are not followed."""
    assert canonicalize_href("data:text/plain;base64,AAA=", BASE) is None
    assert canonicalize_href("ftp://shop.example.com/file.txt", BASE) is None


def test_canonicalize_href_rejects_empty_href() -> None:
    """Empty hrefs (``<a href="">``) are skipped."""
    assert canonicalize_href("", BASE) is None


@pytest.mark.parametrize(
    "href",
    [
        "/fast-image/example-shop/files/Berry_Hoodie_7.jpg",
        "https://shop.example.com/fast-image/example-shop/files/Untitled.jpg",
        "/cdn/shop/products/huge.jpg",
        "https://shop.example.com/cdn/shop/files/icon.svg",
    ],
)
def test_canonicalize_href_rejects_asset_path_prefixes(href: str) -> None:
    """In-domain asset endpoints (``/fast-image/``, ``/cdn/``) are not pages."""
    assert canonicalize_href(href, BASE) is None


def test_canonicalize_href_does_not_reject_lookalike_path() -> None:
    """Only the literal ``/fast-image/`` prefix is rejected, not substrings."""
    link = canonicalize_href("/products/fast-image-hoodie", BASE)
    assert link is not None
    assert link.canonical_id == "/products/<*>"


@pytest.mark.parametrize(
    "href",
    [
        "/sitemap.xml",
        "/feed.json",
        "/robots.txt",
        "/files/manual.pdf",
        "/cdn/IMAGE.JPG",  # case-insensitive
        "/some/icon.ico",
    ],
)
def test_canonicalize_href_rejects_file_extension_paths(href: str) -> None:
    """Paths that resolve to non-page files (``/sitemap.xml``, etc.) are dropped."""
    assert canonicalize_href(href, BASE) is None


@pytest.mark.parametrize(
    "href",
    [
        "/pages/mail%20to:%contact@mock-shop.example",
        "/some/path/with:colon",
    ],
)
def test_canonicalize_href_rejects_paths_with_colon(href: str) -> None:
    """``:`` in the path is always a malformed link (typically a broken mailto)."""
    assert canonicalize_href(href, BASE) is None


def test_canonicalize_href_rejects_pure_fragment() -> None:
    """A ``#section`` href stays on the same canonical page; BFS skips it.

    Without explicit handling, ``urljoin(base, "#x")`` returns the base
    URL, which would re-enqueue the homepage. The frontier dedup will
    catch that, but returning a link still passes the canonical id back
    — verify the behaviour is well-defined (canonical id of the base).
    """
    link = canonicalize_href("#section", BASE)
    assert link is not None
    assert link.canonical_id == "/"
    assert link.representative_url == "https://shop.example.com/"
