"""Unit tests for the individual generators."""
from __future__ import annotations

import pytest

from shop_guru.config import Shop
from shop_guru.generators import (
    collection_browse,
    collection_filter,
    exact_search,
    find_policy,
    substitute_search,
)
from shop_guru.io import load_shop_data


@pytest.fixture
def tiny_data(tiny_shop_arena_root, tiny_shop: Shop) -> dict:
    return load_shop_data(tiny_shop)


def test_exact_search_excludes_gift_cards_and_inactive(tiny_shop: Shop, tiny_data: dict) -> None:
    tasks = exact_search.generate(tiny_shop, tiny_data, seed=42, count=10)
    titles = [t["intent"].split("Find the product named ", 1)[1].split(" and ")[0] for t in tasks]
    assert "Gift Card" not in titles
    assert "Inactive Product" not in titles
    # Five eligible products in the fixture (red-hat, blue-scarf, green-mittens,
    # shorts, sandals); inactive + gift card excluded.
    assert 1 <= len(tasks) <= 5


def test_exact_search_task_shape(tiny_shop: Shop, tiny_data: dict) -> None:
    tasks = exact_search.generate(tiny_shop, tiny_data, seed=0, count=2)
    assert tasks
    t = tasks[0]
    assert t["id"].startswith("tiny-exact-")
    assert t["type"] == "shopping"
    assert "intent" in t
    assert t["success_criteria"]["type"] == "product_search"
    assert t["success_criteria"]["url_contains"].startswith("/products/")
    assert "url" not in t  # URL is attached by the emitter, not the generator


def test_substitute_search_pairs_with_exact(tiny_shop: Shop, tiny_data: dict) -> None:
    exact = exact_search.generate(tiny_shop, tiny_data, seed=0, count=2)
    subs = substitute_search.generate(tiny_shop, tiny_data, seed=0, count=2)

    assert len(subs) == len(exact)
    for e, s in zip(exact, subs, strict=False):
        e_title = e["intent"].split("Find the product named ", 1)[1].split(" and ")[0]
        assert e_title in s["intent"]
        assert s["id"].startswith("tiny-substitute-")


def test_collection_browse_skips_generic(tiny_shop: Shop, tiny_data: dict) -> None:
    tasks = collection_browse.generate(tiny_shop, tiny_data, seed=0, count=5)
    titles = [t["intent"].split('"')[1] for t in tasks]
    assert "All" not in titles
    assert "Promo Eligible Products" not in titles
    assert "Sparse" not in titles  # Only 1 product
    assert set(titles).issubset({"Winter Wear", "Summer Gear"})


def test_collection_filter_uses_priority_dimensions(tiny_shop: Shop, tiny_data: dict) -> None:
    tasks = collection_filter.generate(tiny_shop, tiny_data, seed=0, count=3)
    for task in tasks:
        intent = task["intent"]
        assert " filter" in intent
        # Priority dimensions come first; "Title" is excluded.
        assert "Title filter" not in intent


def test_collection_filter_picks_per_collection_priority_dim(tiny_shop: Shop) -> None:
    """When a collection's own products carry a priority variant dim, the
    generator must pick that dim rather than fall back to a universal one.
    Guards against the previous behavior of choosing dims by shop-wide
    stats independent of the chosen collection.
    """
    products = [
        {
            "id": i,
            "title": f"Hat {i}",
            "handle": f"hat-{i}",
            "product_type": "Hats",
            "vendor": "WoolCo",
            "options": [{"name": "Color", "values": ["Red", "Blue"]}],
            "variants": [{"title": "Default", "available": True}],
        }
        for i in range(6)
    ]
    collections = [
        {
            "id": 1,
            "title": "Hats",
            "handle": "hats",
            "product_handles": [p["handle"] for p in products],
        }
    ]
    data = {
        "products": products,
        "collections": collections,
        "stats": {"option_patterns": []},
    }
    tasks = collection_filter.generate(tiny_shop, data, seed=0, count=1)
    assert len(tasks) == 1
    intent = tasks[0]["intent"]
    assert "Color filter" in intent
    # Lexicographically-first value across all products in the collection.
    assert "e.g. Blue" in intent


def test_collection_filter_falls_back_to_universal_dim(
    tiny_shop: Shop, tiny_data: dict
) -> None:
    """When a collection's products carry no priority variant dim, the
    generator must fall back to the universal `ProductType`/`Vendor` dims
    rather than emit a task with a dim that does not exist in the
    collection..
    """
    # Build a one-collection fixture where products only have ProductType + Vendor.
    products = [p for p in tiny_data["products"] if p["handle"] in {"shorts", "sandals"}]
    extra = [
        {**products[0], "id": 100, "handle": f"x-{i}"}
        for i in range(3)
    ]
    products = products + extra
    collections = [
        {
            "id": 999,
            "title": "Universal Only",
            "handle": "universal-only",
            "product_handles": [p["handle"] for p in products],
        }
    ]
    isolated_data = {**tiny_data, "products": products, "collections": collections}

    tasks = collection_filter.generate(tiny_shop, isolated_data, seed=0, count=1)
    assert tasks, "Should still emit a task using universal-fallback dim"
    intent = tasks[0]["intent"]
    # The display alias is `Type` for ProductType and `Brand` for Vendor.
    assert "Type filter" in intent or "Brand filter" in intent
    # Whatever value is chosen must be realizable in the collection.
    realizable_values = {"Shorts", "Sandals", "SunCo"}
    assert any(f"e.g. {v}" in intent for v in realizable_values), intent


def test_collection_filter_skips_collections_with_no_realizable_dim(
    tiny_shop: Shop,
) -> None:
    """A collection whose products carry no vendor/product_type and no
    variant options must be skipped entirely rather than producing a task
    with a fabricated dim/value.
    """
    products = [
        {
            "id": i,
            "title": f"Bare Product {i}",
            "handle": f"bare-{i}",
            "status": "active",
            "is_gift_card": False,
            "variants": [{"title": "Default", "available": True}],
        }
        for i in range(6)
    ]
    collections = [
        {
            "id": 1,
            "title": "Bare Collection",
            "handle": "bare",
            "product_handles": [p["handle"] for p in products],
        }
    ]
    data = {
        "products": products,
        "collections": collections,
        "stats": {"option_patterns": []},
    }
    tasks = collection_filter.generate(tiny_shop, data, seed=0, count=3)
    assert tasks == []


def test_collection_filter_is_deterministic(tiny_shop: Shop, tiny_data: dict) -> None:
    """Same seed must produce identical (collection, dim, value) selections."""
    a = collection_filter.generate(tiny_shop, tiny_data, seed=11, count=3)
    b = collection_filter.generate(tiny_shop, tiny_data, seed=11, count=3)
    assert a == b


def test_find_policy_shipping_prefers_matching_page(
    tiny_shop: Shop, tiny_data: dict
) -> None:
    tasks = find_policy.generate_shipping(tiny_shop, tiny_data)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["type"] == "navigation"
    assert task["success_criteria"]["url_contains"] == "/pages/shipping-info"
    # Sponsorship page must NOT match (word-boundary check).
    assert "/pages/sponsorship-form" not in (task["success_criteria"]["url_contains"],)
    assert "/pages/sponsorship-form" not in task.get("url_contains_alt", [])


def test_find_policy_returns_uses_fallback_when_missing(tiny_shop: Shop) -> None:
    empty_data: dict = {"pages": []}
    tasks = find_policy.generate_returns(tiny_shop, empty_data)
    assert len(tasks) == 1
    assert tasks[0]["success_criteria"]["url_contains"] == "/policies/refund-policy"


def test_generator_output_is_deterministic(tiny_shop: Shop, tiny_data: dict) -> None:
    """Given the same seed, every run must produce identical tasks."""
    a = exact_search.generate(tiny_shop, tiny_data, seed=7, count=3)
    b = exact_search.generate(tiny_shop, tiny_data, seed=7, count=3)
    assert a == b

    a = collection_browse.generate(tiny_shop, tiny_data, seed=7, count=3)
    b = collection_browse.generate(tiny_shop, tiny_data, seed=7, count=3)
    assert a == b
