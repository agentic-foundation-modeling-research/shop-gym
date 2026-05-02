"""Shared fixtures: a tiny synthetic shop used across all tests.

Having a complete, compact shop dataset in-memory means unit tests don't
depend on a shop-arena checkout being present.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shop_guru.config import Shop


@pytest.fixture(autouse=True)
def mock_litellm_global(monkeypatch):
    """Prevent accidental LLM network calls during tests."""
    from shop_guru.generators import e2e
    if e2e.litellm:
        mock = MagicMock()
        mock.completion.side_effect = Exception("Global test mock - network call prevented")
        monkeypatch.setattr(e2e, "litellm", mock)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tiny_shop_arena_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Materialize a shop-arena-like tree containing one tiny synthetic shop.

    Function-scoped so each test sees a pristine tree — important because
    pipeline tests write into ``<root>/outputs/shop_guru/<slug>/benchmarks/``.

    Also monkeypatches ``shop_guru._paths._REPO_ROOT`` so every caller of
    :func:`shop_guru._paths.repo_root` (``Shop.abs_data_dir``,
    ``per_shop_out_dir``, eval ``benchmarks_root``, …) sees the temporary
    tree as the repo root.

    Creates::

        <tmp>/outputs/shops/tiny.example/
            data/
                store.json
                products.json
                collections.json
                pages.json
                policies.json
                navigation.json
                stats.json
    """
    root = tmp_path / "shop_arena_root"
    shop_dir = root / "outputs" / "shops" / "tiny.example" / "data"
    shop_dir.mkdir(parents=True, exist_ok=True)

    shop_dir.joinpath("store.json").write_text(json.dumps(_TINY_STORE))
    shop_dir.joinpath("products.json").write_text(json.dumps(_TINY_PRODUCTS))
    shop_dir.joinpath("collections.json").write_text(json.dumps(_TINY_COLLECTIONS))
    shop_dir.joinpath("pages.json").write_text(json.dumps(_TINY_PAGES))
    shop_dir.joinpath("policies.json").write_text(json.dumps([]))
    shop_dir.joinpath("navigation.json").write_text(json.dumps({}))
    shop_dir.joinpath("stats.json").write_text(json.dumps(_TINY_STATS))

    from shop_guru import _paths
    monkeypatch.setattr(_paths, "_REPO_ROOT", root)
    return root


@pytest.fixture
def tiny_shop() -> Shop:
    """A Shop config matching the fixture on disk."""
    return Shop(
        slug="tiny",
        name="Tiny Shop",
        real_url="https://tiny.example",
        sandbox_url="https://sandbox.example/?token=abc",
        data_dir="outputs/shops/tiny.example",
        country="US",
        currency="USD",
        language="en",
        image_tag="tiny-main",
    )


@pytest.fixture
def tiny_shop_no_sandbox(tiny_shop: Shop) -> Shop:
    return Shop(**{**tiny_shop.__dict__, "sandbox_url": None})


_TINY_STORE = {
    "shop_id": 1,
    "name": "Tiny Shop",
    "domain": "tiny.example",
    "description": "A minimal shop for testing.",
    "currency_code": "USD",
    "country_code": "US",
    "published_products_count": 3,
    "published_collections_count": 2,
}


_TINY_PRODUCTS = [
    # Winter Wear products carry a Color variant option, so the per-collection
    # filter generator should pick `Color` (a PRIORITY_DIMENSION) for that
    # collection.
    {
        "id": 1,
        "title": "Red Hat",
        "handle": "red-hat",
        "product_type": "Hats",
        "vendor": "WoolCo",
        "status": "active",
        "is_gift_card": False,
        "options": [{"name": "Color", "values": ["Red", "Blue"]}],
        "variants": [{"title": "Default", "available": True}],
    },
    {
        "id": 2,
        "title": "Blue Scarf",
        "handle": "blue-scarf",
        "product_type": "Scarves",
        "vendor": "WoolCo",
        "status": "active",
        "is_gift_card": False,
        "options": [{"name": "Color", "values": ["Blue", "Green"]}],
        "variants": [{"title": "S", "available": True}],
    },
    {
        "id": 3,
        "title": "Green Mittens",
        "handle": "green-mittens",
        "product_type": "Mittens",
        "vendor": "WoolCo",
        "status": "active",
        "is_gift_card": False,
        "options": [{"name": "Color", "values": ["Green"]}],
        "variants": [{"title": "M", "available": True}],
    },
    # Summer Gear products have ProductType + Vendor but no priority variant
    # dimension, so the filter generator should fall back to the universal
    # `ProductType` / `Vendor` dims for that collection.
    {
        "id": 4,
        "title": "Beach Shorts",
        "handle": "shorts",
        "product_type": "Shorts",
        "vendor": "SunCo",
        "status": "active",
        "is_gift_card": False,
        "variants": [{"title": "Default", "available": True}],
    },
    {
        "id": 5,
        "title": "Tan Sandals",
        "handle": "sandals",
        "product_type": "Sandals",
        "vendor": "SunCo",
        "status": "active",
        "is_gift_card": False,
        "variants": [{"title": "Default", "available": True}],
    },
    {
        "id": 6,
        "title": "Inactive Product",
        "handle": "inactive",
        "product_type": "Test",
        "status": "draft",
        "is_gift_card": False,
        "variants": [{"title": "Default", "available": True}],
    },
    {
        "id": 7,
        "title": "Gift Card",
        "handle": "gift-card",
        "product_type": "Gift Card",
        "status": "active",
        "is_gift_card": True,
        "variants": [{"title": "$50", "available": True}],
    },
]


_TINY_COLLECTIONS = [
    {
        "id": 10,
        "title": "Winter Wear",
        "handle": "winter-wear",
        "product_handles": ["red-hat", "blue-scarf", "green-mittens"],
    },
    {
        "id": 11,
        "title": "Summer Gear",
        "handle": "summer-gear",
        "product_handles": [
            "red-hat",
            "blue-scarf",
            "green-mittens",
            "shorts",
            "sandals",
        ],
    },
    {
        "id": 12,
        "title": "All",
        "handle": "all",
        "product_handles": ["red-hat"],
    },
    {
        "id": 13,
        "title": "Promo Eligible Products",
        "handle": "promo-eligible",
        "product_handles": ["red-hat", "blue-scarf", "green-mittens"],
    },
    {
        "id": 14,
        "title": "Sparse",
        "handle": "sparse",
        "product_handles": ["red-hat"],
    },
]


_TINY_PAGES = [
    {
        "handle": "about",
        "title": "About Us",
        "body_html": "<p>About</p>",
        "published_at": "2024-01-01",
    },
    {
        "handle": "shipping-info",
        "title": "Shipping Info",
        "body_html": "<p>Shipping details</p>",
        "published_at": "2024-01-01",
    },
    {
        "handle": "refund-policy",
        "title": "Refund Policy",
        "body_html": "<p>Refunds</p>",
        "published_at": "2024-01-01",
    },
    {
        "handle": "sponsorship-form",
        "title": "Event Sponsorship Form",
        "body_html": "<p>Sponsorship</p>",
        "published_at": "2024-01-01",
    },
]


_TINY_STATS = {
    "total_products": 3,
    "total_collections": 2,
    "currency_code": "USD",
    "product_types": [
        {"product_type": "Hats", "count": 1},
        {"product_type": "Scarves", "count": 1},
        {"product_type": "Mittens", "count": 1},
    ],
    "option_patterns": [
        {"name": "Title", "count": 3, "sample_values": ["Default Title"]},
        {"name": "Color", "count": 2, "sample_values": ["Red", "Blue"]},
        {"name": "Size", "count": 1, "sample_values": ["S", "M", "L"]},
    ],
}
