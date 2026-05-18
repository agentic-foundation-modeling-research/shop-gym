"""URL canonicalization for the structural BFS.

The transition graph collapses URLs into *page classes* so that, e.g.,
``/products/red-shirt`` and ``/products/blue-shirt`` map to the same node
``/products/<*>``. This module centralizes the rules so :mod:`bfs` and
:mod:`graph` stay focused on traversal and metrics.

Canonicalization rules implemented here:

* resolve relative ``href`` values against the run's base URL,
* reject non-HTTP schemes (``mailto:``, ``tel:``, ``javascript:``),
* reject cross-host links (same-host filtering),
* reject in-domain asset paths (Shopify's ``/fast-image/`` image
  transformation endpoint and ``/cdn/`` CDN) — these serve binary files,
  not pages,
* reject paths whose tail matches a non-page file extension
  (``.xml``, ``.json``, ``.txt``, ``.pdf``, image formats) — covers
  ``/sitemap.xml`` and similar resources reachable via ``<a href>``,
* reject paths containing ``:`` — these always come from a CMS wrapping
  a ``mailto:`` link the storefront authored with broken syntax,
* drop fragment **and** query for the canonical id,
* collapse ``/products/<*>``, ``/collections/<*>``, ``/policies/<*>``,
  ``/blogs/<*>``, ``/account/<*>`` (a single slug segment is replaced;
  the literal ``/products/``, ``/collections/``, ``/policies/``,
  ``/blogs/``, ``/account/`` index paths are left untouched). The
  ``/blogs/`` and ``/account/`` rules collapse the entire subtree —
  ``/blogs/<blog>/<post>`` and ``/account/orders/<id>`` are not
  shopping affordances, so the graph treats them as one node each.
* collapse ``/pages/<rest>`` to ``/pages/<*>`` only when ``rest`` is
  in the caller-supplied ``collapse_pages`` set. ``rest`` is the full
  string after ``/pages/`` including any further ``/<sub>`` segments
  (e.g. ``"gift-bundle/coming-home-set"``). The set is typically
  populated by :mod:`shop_arena.env_eval.transition.pages_classifier`,
  which classifies discovered ``/pages/`` slugs and surfaces the
  collapse-eligible ones (currently the ``"marketing"`` label) as a
  frozen set the BFS threads through every canonicalization call.
  The default empty set means "never collapse ``/pages/``", which is
  the safe identity behavior for callers that do not run the
  classifier.
* leave ``/``, ``/cart``, ``/search`` etc. as themselves.

The module exposes pure helpers — no I/O, no Playwright, no globals —
so it is trivially unit-testable and shared by the structural pass and
the stateful pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

__all__ = [
    "DISALLOWED_PATH_PREFIXES",
    "DISALLOWED_PATH_SUFFIXES",
    "DISALLOWED_SCHEMES",
    "PAGES_PREFIX",
    "TEMPLATE_PREFIXES",
    "CanonicalLink",
    "canonical_id_for_path",
    "canonical_id_for_url",
    "canonicalize_href",
    "is_in_domain",
]

#: Schemes that are never followed by the BFS.
DISALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"mailto", "tel", "javascript"})

#: In-domain path prefixes that serve binary assets, not pages, and must be
#: rejected before they enter the BFS frontier. ``/fast-image/`` is Shopify's
#: image transformation endpoint and ``/cdn/`` is the Shopify CDN — every
#: link under either is an asset reachable from product pages, so including
#: them explodes the node count without contributing real navigation
#: affordances.
DISALLOWED_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "/fast-image/",
    "/cdn/",
)

#: Path suffixes (file extensions) that always identify non-page resources.
#: Matched case-insensitively against the path tail; covers ``/sitemap.xml``
#: and direct asset/download links the storefront sometimes exposes via
#: ``<a href>``. Reject early so the BFS does not attempt to navigate to
#: them and then drop the response.
DISALLOWED_PATH_SUFFIXES: Final[tuple[str, ...]] = (
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
)

#: Path prefixes whose entire suffix is collapsed to ``<*>``. Order is
#: irrelevant — the prefixes are disjoint. ``/blogs/``
#: and ``/account/`` collapse multi-segment subtrees because individual
#: blog posts and account subpages are not distinct shopping affordances.
TEMPLATE_PREFIXES: Final[tuple[str, ...]] = (
    "/products/",
    "/collections/",
    "/policies/",
    "/blogs/",
    "/account/",
)

#: Shopify's catch-all for static pages: a single namespace mixing terse
#: info slugs (``/pages/warranty``, ``/pages/faq``) with sentence-shaped
#: marketing/campaign slugs (``/pages/gordons-golden-ticket-paris-rules``).
#: Treated specially — collapse is driven by an explicit ``collapse_pages``
#: set the caller supplies (typically populated by
#: :mod:`shop_arena.env_eval.transition.pages_classifier`).
PAGES_PREFIX: Final[str] = "/pages/"


@dataclass(frozen=True, slots=True)
class CanonicalLink:
    """Canonicalized view of a single ``href`` resolved against a base URL.

    Attributes:
        canonical_id: Host-relative path used as the transition graph
            node id. Query and fragment are dropped; template prefixes
            are collapsed (e.g. ``/products/<*>``).
        representative_url: Absolute URL with query and fragment dropped.
            BFS enqueues this — never the templated ``canonical_id`` —
            so :func:`Page.goto` always navigates to a concrete URL
            so :func:`Page.goto` always navigates to a concrete URL.
        relative_path: Host-relative path with query and fragment dropped
            but **without** template collapsing. Useful for traces and
            for callers that want to display the concrete URL path.
    """

    canonical_id: str
    representative_url: str
    relative_path: str


def is_in_domain(url: str, base_url: str) -> bool:
    """Return ``True`` iff ``url`` shares a host with ``base_url``.

    Both arguments are expected to be absolute. The comparison is on the
    raw ``netloc`` (host + optional port), matching the rule used by
    :mod:`pages` so the two layers cannot disagree.

    Args:
        url: Absolute URL to classify.
        base_url: Absolute base URL of the storefront under evaluation.

    Returns:
        ``True`` if ``urlsplit(url).netloc == urlsplit(base_url).netloc``.
    """
    return urlsplit(url).netloc == urlsplit(base_url).netloc


def canonical_id_for_path(
    path: str,
    *,
    collapse_pages: frozenset[str] = frozenset(),
) -> str:
    """Return the canonical graph-node id for a host-relative ``path``.

    Drops any ``?query`` or ``#fragment`` and collapses the first path
    segment under each of :data:`TEMPLATE_PREFIXES` to ``<*>``. The
    bare prefix itself (e.g. ``/products/`` with no slug) is left
    untouched because it is the index page, not an item.

    ``/pages/<rest>`` is collapsed conditionally: ``rest`` (the full
    string after ``/pages/`` including any nested ``/<sub>`` segments,
    with any trailing ``/`` stripped) is collapsed to ``/pages/<*>`` iff
    it appears in ``collapse_pages``. Otherwise the path is returned
    verbatim. The bare ``/pages/`` index path is always left untouched.
    Trailing-slash normalisation makes ``/pages/foo`` and ``/pages/foo/``
    look up the same classifier entry.

    Args:
        path: A host-relative path. Must start with ``"/"``; the empty
            string and ``""`` are normalised to ``"/"``.
        collapse_pages: Set of post-``/pages/`` paths the caller has
            decided should collapse to ``/pages/<*>``. Empty by default,
            which means ``/pages/`` is never collapsed.

    Returns:
        The canonical id (always starts with ``"/"``).
    """
    if not path:
        return "/"
    bare = path.split("?", 1)[0].split("#", 1)[0]
    if not bare:
        return "/"
    for prefix in TEMPLATE_PREFIXES:
        if bare.startswith(prefix) and len(bare) > len(prefix):
            return prefix + "<*>"
    if bare.startswith(PAGES_PREFIX) and len(bare) > len(PAGES_PREFIX):
        # Normalise the lookup key so ``/pages/foo`` and ``/pages/foo/``
        # share the same classifier entry; the BFS frontier resolves both
        # forms to the same canonical id.
        rest = bare[len(PAGES_PREFIX) :].rstrip("/")
        if rest and rest in collapse_pages:
            return f"{PAGES_PREFIX}<*>"
    return bare


def canonical_id_for_url(
    url: str,
    *,
    collapse_pages: frozenset[str] = frozenset(),
) -> str:
    """Return the canonical graph-node id for an absolute or relative URL.

    The host portion is discarded — the graph keys nodes by host-relative
    path because the run is single-domain by construction. Query and
    fragment are dropped and template prefixes are collapsed via
    :func:`canonical_id_for_path`.

    Args:
        url: Absolute URL (``https://shop.example/products/x?ref=1``) or
            host-relative path (``/products/x``). An empty path becomes
            ``"/"``.
        collapse_pages: Threaded through to
            :func:`canonical_id_for_path`. See its docstring for the
            ``/pages/`` collapse semantics.

    Returns:
        The canonical id.
    """
    parts = urlsplit(url)
    return canonical_id_for_path(parts.path or "/", collapse_pages=collapse_pages)


def _scheme_and_host_allowed(parts: SplitResult, base_url: str) -> bool:
    """Return ``True`` if ``parts`` is an in-domain HTTP(S) URL."""
    scheme = parts.scheme.lower()
    if scheme in DISALLOWED_SCHEMES:
        return False
    if scheme not in {"http", "https"}:
        return False
    return parts.netloc == urlsplit(base_url).netloc


def _path_allowed(relative_path: str) -> bool:
    """Return ``True`` if ``relative_path`` is a candidate page path.

    Rejects asset endpoints (``/fast-image/``, ``/cdn/``), file-extension
    URLs (``/sitemap.xml``, image/document downloads), and paths whose
    raw form contains ``:`` (a CMS authoring error — typically a broken
    ``mailto:`` link wrapped in ``/pages/``).
    """
    if any(relative_path.startswith(prefix) for prefix in DISALLOWED_PATH_PREFIXES):
        return False
    lowered = relative_path.lower()
    if any(lowered.endswith(suffix) for suffix in DISALLOWED_PATH_SUFFIXES):
        return False
    return ":" not in relative_path


def canonicalize_href(
    href: str,
    base_url: str,
    *,
    collapse_pages: frozenset[str] = frozenset(),
) -> CanonicalLink | None:
    """Resolve an ``href`` and apply the BFS canonicalization rules.

    Returns ``None`` when the href must not enter the BFS frontier:

    * the scheme is in :data:`DISALLOWED_SCHEMES`,
    * the resolved host differs from ``base_url`` (cross-host link),
    * the resolved scheme is not ``http`` or ``https`` (e.g. ``data:``,
      ``ftp:``),
    * the path begins with one of :data:`DISALLOWED_PATH_PREFIXES`
      (in-domain asset endpoints like Shopify's ``/fast-image/`` or
      ``/cdn/``),
    * the path ends with one of :data:`DISALLOWED_PATH_SUFFIXES`
      (file extensions for non-page resources like ``/sitemap.xml``),
    * the path contains ``":"`` — these uniformly come from a CMS
      wrapping a ``mailto:`` link as ``/pages/mail%20to:foo@bar``.

    Otherwise the returned :class:`CanonicalLink` carries both the
    template-collapsed ``canonical_id`` (graph key) and the concrete
    ``representative_url`` (suitable for ``page.goto``).

    Args:
        href: Raw ``href`` attribute, possibly relative
            (``/cart``, ``products/x``, ``../policy``) or absolute
            (``https://other.example/x``).
        base_url: Absolute base URL of the storefront. Drives both
            relative-href resolution and the same-host filter.
        collapse_pages: Threaded through to
            :func:`canonical_id_for_path`. See its docstring for the
            ``/pages/`` collapse semantics.

    Returns:
        A :class:`CanonicalLink` for in-domain HTTP(S) links, else
        ``None``.
    """
    if not href:
        return None
    abs_url = urljoin(base_url, href.strip())
    parts = urlsplit(abs_url)
    if not _scheme_and_host_allowed(parts, base_url):
        return None
    relative_path = parts.path or "/"
    if not _path_allowed(relative_path):
        return None
    # Drop query+fragment from the representative URL too: the canonical
    # id is query-stripped and the BFS only needs one concrete URL per
    # node.
    representative_url = urlunsplit((parts.scheme, parts.netloc, relative_path, "", ""))
    canonical_id = canonical_id_for_path(relative_path, collapse_pages=collapse_pages)
    return CanonicalLink(
        canonical_id=canonical_id,
        representative_url=representative_url,
        relative_path=relative_path,
    )
