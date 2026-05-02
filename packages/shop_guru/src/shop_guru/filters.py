"""Filter heuristics used across generators.

Keeping these in one place makes it easy to extend the "skip list" for
back-office collections or the set of keywords used to match policy pages.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

SKIP_COLLECTION_TITLE_EXACT: frozenset[str] = frozenset({
    "all",
    "sale",
    "new arrival",
    "new arrivals",
    "gift card",
    "gift cards",
    "best seller",
    "best sellers",
    "featured",
})


SKIP_COLLECTION_TITLE_TOKENS: tuple[str, ...] = (
    "promo",
    "eligible",
    "test collection",
    "internal",
    "staff only",
    "wholesale",
    "draft",
    "automation",
)


def is_generic_collection(title: str) -> bool:
    """Return True if a collection title looks like a back-office / catchall.

    Examples::

        >>> is_generic_collection("All")
        True
        >>> is_generic_collection("Promo Eligible Products")
        True
        >>> is_generic_collection("Dog Dentals")
        False
    """
    low = title.strip().lower()
    if low in SKIP_COLLECTION_TITLE_EXACT:
        return True
    return any(tok in low for tok in SKIP_COLLECTION_TITLE_TOKENS)


def collections_with_min_products(
    collections: Iterable[dict], min_products: int = 3
) -> list[dict]:
    """Keep only non-generic collections with at least ``min_products``."""
    out = []
    for c in collections:
        handles = c.get("product_handles") or []
        if len(handles) >= min_products and not is_generic_collection(c.get("title", "")):
            out.append(c)
    return out


def pages_matching(pages: Iterable[dict], patterns: Iterable[str]) -> list[dict]:
    """Return pages whose title or handle starts a word with one of ``patterns``.

    Uses a leading word boundary but no trailing one so that e.g. the pattern
    ``ship`` matches ``shipping`` and ``ship-info`` while still rejecting
    ``sponsorship``. Handles are normalized by replacing ``-`` with spaces
    before matching.

    Example::

        >>> pages_matching(
        ...     [{"title": "About", "handle": "about"},
        ...      {"title": "Shipping Info", "handle": "shipping-info"},
        ...      {"title": "Event Sponsorship", "handle": "sponsorship"}],
        ...     ["ship"],
        ... )
        [{'title': 'Shipping Info', 'handle': 'shipping-info'}]
    """
    regexes = [re.compile(rf"\b{re.escape(pat.lower())}") for pat in patterns]
    out: list[dict] = []
    for page in pages:
        title = (page.get("title") or "").lower()
        handle = (page.get("handle") or "").lower().replace("-", " ")
        hay = f"{title} {handle}"
        if any(r.search(hay) for r in regexes):
            out.append(page)
    return out
