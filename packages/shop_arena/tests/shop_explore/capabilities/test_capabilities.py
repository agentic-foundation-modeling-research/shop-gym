"""Unit tests for :mod:`shop_explore.capabilities`.

Covers the requirements from
``docs/impl/shop_explore_implementation.md`` T1.4:

* Round-trip of the closed :class:`Capabilities` schema.
* Unknown-field rejection at every level.
* Deterministic deep-merge with leaf-overwrite + list-union (deduped,
  order-preserving).
* Leaf conflict reporting through :class:`Conflict`.
* Empty / missing parts directories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shop_explore.capabilities import (
    Capabilities,
    CapabilitiesValidationError,
    Conflict,
    merge_fragments,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _spec_example() -> dict[str, object]:
    """The full example from spec §5.5, used as a round-trip fixture."""
    return {
        "version": "0.1",
        "shop": {
            "descriptor": "premium minimalist jewelry store",
            "category": "fashion_accessories",
            "currency": "USD",
            "tone": ["minimal", "luxury"],
        },
        "site_shell": {
            "has_announcement_bar": True,
            "header_style": "horizontal",
            "has_mega_menu": True,
            "nav_depth": 2,
            "footer_groups": 4,
        },
        "homepage": {
            "section_types": [
                "hero_carousel",
                "featured_collection",
                "promo_banner",
                "testimonials",
                "newsletter",
            ],
            "section_count": 5,
            "has_popup_modal": True,
        },
        "collection": {
            "layout": "grid",
            "columns_desktop": 4,
            "filters": ["size", "color", "price"],
            "sort": ["featured", "price_asc", "price_desc", "newest"],
            "pagination": "load_more",
        },
        "product": {
            "gallery_style": "thumbnail_strip",
            "variant_selectors": ["color_swatch", "size_button"],
            "has_quantity_selector": True,
            "description_layout": "tabs",
            "has_reviews": True,
            "has_recommendations": True,
            "has_personalization": False,
        },
        "cart": {
            "type": "drawer",
            "has_promo_input": True,
            "has_upsells": True,
            "has_shipping_estimate": False,
        },
        "search": {
            "trigger": "header_icon",
            "has_predictive": True,
            "predictive_types": ["products", "collections"],
            "results_layout": "grid_with_filters",
        },
        "floating": {
            "has_chat_widget": True,
            "has_age_gate": False,
            "has_cookie_banner": True,
            "has_newsletter_popup": True,
        },
        "info_pages_present": [
            "about",
            "contact",
            "shipping_policy",
            "returns_policy",
            "privacy",
            "tos",
            "faq",
            "gift_cards",
        ],
    }


def test_capabilities_round_trip_spec_example() -> None:
    payload = _spec_example()
    model = Capabilities.model_validate(payload)
    # Round-trip via JSON to make sure the dump matches the spec example.
    assert json.loads(model.model_dump_json()) == payload


def test_capabilities_defaults_are_empty() -> None:
    caps = Capabilities()
    assert caps.version == "0.1"
    assert caps.shop.tone == []
    assert caps.collection.filters == []
    assert caps.cart.type is None
    assert caps.info_pages_present == []


def test_capabilities_rejects_unknown_top_level_field() -> None:
    with pytest.raises(Exception) as exc_info:
        Capabilities.model_validate({"unexpected_top_level": True})
    assert "unexpected_top_level" in str(exc_info.value)


def test_capabilities_rejects_unknown_nested_field() -> None:
    with pytest.raises(Exception) as exc_info:
        Capabilities.model_validate({"cart": {"type": "drawer", "bogus_flag": True}})
    assert "bogus_flag" in str(exc_info.value)


# ---------------------------------------------------------------------------
# merge_fragments
# ---------------------------------------------------------------------------


def _write_fragment(parts_dir: Path, name: str, payload: dict[str, object]) -> None:
    parts_dir.joinpath(name).write_text(json.dumps(payload), encoding="utf-8")


def test_merge_fragments_empty_dir_returns_default(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    caps, conflicts = merge_fragments(parts)
    assert caps == Capabilities()
    assert conflicts == []


def test_merge_fragments_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        merge_fragments(tmp_path / "does_not_exist")


def test_merge_fragments_ignores_non_caps_files(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    parts.joinpath("homepage_sections.md").write_text("# notes", encoding="utf-8")
    _write_fragment(parts, "cart.caps.json", {"cart": {"type": "drawer"}})
    caps, conflicts = merge_fragments(parts)
    assert caps.cart.type == "drawer"
    assert conflicts == []


def test_merge_fragments_combines_disjoint_sections(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    _write_fragment(parts, "cart.caps.json", {"cart": {"type": "drawer"}})
    _write_fragment(
        parts,
        "search.caps.json",
        {"search": {"has_predictive": True, "predictive_types": ["products"]}},
    )
    caps, conflicts = merge_fragments(parts)
    assert caps.cart.type == "drawer"
    assert caps.search.has_predictive is True
    assert caps.search.predictive_types == ["products"]
    assert conflicts == []


def test_merge_fragments_unions_lists_with_dedup_preserving_order(
    tmp_path: Path,
) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    # Sorted filename order: a, b, c — so "a" contributes ["size", "color"] first.
    _write_fragment(
        parts,
        "a_collection.caps.json",
        {"collection": {"filters": ["size", "color"]}},
    )
    _write_fragment(
        parts,
        "b_collection.caps.json",
        {"collection": {"filters": ["color", "price"]}},
    )
    _write_fragment(
        parts,
        "c_collection.caps.json",
        {"collection": {"filters": ["price", "material"]}},
    )
    caps, conflicts = merge_fragments(parts)
    assert caps.collection.filters == ["size", "color", "price", "material"]
    # List union does not produce conflicts.
    assert conflicts == []


def test_merge_fragments_records_leaf_conflicts(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    # "a" wins first → "drawer"; "b" overwrites with "page".
    _write_fragment(parts, "a_cart.caps.json", {"cart": {"type": "drawer"}})
    _write_fragment(parts, "b_cart.caps.json", {"cart": {"type": "page"}})
    caps, conflicts = merge_fragments(parts)
    assert caps.cart.type == "page"  # last writer wins
    assert conflicts == [
        Conflict(
            path="cart.type",
            previous_value="drawer",
            previous_source="a_cart.caps.json",
            new_value="page",
            new_source="b_cart.caps.json",
        )
    ]


def test_merge_fragments_no_conflict_when_leaves_agree(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    _write_fragment(parts, "a_cart.caps.json", {"cart": {"type": "drawer"}})
    _write_fragment(parts, "b_cart.caps.json", {"cart": {"type": "drawer"}})
    _, conflicts = merge_fragments(parts)
    assert conflicts == []


def test_merge_fragments_rejects_unknown_field(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    _write_fragment(parts, "cart.caps.json", {"cart": {"type": "drawer", "bogus": 1}})
    with pytest.raises(CapabilitiesValidationError) as exc_info:
        merge_fragments(parts)
    assert "bogus" in str(exc_info.value)


def test_merge_fragments_rejects_malformed_json(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    parts.joinpath("broken.caps.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CapabilitiesValidationError) as exc_info:
        merge_fragments(parts)
    assert "broken.caps.json" in str(exc_info.value)


def test_merge_fragments_rejects_non_object_fragment(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    parts.joinpath("array.caps.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(CapabilitiesValidationError) as exc_info:
        merge_fragments(parts)
    assert "array.caps.json" in str(exc_info.value)


def test_merge_fragments_is_deterministic_in_filename_order(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    # Different write order; same final result + conflict list.
    _write_fragment(parts, "z_last.caps.json", {"cart": {"type": "page"}})
    _write_fragment(parts, "a_first.caps.json", {"cart": {"type": "drawer"}})
    caps, conflicts = merge_fragments(parts)
    assert caps.cart.type == "page"
    assert len(conflicts) == 1
    assert conflicts[0].previous_source == "a_first.caps.json"
    assert conflicts[0].new_source == "z_last.caps.json"


def test_merge_fragments_full_roundtrip_against_spec_example(tmp_path: Path) -> None:
    """One fragment containing the full spec §5.5 example merges cleanly."""
    parts = tmp_path / "parts"
    parts.mkdir()
    _write_fragment(parts, "all.caps.json", _spec_example())
    caps, conflicts = merge_fragments(parts)
    assert conflicts == []
    assert caps == Capabilities.model_validate(_spec_example())
