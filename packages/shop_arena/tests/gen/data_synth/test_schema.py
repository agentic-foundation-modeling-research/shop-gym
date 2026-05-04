"""Unit tests for :mod:`shop_arena.gen.data_synth.schema`.

Covers the T3.2 requirements from
``docs/impl/shop_gen_implementation.md``:

* Round-trip a ``shop_backend`` fixture dataset through the pydantic
  models without loss (every byte-relevant field survives
  validate → ``model_dump(mode="json")``).
* Closed schemas reject unknown top-level fields per spec §8.1.1.
* Recursive :class:`~shop_arena.gen.data_synth.schema.NavigationItem`
  validates nested children.
* :class:`~shop_arena.gen.data_synth.schema.Store.dataset_version` is
  optional and may be omitted on input.
* :class:`~shop_arena.gen.data_synth.schema.NavigationItemType` is closed:
  unknown values raise ``ValidationError``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shop_arena.gen.data_synth.schema import (
    Collection,
    Navigation,
    NavigationItem,
    Page,
    Policy,
    Product,
    Store,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sandbox_shop_v0"


def _load(name: str) -> Any:
    """Read ``fixtures/sandbox_shop_v0/<name>`` as parsed JSON."""
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Round-trip tests — every required v0.1 dataset file
# --------------------------------------------------------------------------- #


def test_store_round_trip_without_loss() -> None:
    raw = cast("dict[str, Any]", _load("store.json"))

    model = Store.model_validate(raw)

    assert model.model_dump(mode="json") == raw


def test_products_round_trip_without_loss() -> None:
    raw = cast("list[dict[str, Any]]", _load("products.json"))

    products = [Product.model_validate(p) for p in raw]

    assert [p.model_dump(mode="json") for p in products] == raw


def test_collections_round_trip_without_loss() -> None:
    raw = cast("list[dict[str, Any]]", _load("collections.json"))

    collections = [Collection.model_validate(c) for c in raw]

    assert [c.model_dump(mode="json") for c in collections] == raw


def test_pages_round_trip_without_loss() -> None:
    raw = cast("list[dict[str, Any]]", _load("pages.json"))

    pages = [Page.model_validate(p) for p in raw]

    assert [p.model_dump(mode="json") for p in pages] == raw


def test_policies_round_trip_without_loss() -> None:
    raw = cast("list[dict[str, Any]]", _load("policies.json"))

    policies = [Policy.model_validate(p) for p in raw]

    assert [p.model_dump(mode="json") for p in policies] == raw


def test_navigation_round_trip_without_loss() -> None:
    raw = cast("dict[str, Any]", _load("navigation.json"))

    nav = Navigation.model_validate(raw)

    assert nav.model_dump(mode="json") == raw


# --------------------------------------------------------------------------- #
# Closed-schema enforcement
# --------------------------------------------------------------------------- #


def test_store_rejects_extra_top_level_field() -> None:
    raw = cast("dict[str, Any]", _load("store.json"))
    raw_with_extra = {**raw, "example_domain": "example.com"}

    with pytest.raises(ValidationError):
        Store.model_validate(raw_with_extra)


def test_product_rejects_extra_field() -> None:
    raw = cast("list[dict[str, Any]]", _load("products.json"))
    tainted = {**raw[0], "status": "active"}

    with pytest.raises(ValidationError):
        Product.model_validate(tainted)


def test_product_variant_rejects_dropped_currency_code() -> None:
    """Spec §8.1.1 lists ``currency_code`` as dropped from the variant."""
    raw = cast("list[dict[str, Any]]", _load("products.json"))
    variants = cast("list[dict[str, Any]]", raw[0]["variants"])
    tainted = {**variants[0], "currency_code": "USD"}

    raw[0]["variants"] = [tainted]

    with pytest.raises(ValidationError):
        Product.model_validate(raw[0])


def test_page_rejects_dropped_published_at() -> None:
    """Spec §8.1.1 explicitly drops ``Page.published_at``."""
    raw = cast("list[dict[str, Any]]", _load("pages.json"))
    tainted = {**raw[0], "published_at": "2026-04-14T07:16:31-04:00"}

    with pytest.raises(ValidationError):
        Page.model_validate(tainted)


# --------------------------------------------------------------------------- #
# Optional + recursive cases
# --------------------------------------------------------------------------- #


def test_store_dataset_version_is_optional() -> None:
    raw = cast("dict[str, Any]", _load("store.json"))
    raw_no_version = {k: v for k, v in raw.items() if k != "dataset_version"}

    model = Store.model_validate(raw_no_version)

    assert model.dataset_version is None


def test_navigation_item_recurses() -> None:
    payload = {
        "main-menu": [
            {
                "title": "Shop",
                "url": "/collections/all",
                "type": "COLLECTION",
                "children": [
                    {
                        "title": "Featured",
                        "url": "/collections/featured",
                        "type": "COLLECTION",
                        "children": [
                            {
                                "title": "Outbound",
                                "url": "https://example.com/",
                                "type": "HTTP",
                                "children": [],
                            },
                        ],
                    },
                ],
            },
        ],
    }

    nav = Navigation.model_validate(payload)

    main_menu = nav.root["main-menu"]
    assert main_menu[0].children[0].children[0].type == "HTTP"
    assert nav.model_dump(mode="json") == payload


def test_navigation_item_rejects_unknown_type() -> None:
    payload = {
        "title": "Bad",
        "url": "/x",
        "type": "VIDEO",  # not in the closed enum
        "children": [],
    }

    with pytest.raises(ValidationError):
        NavigationItem.model_validate(payload)
