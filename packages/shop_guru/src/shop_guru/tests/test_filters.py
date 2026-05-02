"""Unit tests for shop_guru.filters."""
from __future__ import annotations

import pytest

from shop_guru.filters import (
    collections_with_min_products,
    is_generic_collection,
    pages_matching,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("All", True),
        ("Sale", True),
        ("Gift Card", True),
        ("Gift Cards", True),
        ("Featured", True),
        ("Best Sellers", True),
        ("Promo Eligible Products", True),
        ("Wholesale only", True),
        ("Dog Dentals", False),
        ("Winter Wear", False),
        ("", False),
    ],
)
def test_is_generic_collection(title: str, expected: bool) -> None:
    assert is_generic_collection(title) is expected


def test_collections_with_min_products_filters_generic_and_sparse() -> None:
    collections = [
        {"title": "Winter Wear", "handle": "w", "product_handles": ["a", "b", "c"]},
        {"title": "Sale", "handle": "s", "product_handles": ["a", "b", "c"]},
        {"title": "Sparse", "handle": "sp", "product_handles": ["a"]},
        {"title": "Promo Eligible", "handle": "pe", "product_handles": ["a", "b", "c"]},
    ]
    result = collections_with_min_products(collections, min_products=3)
    assert [c["title"] for c in result] == ["Winter Wear"]


def test_pages_matching_uses_word_boundaries() -> None:
    pages = [
        {"title": "Shipping Info", "handle": "shipping-info"},
        {"title": "Event Sponsorship Form", "handle": "sponsorship-form"},
        {"title": "About Us", "handle": "about"},
    ]
    matched = pages_matching(pages, ["ship"])
    assert [p["handle"] for p in matched] == ["shipping-info"]


def test_pages_matching_matches_handle_words() -> None:
    pages = [
        {"title": "Frequently Asked Questions", "handle": "faq-return-policy"},
    ]
    matched = pages_matching(pages, ["return"])
    assert len(matched) == 1


def test_pages_matching_is_case_insensitive() -> None:
    pages = [{"title": "SHIPPING", "handle": "SHIPPING"}]
    matched = pages_matching(pages, ["ship"])
    assert len(matched) == 1
