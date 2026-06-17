"""Unit tests for ``shop_arena.gen.build.verifiers._task_routes`` (impl plan T1.3).

Covers the SC8 fixture from the visual-verifier spec:

* ``buckets_for_task`` strips ``_redo_<n>`` suffixes (B1 prefix match).
* Multi-bucket route unions are sorted (deterministic).
* Unknown task ids resolve to the empty bucket set.
* :class:`BucketCaps` differentiation is observable in the route count
  (per-iteration vs. sweep — spec §5.6.1).
* ``capabilities_for_buckets`` filters by the bucket-keyed glob slice
  and never leaks keys outside the slice (spec §5.3.1).
"""

from __future__ import annotations

import json
from pathlib import Path

from shop_arena.gen.build.verifiers._task_routes import (
    BUCKET_CAPABILITY_KEYS,
    DEFAULT_CAPS,
    SWEEP_CAPS,
    TASK_BUCKETS,
    BucketCaps,
    bucket_routes,
    buckets_for_task,
    capabilities_for_buckets,
    routes_for_buckets,
)


def _write_dataset(
    data_dir: Path,
    *,
    collections: list[dict[str, object]] | None = None,
    products: list[dict[str, object]] | None = None,
    pages: list[dict[str, object]] | None = None,
) -> Path:
    """Lay out a minimal ``data/`` tree under ``data_dir``."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "collections.json").write_text(
        json.dumps(collections if collections is not None else []),
        encoding="utf-8",
    )
    (data_dir / "products.json").write_text(
        json.dumps(products if products is not None else []),
        encoding="utf-8",
    )
    (data_dir / "pages.json").write_text(
        json.dumps(pages if pages is not None else []),
        encoding="utf-8",
    )
    return data_dir


def _seed_dataset(data_dir: Path) -> Path:
    """Populate a representative dataset reused by most tests."""
    return _write_dataset(
        data_dir,
        collections=[
            {
                "handle": f"col-{i:02d}",
                "product_handles": [f"prod-{i:02d}-a", f"prod-{i:02d}-b"],
            }
            for i in range(10)
        ],
        products=[
            {"handle": "wireless-anti-tick-collar", "title": "Wireless Anti Tick Collar"},
            {"handle": "shopliseum-mushroom-dog-toys", "title": "Shopliseum Mushroom Dog Toys"},
        ],
        pages=[{"handle": f"page-{i:02d}", "title": f"Page {i}"} for i in range(8)],
    )


# ---------------------------------------------------------------------------
# Layer 1: task → buckets
# ---------------------------------------------------------------------------


def test_task_buckets_constant_has_seven_keys() -> None:
    """Sanity check: 6 ``gen_*`` + ``visual_fix`` (spec §5.3)."""
    assert len(TASK_BUCKETS) == 7
    assert set(TASK_BUCKETS) == {
        "gen_homepage",
        "gen_navigation",
        "gen_collections",
        "gen_product",
        "gen_cart_search",
        "gen_info_pages",
        "visual_fix",
    }


def test_bucket_capability_keys_constant_has_six_buckets() -> None:
    """Sanity check: one entry per page bucket (spec §5.3.1)."""
    assert set(BUCKET_CAPABILITY_KEYS) == {
        "homepage",
        "navigation",
        "collections",
        "product",
        "cart_search",
        "info_pages",
    }


def test_buckets_for_task_returns_homepage_for_gen_homepage() -> None:
    assert buckets_for_task("gen_homepage") == frozenset({"homepage"})


def test_buckets_for_task_strips_redo_suffix() -> None:
    """``gen_homepage_redo_3`` resolves to the same bucket set as the base task."""
    assert buckets_for_task("gen_homepage_redo_3") == frozenset({"homepage"})
    assert buckets_for_task("gen_product_redo_12") == frozenset({"product"})


def test_buckets_for_task_unknown_id_returns_empty() -> None:
    assert buckets_for_task("not_a_task") == frozenset()
    assert buckets_for_task("") == frozenset()


def test_buckets_for_task_visual_fix_covers_all_six_buckets() -> None:
    """``visual_fix`` is the only multi-bucket task that sees every bucket."""
    assert buckets_for_task("visual_fix") == frozenset(BUCKET_CAPABILITY_KEYS)


def test_buckets_for_task_redo_suffix_only_strips_trailing() -> None:
    """An embedded ``_redo_<n>`` (not at end) is not stripped."""
    # No such canonical task id exists, but the regex must be anchored.
    assert buckets_for_task("gen_redo_3_homepage") == frozenset()


# ---------------------------------------------------------------------------
# Layer 2: bucket → routes (data-driven)
# ---------------------------------------------------------------------------


def test_bucket_routes_homepage_returns_root(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    assert bucket_routes("homepage", tmp_path) == ("/",)


def test_bucket_routes_navigation_returns_root_and_collections(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    assert bucket_routes("navigation", tmp_path) == ("/", "/collections")


def test_bucket_routes_collections_caps_at_default_one(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    routes = bucket_routes("collections", tmp_path)
    # 1 collection by default → ``/collections`` + 1 collection page.
    assert routes == ("/collections", "/collections/col-00")


def test_bucket_routes_product_uses_first_collection_first_product(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    routes = bucket_routes("product", tmp_path)
    # First collection's first product handle.
    assert routes == ("/products/prod-00-a",)


def test_bucket_routes_cart_search_renders_cart_and_search(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    routes = bucket_routes("cart_search", tmp_path)
    # First product title is ``AisleArena Anti Tick Collar``; the noun-token
    # resolver skips ``wireless`` (-less suffix) and ``anti`` (prefix word),
    # landing on ``tick``. Spec §9.1 + T4.2.
    assert routes == ("/cart", "/search?q=tick")


def test_bucket_routes_info_pages_caps_and_appends_policies(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    routes = bucket_routes("info_pages", tmp_path)
    assert routes == ("/pages/page-00", "/policies/privacy")


def test_bucket_routes_unknown_bucket_returns_empty(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    assert bucket_routes("not_a_bucket", tmp_path) == ()


def test_bucket_routes_handles_missing_data_files(tmp_path: Path) -> None:
    """A missing dataset yields zero data-driven routes (no crash)."""
    # Don't seed anything.
    assert bucket_routes("collections", tmp_path) == ("/collections",)
    assert bucket_routes("product", tmp_path) == ()
    assert bucket_routes("info_pages", tmp_path) == ("/policies/privacy",)
    # Search falls back to the default token.
    assert bucket_routes("cart_search", tmp_path) == ("/cart", "/search?q=shop")


# ---------------------------------------------------------------------------
# Search-token resolution (spec §9.1 + impl plan T4.2)
# ---------------------------------------------------------------------------


def test_search_token_skips_adjective_lead_then_prefix_word(tmp_path: Path) -> None:
    """Wireless (-less suffix) and ``anti`` (prefix word) are skipped; first
    surviving token is ``tick``. Spec §9.1 + T4.2."""
    _write_dataset(
        tmp_path,
        products=[{"handle": "a", "title": "Wireless Anti Tick Collar"}],
    )
    assert bucket_routes("cart_search", tmp_path) == ("/cart", "/search?q=tick")


def test_search_token_skips_common_adjective_leads(tmp_path: Path) -> None:
    """Common adjectives (``best``, ``premium``, articles) are skipped."""
    _write_dataset(
        tmp_path,
        products=[{"handle": "a", "title": "The Best Premium Mushroom Lamp"}],
    )
    assert bucket_routes("cart_search", tmp_path) == ("/cart", "/search?q=mushroom")


def test_search_token_falls_back_to_shop_when_all_tokens_skipped(tmp_path: Path) -> None:
    """A title made entirely of stop-listed words yields the ``"shop"`` fallback."""
    _write_dataset(
        tmp_path,
        products=[{"handle": "a", "title": "The Best New Premium"}],
    )
    assert bucket_routes("cart_search", tmp_path) == ("/cart", "/search?q=shop")


def test_search_token_is_deterministic_across_reruns(tmp_path: Path) -> None:
    """Same dataset → same token, regardless of how many times it's resolved."""
    _seed_dataset(tmp_path)
    first = bucket_routes("cart_search", tmp_path)
    second = bucket_routes("cart_search", tmp_path)
    third = bucket_routes("cart_search", tmp_path)
    assert first == second == third
    assert first == ("/cart", "/search?q=tick")


def test_search_token_strips_numbers_and_punctuation(tmp_path: Path) -> None:
    """Tokens with digits / punctuation are excluded (alphabetic-only regex)."""
    _write_dataset(
        tmp_path,
        products=[{"handle": "a", "title": "2024 Edition: Ergonomic Keyboard"}],
    )
    # ``2024`` is non-alphabetic; ``edition`` is the first alpha noun-token
    # (≥ 3 chars, not stop-listed, no adjective suffix).
    assert bucket_routes("cart_search", tmp_path) == ("/cart", "/search?q=edition")


# ---------------------------------------------------------------------------
# Cap differentiation (spec §5.6.1)
# ---------------------------------------------------------------------------


def test_caps_widen_collections_and_products_for_sweep(tmp_path: Path) -> None:
    """Sweep caps surface more collections + products than the per-iter default."""
    _seed_dataset(tmp_path)
    default_collections = bucket_routes("collections", tmp_path, caps=DEFAULT_CAPS)
    sweep_collections = bucket_routes("collections", tmp_path, caps=SWEEP_CAPS)
    # Default: ``/collections`` + 1 handle. Sweep: ``/collections`` + 8 handles.
    assert len(default_collections) == 2
    assert len(sweep_collections) == 9

    default_products = bucket_routes("product", tmp_path, caps=DEFAULT_CAPS)
    sweep_products = bucket_routes("product", tmp_path, caps=SWEEP_CAPS)
    # Default: 1 product. Sweep: 8 collections x 1 product/each = 8 products.
    assert len(default_products) == 1
    assert len(sweep_products) == 8


def test_caps_widen_pages_for_sweep(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    default_pages = bucket_routes("info_pages", tmp_path, caps=DEFAULT_CAPS)
    sweep_pages = bucket_routes("info_pages", tmp_path, caps=SWEEP_CAPS)
    # Default: 1 page handle + ``/policies/privacy``.
    # Sweep: 6 page handles + ``/policies/privacy``.
    assert len(default_pages) == 2
    assert len(sweep_pages) == 7


def test_caps_default_is_used_when_none(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    assert bucket_routes("collections", tmp_path, caps=None) == bucket_routes(
        "collections",
        tmp_path,
        caps=DEFAULT_CAPS,
    )


def test_caps_zero_yields_no_data_driven_routes(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    zero = BucketCaps(max_collections=0, products_per_collection=0, max_pages=0)
    assert bucket_routes("collections", tmp_path, caps=zero) == ("/collections",)
    assert bucket_routes("product", tmp_path, caps=zero) == ()
    # info_pages always emits ``/policies/privacy`` regardless of cap.
    assert bucket_routes("info_pages", tmp_path, caps=zero) == ("/policies/privacy",)


def test_sample_product_handles_dedupes_across_collections(tmp_path: Path) -> None:
    """Duplicate product handles across collections are kept once, first-seen."""
    _write_dataset(
        tmp_path,
        collections=[
            {"handle": "a", "product_handles": ["shared", "only-a"]},
            {"handle": "b", "product_handles": ["shared", "only-b"]},
        ],
    )
    routes = bucket_routes(
        "product",
        tmp_path,
        caps=BucketCaps(max_collections=2, products_per_collection=2, max_pages=1),
    )
    assert routes == ("/products/shared", "/products/only-a", "/products/only-b")


# ---------------------------------------------------------------------------
# routes_for_buckets — sorted union over bucket sets
# ---------------------------------------------------------------------------


def test_routes_for_buckets_returns_sorted_union(tmp_path: Path) -> None:
    """Multi-bucket invocations produce a deterministic sorted union."""
    _seed_dataset(tmp_path)
    buckets = frozenset({"homepage", "navigation"})
    routes = routes_for_buckets(buckets, tmp_path)
    assert list(routes) == sorted(routes)
    assert "/" in routes
    assert "/collections" in routes
    # No duplicates: ``homepage`` and ``navigation`` both emit ``/``.
    assert len(routes) == len(set(routes))


def test_routes_for_buckets_visual_fix_covers_full_set(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    routes = routes_for_buckets(buckets_for_task("visual_fix"), tmp_path)
    # Spot-check one route per bucket.
    assert "/" in routes
    assert "/collections" in routes
    assert "/collections/col-00" in routes
    assert "/products/prod-00-a" in routes
    assert "/cart" in routes
    assert "/search?q=tick" in routes
    assert "/pages/page-00" in routes
    assert "/policies/privacy" in routes


def test_routes_for_buckets_empty_input_returns_empty(tmp_path: Path) -> None:
    _seed_dataset(tmp_path)
    assert routes_for_buckets(frozenset(), tmp_path) == ()


def test_routes_for_buckets_redo_task_resolves_same_as_base(tmp_path: Path) -> None:
    """``gen_homepage_redo_3`` and ``gen_homepage`` produce identical route lists."""
    _seed_dataset(tmp_path)
    base = routes_for_buckets(buckets_for_task("gen_homepage"), tmp_path)
    redo = routes_for_buckets(buckets_for_task("gen_homepage_redo_3"), tmp_path)
    assert base == redo


def test_routes_for_buckets_caps_propagate(tmp_path: Path) -> None:
    """The ``caps`` argument flows through to every bucket in the union."""
    _seed_dataset(tmp_path)
    visual_fix = buckets_for_task("visual_fix")
    default_routes = routes_for_buckets(visual_fix, tmp_path, caps=DEFAULT_CAPS)
    sweep_routes = routes_for_buckets(visual_fix, tmp_path, caps=SWEEP_CAPS)
    # Sweep yields strictly more routes than the per-iteration default
    # (more collections + more products + more pages).
    assert len(sweep_routes) > len(default_routes)


# ---------------------------------------------------------------------------
# capabilities_for_buckets — slice filter (spec §5.3.1)
# ---------------------------------------------------------------------------


def test_capabilities_for_buckets_homepage_excludes_collection_keys() -> None:
    capabilities = {
        "home.hero": "x",
        "home.featured": "x",
        "navigation.header": "x",
        "footer": "x",
        "collection.filters": "x",
        "product.gallery": "x",
    }
    sliced = capabilities_for_buckets({"homepage"}, capabilities)
    assert set(sliced) == {"home.hero", "home.featured", "navigation.header", "footer"}
    # Original mapping is untouched.
    assert "collection.filters" in capabilities


def test_capabilities_for_buckets_unions_across_buckets() -> None:
    capabilities = {
        "home.hero": "x",
        "collection.filters": "x",
        "product.gallery": "x",
        "cart.summary": "x",
        "search.results": "x",
    }
    sliced = capabilities_for_buckets({"collections", "cart_search"}, capabilities)
    assert set(sliced) == {"collection.filters", "cart.summary", "search.results"}


def test_capabilities_for_buckets_preserves_nested_top_level_keys() -> None:
    """Real ``capabilities.json`` uses nested top-level objects, not dotted keys."""
    capabilities = {
        "site_shell": {"header_style": "two_row_sticky"},
        "homepage": {"section_count": 11},
        "collection": {"layout": "grid"},
        "product": {"has_quantity_selector": True},
        "cart": {"type": "page"},
        "search": {"has_predictive": True},
        "info_pages_present": ["about"],
        "floating": {"has_chat_widget": False},
    }

    cart_search = capabilities_for_buckets({"cart_search"}, capabilities)
    assert cart_search == {
        "cart": {"type": "page"},
        "search": {"has_predictive": True},
    }

    visual_fix = capabilities_for_buckets(buckets_for_task("visual_fix"), capabilities)
    assert set(visual_fix) == {
        "site_shell",
        "homepage",
        "collection",
        "product",
        "cart",
        "search",
        "info_pages_present",
    }
    assert "floating" not in visual_fix


def test_capabilities_for_buckets_empty_bucket_set_returns_empty() -> None:
    """No bucket means no slice → no leakage."""
    assert capabilities_for_buckets(frozenset(), {"home.hero": "x"}) == {}


def test_capabilities_for_buckets_unknown_bucket_contributes_no_keys() -> None:
    capabilities = {"home.hero": "x", "navigation.header": "x"}
    sliced = capabilities_for_buckets({"homepage", "not_a_bucket"}, capabilities)
    # Unknown bucket adds zero patterns; result reflects only ``homepage``.
    assert set(sliced) == {"home.hero", "navigation.header"}


# ---------------------------------------------------------------------------
# T4.3 — Multi-bucket fan-out: ordering, caps, redo prefix-match (spec §5.6.1)
# ---------------------------------------------------------------------------


def test_routes_for_buckets_visual_fix_is_sorted(tmp_path: Path) -> None:
    """``visual_fix`` (all 6 buckets) returns a sorted tuple with no duplicates."""
    _seed_dataset(tmp_path)
    routes = routes_for_buckets(buckets_for_task("visual_fix"), tmp_path)
    assert list(routes) == sorted(routes)
    assert len(routes) == len(set(routes))


def test_routes_for_buckets_visual_fix_length_within_sweep_caps(tmp_path: Path) -> None:
    """Sweep caps bound the visual_fix union length (spec §5.6.1)."""
    _seed_dataset(tmp_path)
    routes = routes_for_buckets(
        buckets_for_task("visual_fix"),
        tmp_path,
        caps=SWEEP_CAPS,
    )
    # homepage(1) + navigation(2 — overlaps with homepage/collections) +
    # collections(1 + max_collections) + product(max_collections *
    # products_per_collection) + cart_search(2) + info_pages(max_pages + 1).
    upper_bound = (
        1
        + 2
        + (1 + SWEEP_CAPS.max_collections)
        + (SWEEP_CAPS.max_collections * SWEEP_CAPS.products_per_collection)
        + 2
        + (SWEEP_CAPS.max_pages + 1)
    )
    assert len(routes) <= upper_bound


def test_routes_for_buckets_visual_fix_redo_resolves_same_as_base(tmp_path: Path) -> None:
    """``visual_fix_redo_5`` produces identical routes to ``visual_fix``."""
    _seed_dataset(tmp_path)
    base = routes_for_buckets(buckets_for_task("visual_fix"), tmp_path)
    redo = routes_for_buckets(buckets_for_task("visual_fix_redo_5"), tmp_path)
    assert base == redo


def test_routes_for_buckets_redo_resolves_same_under_sweep_caps(tmp_path: Path) -> None:
    """Redo prefix-match coverage holds under sweep caps too (spec §5.3 layer 1)."""
    _seed_dataset(tmp_path)
    base = routes_for_buckets(
        buckets_for_task("visual_fix"),
        tmp_path,
        caps=SWEEP_CAPS,
    )
    redo = routes_for_buckets(
        buckets_for_task("visual_fix_redo_9"),
        tmp_path,
        caps=SWEEP_CAPS,
    )
    assert base == redo
