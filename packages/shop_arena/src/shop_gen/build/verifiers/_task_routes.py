"""Task → buckets → (routes, capabilities) resolution (impl plan T1.3).

Two-layer model from spec §5.3 + §9.1.

* **Layer 1 — task → buckets.** ``TASK_BUCKETS`` is a static map from a
  ``gen_*`` / ``visual_fix`` task id to a small set of page **buckets**.
  :func:`buckets_for_task` strips a trailing
  ``_redo_<n>`` suffix (B1 prefix match, §5.3 layer 1) before lookup so
  the redo flow (``gen_homepage_redo_3``) reuses the base task's scope.
* **Layer 2 — bucket → routes.** :func:`bucket_routes` reads
  ``data/{collections,products,pages}.json`` at run time so resolved
  routes always carry real handles. Per-bucket caps (1 collection / 1
  product / 1 page by default) are bundled in :class:`BucketCaps`. The
  build-loop verifier passes the tight defaults; the final-eval visual
  sweep widens via §5.6.1.

Also exposes :data:`BUCKET_CAPABILITY_KEYS` (the static slice keys per
bucket) and :func:`capabilities_for_buckets`, the ``fnmatch``-based
filter used to keep ``capabilities.json`` aligned with the rendered
routes (§5.3.1). Without slicing, a homepage judge would see "missing
collection filters!" in the prompt and spuriously FAIL.

The bucket axis is shared with the page-bucket fan-out (§5.2.1 step 5)
and the page weights table (§9.5) — one taxonomy, three uses.

Module is import-safe: no I/O, no env reads, no side effects at import
time.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Final, cast

__all__ = [
    "BUCKET_CAPABILITY_KEYS",
    "DEFAULT_CAPS",
    "PAGE_WEIGHTS",
    "SWEEP_CAPS",
    "TASK_BUCKETS",
    "BucketCaps",
    "bucket_routes",
    "buckets_for_task",
    "capabilities_for_buckets",
    "routes_for_buckets",
]


@dataclass(frozen=True, slots=True)
class BucketCaps:
    """Per-bucket sampling caps for :func:`bucket_routes`.

    Both the build-loop ``visual_judge`` (per-iteration ``visual_fix``
    invocations) and the final-eval visual sweep flow through the same
    :func:`routes_for_buckets` entry point with different cap profiles
    (spec §5.6.1). The verifier passes :data:`DEFAULT_CAPS` (tight: 1
    collection, 1 product, 1 page); the sweep passes :data:`SWEEP_CAPS`
    (wider: 8 collections, 1 product per collection, 6 pages).

    Attributes:
        max_collections: Upper bound on collection handles drawn from
            ``data/collections.json``. Drives ``/collections/<handle>``
            route count.
        products_per_collection: Upper bound on product handles drawn
            from each sampled collection's ``product_handles`` list.
            Drives ``/products/<handle>`` route count.
        max_pages: Upper bound on page handles drawn from
            ``data/pages.json``. Drives ``/pages/<handle>`` route count.
    """

    max_collections: int = 1
    products_per_collection: int = 1
    max_pages: int = 1


DEFAULT_CAPS: Final[BucketCaps] = BucketCaps(
    max_collections=1,
    products_per_collection=1,
    max_pages=1,
)
"""Tight per-iteration caps used by ``visual_judge`` (spec §5.6.1)."""


SWEEP_CAPS: Final[BucketCaps] = BucketCaps(
    max_collections=8,
    products_per_collection=1,
    max_pages=6,
)
"""Wider caps used by ``final_eval``'s visual sweep (spec §5.6.1)."""


TASK_BUCKETS: Final[dict[str, frozenset[str]]] = {
    "gen_homepage": frozenset({"homepage"}),
    "gen_navigation": frozenset({"navigation"}),
    "gen_collections": frozenset({"collections"}),
    "gen_product": frozenset({"product"}),
    "gen_cart_search": frozenset({"cart_search"}),
    "gen_info_pages": frozenset({"info_pages"}),
    "visual_fix": frozenset(
        {
            "homepage",
            "navigation",
            "collections",
            "product",
            "cart_search",
            "info_pages",
        },
    ),
}
"""Task id → page-bucket set (spec §5.3 layer 1).

Keyed by the *base* task id; :func:`buckets_for_task` strips a trailing
``_redo_<n>`` before lookup so redo task ids (``gen_homepage_redo_3``)
reuse the base task's bucket set.
"""


BUCKET_CAPABILITY_KEYS: Final[dict[str, frozenset[str]]] = {
    "homepage": frozenset({"home.*", "navigation.header", "footer"}),
    "navigation": frozenset({"navigation.*", "footer"}),
    "collections": frozenset({"collection.*"}),
    "product": frozenset({"product.*"}),
    "cart_search": frozenset({"cart.*", "search.*"}),
    "info_pages": frozenset({"page.*", "policies.*"}),
}
"""Bucket → ``capabilities.json`` key globs (spec §5.3.1).

Keys are shell-glob patterns matched via :func:`fnmatch.fnmatch`; the
union over the active bucket set filters the capabilities slice handed
to the agent so it never sees (and never penalises the absence of)
features that belong to a different bucket.
"""


PAGE_WEIGHTS: Final[dict[str, float]] = {
    "homepage": 0.25,
    "navigation": 0.20,
    "collections": 0.20,
    "product": 0.20,
    "cart_search": 0.08,
    "info_pages": 0.07,
}
"""Page-bucket weights for merging per-bucket verdicts (spec §9.5).

Used by :class:`shop_gen.build.verifiers.visual_judge.VisualJudgeVerifier`
to merge ``visual_fix``-task fan-out results (T5.7) and by
the :mod:`shop_gen.final_eval.visual_sweep` driver (T5.3) to compute
the overall sweep score. Buckets absent from a fan-out are dropped from
both numerator and denominator so the weighted average stays well-defined.
"""


_REDO_SUFFIX: Final[re.Pattern[str]] = re.compile(r"_redo_\d+$")
"""Trailing ``_redo_<n>`` suffix on redo task ids; stripped before lookup."""


def buckets_for_task(task_id: str) -> frozenset[str]:
    """Resolve a task id to its page-bucket set.

    Strips a trailing ``_redo_<n>`` suffix (B1 prefix match, spec §5.3
    layer 1) and looks the result up in :data:`TASK_BUCKETS`. Unknown
    task ids return the empty set; the caller (the verifier) maps that
    to a :attr:`~harness.verifiers.Verdict.ERROR` per spec §5.2.1 step 1.

    Args:
        task_id: Selected task id from
            :attr:`harness.verifiers.VerifierContext.selected_task_id`.

    Returns:
        Frozen set of bucket names; empty when ``task_id`` is unknown.
    """
    base = _REDO_SUFFIX.sub("", task_id)
    return TASK_BUCKETS.get(base, frozenset())


def bucket_routes(  # noqa: PLR0911 - one return per bucket case, intentionally explicit
    bucket: str,
    data_dir: Path,
    *,
    caps: BucketCaps | None = None,
) -> tuple[str, ...]:
    """Resolve a single bucket to its concrete route list.

    Reads ``data/{collections,products,pages}.json`` for the data-driven
    buckets so the returned routes carry real handles. Sampling is
    deterministic (first N entries by file order) and capped via
    ``caps`` so reruns reuse the same evidence set.

    Args:
        bucket: One of the keys in :data:`BUCKET_CAPABILITY_KEYS`. An
            unknown bucket returns the empty tuple.
        data_dir: Directory containing the published ``collections``,
            ``products``, and ``pages`` JSON files.
        caps: Sampling caps; defaults to :data:`DEFAULT_CAPS` when
            ``None``.

    Returns:
        Routes the bucket should render, in deterministic source order
        (no per-bucket sort — that happens at the union level in
        :func:`routes_for_buckets`).
    """
    effective = caps if caps is not None else DEFAULT_CAPS
    match bucket:
        case "homepage":
            return ("/",)
        case "navigation":
            return ("/", "/collections")
        case "collections":
            handles = _read_collection_handles(data_dir)[: effective.max_collections]
            return ("/collections", *(f"/collections/{h}" for h in handles))
        case "product":
            handles = _sample_product_handles(
                data_dir,
                max_collections=effective.max_collections,
                products_per_collection=effective.products_per_collection,
            )
            return tuple(f"/products/{h}" for h in handles)
        case "cart_search":
            return ("/cart", f"/search?q={_sample_search_token(data_dir)}")
        case "info_pages":
            handles = _read_page_handles(data_dir)[: effective.max_pages]
            return (*(f"/pages/{h}" for h in handles), "/policies/privacy")
        case _:
            return ()


def routes_for_buckets(
    buckets: Iterable[str],
    data_dir: Path,
    *,
    caps: BucketCaps | None = None,
) -> tuple[str, ...]:
    """Sorted union of :func:`bucket_routes` over ``buckets``.

    Multi-bucket invocations (``visual_fix``, the final-eval sweep)
    take the union; sorting makes the result deterministic across
    reruns and across bucket-set orderings.

    Args:
        buckets: Bucket names; unknown bucket names contribute no routes.
        data_dir: Directory containing the published data JSON files.
        caps: Sampling caps applied uniformly across buckets; defaults
            to :data:`DEFAULT_CAPS` when ``None``.

    Returns:
        Deterministic sorted tuple of route paths.
    """
    routes: set[str] = set()
    for bucket in buckets:
        routes.update(bucket_routes(bucket, data_dir, caps=caps))
    return tuple(sorted(routes))


def capabilities_for_buckets(
    buckets: Iterable[str],
    capabilities: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter a ``capabilities.json`` mapping to the active bucket slice.

    Takes the union of :data:`BUCKET_CAPABILITY_KEYS` over the active
    buckets, then keeps every capability key that ``fnmatch``-es one of
    the patterns. Unknown bucket names contribute no patterns; an empty
    bucket set yields an empty result (no leaks).

    Args:
        buckets: Bucket names; unknown buckets are silently skipped so
            this can absorb stray names from upstream maps.
        capabilities: The ``capabilities.json`` mapping (already loaded
            into a dict).

    Returns:
        A new dict with only the keys belonging to the slice; the
        original mapping is not mutated.
    """
    keys: set[str] = set()
    for bucket in buckets:
        keys.update(BUCKET_CAPABILITY_KEYS.get(bucket, frozenset()))
    if not keys:
        return {}
    return {k: v for k, v in capabilities.items() if any(fnmatch(k, p) for p in keys)}


# ---------------------------------------------------------------------------
# Data-driven helpers (private)
# ---------------------------------------------------------------------------


def _read_collection_handles(data_dir: Path) -> list[str]:
    """Return ordered collection handles from ``data/collections.json``."""
    return _read_handles(data_dir / "collections.json")


def _read_page_handles(data_dir: Path) -> list[str]:
    """Return ordered page handles from ``data/pages.json``."""
    return _read_handles(data_dir / "pages.json")


def _read_handles(path: Path) -> list[str]:
    """Return the ``handle`` field of every record under ``path``.

    A missing or unreadable file returns an empty list — the caller's
    :class:`BucketCaps` then yields zero routes for the affected bucket
    rather than raising. Phase 2 should have populated every dataset
    before Phase 4 runs; this fallback only triggers when something
    upstream has misbehaved.
    """
    raw = _load_json_list(path)
    if raw is None:
        return []
    handles: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        handle = cast("dict[str, Any]", entry).get("handle")
        if isinstance(handle, str) and handle:
            handles.append(handle)
    return handles


def _sample_product_handles(
    data_dir: Path,
    *,
    max_collections: int,
    products_per_collection: int,
) -> list[str]:
    """Sample product handles by walking the first N collections.

    For each of the first ``max_collections`` collections (in source
    order), takes up to ``products_per_collection`` handles from the
    collection's ``product_handles`` list. Duplicates across collections
    are dropped while preserving first-seen order.

    Spec §5.3 layer 2 ("1 product per collection" defaults).
    """
    raw = _load_json_list(data_dir / "collections.json")
    if raw is None:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for entry in raw[:max_collections]:
        if not isinstance(entry, dict):
            continue
        product_handles = cast("dict[str, Any]", entry).get("product_handles")
        if not isinstance(product_handles, list):
            continue
        taken = 0
        for handle in cast("list[Any]", product_handles):
            if taken >= products_per_collection:
                break
            if not isinstance(handle, str) or not handle or handle in seen:
                continue
            seen.add(handle)
            out.append(handle)
            taken += 1
    return out


def _sample_search_token(data_dir: Path) -> str:
    """Pick a deterministic noun-token from ``data/products.json``.

    Walks the first product title left to right and returns the first
    token that is *not* an obvious non-noun (article, preposition,
    conjunction, prefix, common adjective, or word with a clear
    adjective/adverb suffix). The result is deterministic per dataset:
    the same ``products.json`` always yields the same token, regardless
    of run order. Spec §9.1 + impl plan T4.2.

    Empty / missing dataset, or a title whose tokens are all skipped,
    falls back to ``"shop"`` so the resulting ``/search?q=…`` URL is
    still well-formed.
    """
    raw = _load_json_list(data_dir / "products.json")
    if raw is None:
        return "shop"
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = cast("dict[str, Any]", entry).get("title")
        if not isinstance(title, str):
            continue
        token = _first_noun_token(title)
        if token is not None:
            return token
    return "shop"


_NON_NOUN_WORDS: Final[frozenset[str]] = frozenset(
    {
        # Articles, conjunctions, common prepositions.
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "yet",
        "so",
        "of",
        "for",
        "with",
        "without",
        "in",
        "on",
        "at",
        "to",
        "by",
        "from",
        "as",
        "into",
        "onto",
        "per",
        # Standalone prefix-style words.
        "anti",
        "non",
        "pre",
        "post",
        "sub",
        "super",
        "ultra",
        # Common adjectives that frequently lead product titles.
        "new",
        "old",
        "big",
        "small",
        "large",
        "tiny",
        "mini",
        "best",
        "great",
        "good",
        "better",
        "premium",
        "luxury",
        "deluxe",
        "free",
        "easy",
        "soft",
        "hard",
        "light",
        "dark",
        "pure",
        "fresh",
    },
)
"""Stoplist of obvious non-noun words skipped by :func:`_first_noun_token`."""


_ADJECTIVE_SUFFIXES: Final[tuple[str, ...]] = ("less", "ish")
"""Suffixes that reliably mark adjectives (e.g. ``tickless``, ``greenish``)."""


_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]+")
"""Alphabetic tokens; numbers / punctuation are skipped."""


_MIN_TOKEN_LEN: Final[int] = 3
"""Single- and two-letter tokens are too short to be useful search queries."""


def _first_noun_token(title: str) -> str | None:
    """Return the first noun-like alphabetic token from ``title``.

    A token is considered noun-like when it is alphabetic, at least
    :data:`_MIN_TOKEN_LEN` characters long, not in :data:`_NON_NOUN_WORDS`,
    and does not end in any of :data:`_ADJECTIVE_SUFFIXES`. The check is
    intentionally lightweight: it rejects the obvious adjective /
    function-word leads typical of product titles (``Tickless Anti …``,
    ``Best Premium …``) without pulling in a full POS tagger.

    Returns ``None`` when no token in ``title`` qualifies, leaving the
    caller's ``"shop"`` fallback in charge of route well-formedness.
    """
    for raw in _TOKEN_RE.findall(title):
        token = raw.lower()
        if len(token) < _MIN_TOKEN_LEN:
            continue
        if token in _NON_NOUN_WORDS:
            continue
        if token.endswith(_ADJECTIVE_SUFFIXES):
            continue
        return token
    return None


def _load_json_list(path: Path) -> list[Any] | None:
    """Load ``path`` as a JSON list; return ``None`` on any read error."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(body, list):
        return None
    return cast("list[Any]", body)
