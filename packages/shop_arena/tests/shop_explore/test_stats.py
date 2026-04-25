"""Unit tests for :mod:`shop_explore.stats`.

Covers the requirements from
``docs/impl/shop_explore_implementation.md`` T1.5:

* Pure function over fixture ``prefetch/`` directories.
* Truncation flag set when ``products.json`` returns ≥ 50 entries.
* Aggregations (per-collection counts, prices, variants pct, axes).
* ``feature_count`` derived from a closed :class:`Capabilities` model.
* Closed schema rejects unknown fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shop_explore.capabilities import Capabilities
from shop_explore.stats import (
    PRODUCTS_LIMIT,
    PriceStats,
    ProductsPerCollection,
    Stats,
    compute,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PRODUCTS_BELOW_LIMIT = 7
"""Arbitrary product count strictly below ``PRODUCTS_LIMIT`` for truncation tests."""

COLLECTION_COUNTS_FOUR = (10, 20, 30, 60)
"""Four ``products_count`` values used for distribution-aggregation assertions."""
COLLECTION_AVG_FOUR = 30.0
COLLECTION_MEDIAN_FOUR = 25.0
COLLECTION_MAX_FOUR = 60

VARIANT_AXES_EXPECTED = ["size", "color", "material"]
"""First-encountered, lower-cased, deduped axes for the variant-axes test."""

EXPECTED_FEATURE_COUNT = 8
"""Sum from the spec example used in :func:`test_compute_feature_count_*`."""

NAV_DEPTH = 3
HOMEPAGE_SECTION_COUNT = 5
INFO_PAGES = ["about", "contact", "shipping_policy"]


def _write(prefetch_dir: Path, name: str, data: Any) -> None:
    prefetch_dir.mkdir(parents=True, exist_ok=True)
    prefetch_dir.joinpath(name).write_text(json.dumps(data), encoding="utf-8")


def _product(
    *,
    variants: list[dict[str, Any]] | None = None,
    options: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": 1,
        "handle": "p",
        "title": "Product",
        "variants": variants if variants is not None else [{"price": "10.00"}],
        "options": options if options is not None else [],
    }


def _empty_caps() -> Capabilities:
    return Capabilities()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_stats_rejects_unknown_field() -> None:
    with pytest.raises(ValueError, match=r"bogus"):
        Stats.model_validate({"products_total": 1, "bogus": True})


def test_stats_defaults_are_zeros_and_empty() -> None:
    stats = Stats()
    assert stats.products_total == 0
    assert stats.products_truncated is False
    assert stats.collections_total == 0
    assert stats.products_per_collection == ProductsPerCollection()
    assert stats.price == PriceStats()
    assert stats.products_with_variants_pct == 0.0
    assert stats.variant_axes_observed == []
    assert stats.feature_count == 0


# ---------------------------------------------------------------------------
# compute() — error paths
# ---------------------------------------------------------------------------


def test_compute_missing_prefetch_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute(tmp_path / "nope", _empty_caps())


def test_compute_prefetch_dir_is_file_raises(tmp_path: Path) -> None:
    file_path = tmp_path / "prefetch"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        compute(file_path, _empty_caps())


def test_compute_malformed_products_json_raises(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    prefetch.joinpath("products.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match=r"products\.json"):
        compute(prefetch, _empty_caps())


# ---------------------------------------------------------------------------
# compute() — empty / missing prefetch
# ---------------------------------------------------------------------------


def test_compute_empty_prefetch_returns_zeroed_stats(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    stats = compute(prefetch, _empty_caps())
    assert stats == Stats()


def test_compute_unexpected_shape_collapses_to_empty(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(prefetch, "products.json", [1, 2, 3])  # not the {"products": [...]} shape
    _write(prefetch, "collections.json", "no collections")
    stats = compute(prefetch, _empty_caps())
    assert stats.products_total == 0
    assert stats.collections_total == 0


# ---------------------------------------------------------------------------
# compute() — products / truncation
# ---------------------------------------------------------------------------


def test_compute_products_total_below_limit_not_truncated(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(
        prefetch,
        "products.json",
        {"products": [_product() for _ in range(PRODUCTS_BELOW_LIMIT)]},
    )
    stats = compute(prefetch, _empty_caps())
    assert stats.products_total == PRODUCTS_BELOW_LIMIT
    assert stats.products_truncated is False


def test_compute_products_at_limit_marks_truncated(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(
        prefetch,
        "products.json",
        {"products": [_product() for _ in range(PRODUCTS_LIMIT)]},
    )
    stats = compute(prefetch, _empty_caps())
    assert stats.products_total == PRODUCTS_LIMIT
    assert stats.products_truncated is True


# ---------------------------------------------------------------------------
# compute() — collections
# ---------------------------------------------------------------------------


def test_compute_products_per_collection_aggregates(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(
        prefetch,
        "collections.json",
        {
            "collections": [
                {"id": index, "products_count": count}
                for index, count in enumerate(COLLECTION_COUNTS_FOUR, start=1)
            ]
        },
    )
    stats = compute(prefetch, _empty_caps())
    assert stats.collections_total == len(COLLECTION_COUNTS_FOUR)
    assert stats.products_per_collection.avg == pytest.approx(COLLECTION_AVG_FOUR)
    assert stats.products_per_collection.median == pytest.approx(COLLECTION_MEDIAN_FOUR)
    assert stats.products_per_collection.max == COLLECTION_MAX_FOUR


def test_compute_products_per_collection_ignores_missing_counts(tmp_path: Path) -> None:
    sole_count = 5
    raw_collections = [
        {"id": 1},  # missing products_count
        {"id": 2, "products_count": "10"},  # wrong type, skipped
        {"id": 3, "products_count": sole_count},
    ]
    prefetch = tmp_path / "prefetch"
    _write(prefetch, "collections.json", {"collections": raw_collections})
    stats = compute(prefetch, _empty_caps())
    assert stats.collections_total == len(raw_collections)
    assert stats.products_per_collection == ProductsPerCollection(
        avg=float(sole_count), median=float(sole_count), max=sole_count
    )


def test_compute_no_collections_yields_zeroed_collection_stats(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(prefetch, "collections.json", {"collections": []})
    stats = compute(prefetch, _empty_caps())
    assert stats.collections_total == 0
    assert stats.products_per_collection == ProductsPerCollection()


# ---------------------------------------------------------------------------
# compute() — prices
# ---------------------------------------------------------------------------


def test_compute_price_stats_from_variants(tmp_path: Path) -> None:
    expected_min = 12.0
    expected_max = 100.0
    expected_median = 44.5
    prefetch = tmp_path / "prefetch"
    _write(
        prefetch,
        "products.json",
        {
            "products": [
                _product(variants=[{"price": "12.00"}, {"price": "24.00"}]),
                _product(variants=[{"price": "100.00"}]),
                _product(variants=[{"price": 65.0}]),  # numeric price tolerated
            ]
        },
    )
    stats = compute(prefetch, _empty_caps())
    assert stats.price.min == pytest.approx(expected_min)
    assert stats.price.max == pytest.approx(expected_max)
    assert stats.price.median == pytest.approx(expected_median)


def test_compute_price_currency_from_capabilities_takes_priority(
    tmp_path: Path,
) -> None:
    prefetch = tmp_path / "prefetch"
    _write(prefetch, "products.json", {"products": [_product()]})
    _write(prefetch, "cart.js", {"currency": "USD"})
    caps = Capabilities.model_validate({"shop": {"currency": "EUR"}})
    stats = compute(prefetch, caps)
    assert stats.price.currency == "EUR"


def test_compute_price_currency_falls_back_to_cart_js(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(prefetch, "products.json", {"products": [_product()]})
    _write(prefetch, "cart.js", {"currency": "GBP"})
    stats = compute(prefetch, _empty_caps())
    assert stats.price.currency == "GBP"


def test_compute_price_currency_empty_when_unknown(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(prefetch, "products.json", {"products": [_product()]})
    stats = compute(prefetch, _empty_caps())
    assert stats.price.currency == ""


def test_compute_ignores_unparseable_prices(tmp_path: Path) -> None:
    expected_price = 5.0
    prefetch = tmp_path / "prefetch"
    _write(
        prefetch,
        "products.json",
        {
            "products": [
                _product(variants=[{"price": "not-a-price"}, {"price": "5.00"}]),
            ]
        },
    )
    stats = compute(prefetch, _empty_caps())
    assert stats.price.min == pytest.approx(expected_price)
    assert stats.price.max == pytest.approx(expected_price)


# ---------------------------------------------------------------------------
# compute() — variants
# ---------------------------------------------------------------------------


def test_compute_products_with_variants_pct(tmp_path: Path) -> None:
    expected_pct = 0.5
    prefetch = tmp_path / "prefetch"
    _write(
        prefetch,
        "products.json",
        {
            "products": [
                _product(variants=[{"price": "10"}]),  # 1 variant → not "with variants"
                _product(variants=[{"price": "10"}, {"price": "20"}]),
                _product(variants=[{"price": "10"}, {"price": "20"}, {"price": "30"}]),
                _product(variants=[]),
            ]
        },
    )
    stats = compute(prefetch, _empty_caps())
    assert stats.products_with_variants_pct == pytest.approx(expected_pct)


def test_compute_variant_axes_dedup_and_lowercase(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    _write(
        prefetch,
        "products.json",
        {
            "products": [
                _product(options=[{"name": "Size"}, {"name": "Color"}]),
                _product(options=[{"name": "color"}, {"name": "Material"}]),
                _product(options=["size", " COLOR "]),  # tolerate string options
            ]
        },
    )
    stats = compute(prefetch, _empty_caps())
    # First-encountered order, lower-cased, deduped.
    assert stats.variant_axes_observed == VARIANT_AXES_EXPECTED


# ---------------------------------------------------------------------------
# compute() — capability-derived fields
# ---------------------------------------------------------------------------


def test_compute_pulls_navigation_homepage_info_pages_from_capabilities(
    tmp_path: Path,
) -> None:
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    caps = Capabilities.model_validate(
        {
            "site_shell": {"nav_depth": NAV_DEPTH},
            "homepage": {"section_count": HOMEPAGE_SECTION_COUNT},
            "info_pages_present": INFO_PAGES,
        }
    )
    stats = compute(prefetch, caps)
    assert stats.navigation_depth_max == NAV_DEPTH
    assert stats.homepage_section_count == HOMEPAGE_SECTION_COUNT
    assert stats.info_pages_count == len(INFO_PAGES)


def test_compute_feature_count_sums_truthy_bools_and_list_lengths(
    tmp_path: Path,
) -> None:
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    # Hand-counted: 4 truthy bools (announcement, mega_menu, predictive,
    # implicit none from cart) + list lengths 2 (predictive_types) +
    # 3 (info_pages_present) -> 3 bools (announcement, mega_menu,
    # predictive) + 2 + 3 = 8.
    caps = Capabilities.model_validate(
        {
            "site_shell": {
                "has_announcement_bar": True,  # +1
                "has_mega_menu": True,  # +1
                "nav_depth": 99,  # not counted (numeric)
            },
            "cart": {"type": "drawer", "has_promo_input": False},  # +0
            "search": {
                "has_predictive": True,  # +1
                "predictive_types": ["products", "collections"],  # +2
            },
            "info_pages_present": ["about", "contact", "faq"],  # +3
        }
    )
    stats = compute(prefetch, caps)
    assert stats.feature_count == EXPECTED_FEATURE_COUNT


def test_compute_feature_count_zero_for_empty_capabilities(tmp_path: Path) -> None:
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    stats = compute(prefetch, _empty_caps())
    assert stats.feature_count == 0
