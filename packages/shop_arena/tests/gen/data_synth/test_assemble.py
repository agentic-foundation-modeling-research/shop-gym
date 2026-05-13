"""Unit tests for :mod:`shop_arena.gen.data_synth.assemble`.

Covers the T3.11 requirements from
``docs/impl/shop_gen_implementation.md``:

* Happy path: assemble the six ``data/*.json`` files from a fully
  populated stage cache + ``identity.json``; deterministic numeric
  ids; pydantic-validated outputs.
* Pure-helper coverage of the (currently disabled at the step level)
  brand-leak scrub: :func:`scan_for_brand_leaks` and
  :func:`_step_for_field_path`. The assemble-time invocation is
  disabled in v0.1.x — see spec §5.6 "Current status" — so the step
  itself no longer raises :class:`BrandLeakError`.
* Cross-collection handle conflict resolution at assembly time
  (spec §5.3).
* Step contract: id, phase, outputs, depends_on, version; pipeline
  registration surfaces ``assemble_data`` in the data-synth phase
  listing.
* Integration: drive the whole step run against a populated stage
  cache and assert the published files round-trip through the closed
  pydantic mirrors (SC1 + SC4).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from shop_arena.gen.brands.allowlist import load_allowlist
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.data_synth import (
    AssembleDataStep,
    Collection,
    CollectionDraft,
    Navigation,
    Page,
    Policy,
    Product,
    ProductDetail,
    ProductSkeleton,
    StageSynthError,
    Store,
    assemble_records,
    scan_for_brand_leaks,
)
from shop_arena.gen.data_synth.assemble import (
    _ID_HEX_CHARS,
    _step_for_field_path,
)
from shop_arena.gen.pipeline import list_steps
from shop_arena.gen.steps.base import StepContext
from shop_arena.gen.steps.runner import Registry, run_pipeline

# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


def _identity_payload() -> dict[str, Any]:
    return {
        "name": "AisleArena",
        "descriptor": "modern outdoor gear store",
        "tone": ["confident"],
        "currency": "USD",
        "country": "US",
    }


def _store_cache() -> dict[str, Any]:
    return {
        "shop_id": 0,
        "name": "AisleArena",
        "domain": "aislearena.example",
        "description": "plain descriptive store description.",
        "currency_code": "USD",
        "country_code": "US",
        "payment_settings": {
            "accepted_card_brands": ["VISA", "MASTER"],
        },
        "brand": {
            "logo_url": None,
            "colors": {
                "primary": "#1f6f43",
                "secondary": "#f3e9d2",
            },
        },
    }


def _collection_draft(
    handle: str,
    *,
    title: str | None = None,
    target_product_count: int = 2,
) -> CollectionDraft:
    return CollectionDraft(
        title=title if title is not None else handle.replace("-", " "),
        handle=handle,
        description=f"plain description of {handle}.",
        sort_order="manual",
        target_product_count=target_product_count,
    )


def _skeleton(handle: str, *, collection_handle: str) -> ProductSkeleton:
    return ProductSkeleton(
        title=handle.replace("-", " "),
        handle=handle,
        price="29.99",
        collection_handle=collection_handle,
    )


def _detail(
    handle: str,
    *,
    vendor: str = "AisleArena",
    description_html: str = "<p>warm and quiet.</p>",
    product_type: str = "outerwear",
    tags: tuple[str, ...] = ("warm", "winter"),
) -> ProductDetail:
    return ProductDetail.model_validate(
        {
            "handle": handle,
            "description_html": description_html,
            "vendor": vendor,
            "product_type": product_type,
            "tags": list(tags),
            "options": [
                {"name": "Size", "position": 1, "values": ["S", "M"]},
            ],
            "variants": [
                {
                    "title": "Small",
                    "sku": f"{handle}-s",
                    "price": "29.99",
                    "compare_at_price": None,
                    "available": True,
                    "option1": "S",
                    "option2": None,
                    "option3": None,
                    "position": 1,
                    "requires_shipping": True,
                },
                {
                    "title": "Medium",
                    "sku": f"{handle}-m",
                    "price": "29.99",
                    "compare_at_price": None,
                    "available": True,
                    "option1": "M",
                    "option2": None,
                    "option3": None,
                    "position": 2,
                    "requires_shipping": True,
                },
            ],
        },
    )


_OUTERWEAR = _collection_draft("outerwear")
_KITCHEN = _collection_draft("kitchen-tools")
_COLLECTIONS: list[CollectionDraft] = [_OUTERWEAR, _KITCHEN]
_SKELETONS: list[ProductSkeleton] = [
    _skeleton("warm-winter-coat", collection_handle="outerwear"),
    _skeleton("waterproof-rain-jacket", collection_handle="outerwear"),
    _skeleton("ceramic-coffee-mug", collection_handle="kitchen-tools"),
    _skeleton("stainless-mixing-bowl", collection_handle="kitchen-tools"),
]
_DETAILS: list[ProductDetail] = [
    _detail("warm-winter-coat"),
    _detail("waterproof-rain-jacket"),
    _detail("ceramic-coffee-mug", product_type="mug"),
    _detail("stainless-mixing-bowl", product_type="bowl"),
]
_DETAILS_BY_HANDLE: dict[str, ProductDetail] = {d.handle: d for d in _DETAILS}
_ALT_TEXT: dict[str, list[str]] = {
    "warm-winter-coat": ["front view of the warm winter coat", "close up of the warm winter coat"],
    "waterproof-rain-jacket": [
        "front view of the waterproof rain jacket",
        "close up of the waterproof rain jacket",
    ],
    "ceramic-coffee-mug": [
        "front view of the ceramic coffee mug",
        "close up of the ceramic coffee mug",
    ],
    "stainless-mixing-bowl": [
        "front view of the stainless mixing bowl",
        "close up of the stainless mixing bowl",
    ],
}
_PAGES: list[dict[str, Any]] = [
    {"handle": "about", "title": "About us", "body_html": "<p>plain about page.</p>"},
    {"handle": "contact", "title": "Contact", "body_html": "<p>plain contact page.</p>"},
]
_POLICIES: list[dict[str, Any]] = [
    {"handle": "privacy-policy", "title": "Privacy", "body_html": "<p>plain privacy.</p>"},
    {"handle": "shipping-policy", "title": "Shipping", "body_html": "<p>plain shipping.</p>"},
    {"handle": "terms-of-service", "title": "Terms", "body_html": "<p>plain terms.</p>"},
    {"handle": "refund-policy", "title": "Refunds", "body_html": "<p>plain refunds.</p>"},
]
_NAVIGATION: dict[str, Any] = {
    "main-menu": [
        {
            "title": "Outerwear",
            "url": "/collections/outerwear",
            "type": "COLLECTION",
            "children": [],
        },
        {
            "title": "Kitchen tools",
            "url": "/collections/kitchen-tools",
            "type": "COLLECTION",
            "children": [],
        },
    ],
    "footer": [
        {"title": "About", "url": "/pages/about", "type": "PAGE", "children": []},
    ],
}


def _images_manifest() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for skeleton in _SKELETONS:
        for index in range(2):
            entries.append(
                {
                    "handle": skeleton.handle,
                    "index": index,
                    "file": f"data/images/{skeleton.handle}-{index}.svg",
                    "width": 800,
                    "height": 800,
                },
            )
    return {
        "backend": "placeholder",
        "extension": ".svg",
        "images_per_product": 2,
        "total_images": len(entries),
        "entries": entries,
    }


def _materialise_workspace(
    out_dir: Path,
    *,
    skeletons: list[ProductSkeleton] | None = None,
    details_by_handle: dict[str, ProductDetail] | None = None,
    pages: list[dict[str, Any]] | None = None,
    policies: list[dict[str, Any]] | None = None,
) -> None:
    """Populate ``<out_dir>/`` with every cached file ``assemble_data`` reads."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / ".shop_gen" / "stage_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (out_dir / "identity.json").write_text(
        json.dumps(_identity_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (cache / "store.json").write_text(
        json.dumps(_store_cache(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (cache / "collections.json").write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in _COLLECTIONS],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    actual_skeletons = skeletons if skeletons is not None else _SKELETONS
    (cache / "skeletons.json").write_text(
        json.dumps(
            [s.model_dump(mode="json") for s in actual_skeletons],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (cache / "pages.json").write_text(
        json.dumps(pages if pages is not None else _PAGES, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (cache / "policies.json").write_text(
        json.dumps(policies if policies is not None else _POLICIES, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (cache / "alt_text.json").write_text(
        json.dumps(_ALT_TEXT, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (cache / "navigation.json").write_text(
        json.dumps(_NAVIGATION, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (cache / "images_manifest.json").write_text(
        json.dumps(_images_manifest(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    actual_details_by_handle = (
        details_by_handle if details_by_handle is not None else _DETAILS_BY_HANDLE
    )
    details_dir = cache / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, Any]] = []
    for collection in _COLLECTIONS:
        bucket = [
            actual_details_by_handle[s.handle]
            for s in actual_skeletons
            if s.collection_handle == collection.handle and s.handle in actual_details_by_handle
        ]
        file_name = f"{collection.handle}.json"
        (details_dir / file_name).write_text(
            json.dumps([d.model_dump(mode="json") for d in bucket], indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        manifest_entries.append(
            {
                "handle": collection.handle,
                "file": file_name,
                "details_count": len(bucket),
                "dropped_count": 0,
            },
        )
    (details_dir / "_manifest.json").write_text(
        json.dumps(
            {
                "collections": manifest_entries,
                "total_products": sum(e["details_count"] for e in manifest_entries),
                "total_dropped": 0,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


class _NoopStep:
    """Test stub satisfying the :class:`shop_arena.gen.steps.base.Step` protocol.

    Used by the runner integration test to register placeholder upstream
    steps so :func:`run_pipeline` can resolve ``assemble_data``'s
    dependency graph without booting the real Phase 2 sub-DAG.
    """

    def __init__(self, *, step_id: str, phase: str = "data_synth") -> None:
        self.id: str = step_id
        self.phase: str = phase
        self.inputs: list[Any] = []
        self.outputs: list[Path] = []
        self.depends_on: list[str] = []
        self.version: int = 1

    def run(self, ctx: StepContext) -> None:
        del ctx  # No-op.


# --------------------------------------------------------------------------- #
# assemble_records (pure function)
# --------------------------------------------------------------------------- #


def test_assemble_records_happy_path_round_trips_through_schema() -> None:
    data = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    assert isinstance(data.store, Store)
    assert all(isinstance(p, Product) for p in data.products)
    assert all(isinstance(c, Collection) for c in data.collections)
    assert all(isinstance(p, Page) for p in data.pages)
    assert all(isinstance(p, Policy) for p in data.policies)
    assert isinstance(data.navigation, Navigation)


def test_assemble_records_assigns_deterministic_ids() -> None:
    """SC7: re-running with identical inputs reproduces the same numeric ids."""
    data1 = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    data2 = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    assert [p.id for p in data1.products] == [p.id for p in data2.products]
    assert [c.id for c in data1.collections] == [c.id for c in data2.collections]
    assert data1.store.shop_id == data2.store.shop_id


def test_assemble_records_id_derived_from_sha256_prefix() -> None:
    """Spec §5.3: numeric ids are sha256-prefix of the handle."""
    data = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    expected = int(
        hashlib.sha256(b"product\x00warm-winter-coat").hexdigest()[:_ID_HEX_CHARS],
        16,
    )
    matching = next(p for p in data.products if p.handle == "warm-winter-coat")
    assert matching.id == expected


def test_assemble_records_collections_carry_member_handles() -> None:
    data = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    by_handle = {c.handle: c for c in data.collections}
    assert by_handle["outerwear"].product_handles == [
        "warm-winter-coat",
        "waterproof-rain-jacket",
    ]
    assert by_handle["kitchen-tools"].product_handles == [
        "ceramic-coffee-mug",
        "stainless-mixing-bowl",
    ]


def test_assemble_records_attaches_alt_text_to_images() -> None:
    data = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    coat = next(p for p in data.products if p.handle == "warm-winter-coat")
    assert [img.alt for img in coat.images] == _ALT_TEXT["warm-winter-coat"]
    assert [img.position for img in coat.images] == [1, 2]
    assert all(img.src == f"warm-winter-coat-{i}.svg" for i, img in enumerate(coat.images))


def test_assemble_records_resolves_cross_collection_handle_conflict() -> None:
    """Spec §5.3: cross-collection conflicts get a positional suffix."""
    skeletons = [
        _skeleton("shared-handle", collection_handle="outerwear"),
        _skeleton("shared-handle", collection_handle="kitchen-tools"),
    ]
    details = {
        "shared-handle": _detail("shared-handle"),
    }
    alt_text = {"shared-handle": ["front view of shared handle", "close up of shared handle"]}
    images = {
        "backend": "placeholder",
        "extension": ".svg",
        "images_per_product": 2,
        "total_images": 4,
        "entries": [
            {
                "handle": "shared-handle",
                "index": idx,
                "file": f"data/images/shared-handle-{idx}.svg",
                "width": 800,
                "height": 800,
            }
            for idx in range(2)
        ],
    }
    data = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=skeletons,
        details_by_handle=details,
        alt_text_by_handle=alt_text,
        image_manifest=images,
        navigation_payload=dict(_NAVIGATION),
    )
    handles = sorted(p.handle for p in data.products)
    # Second skeleton picked up its position-2 suffix.
    assert handles == ["shared-handle", "shared-handle-2"]


def test_assemble_records_rejects_skeleton_without_detail() -> None:
    skeletons = list(_SKELETONS)
    details = {h: d for h, d in _DETAILS_BY_HANDLE.items() if h != "warm-winter-coat"}
    with pytest.raises(StageSynthError, match="no matching detail"):
        assemble_records(
            identity=_identity_payload(),
            store_payload=_store_cache(),
            collection_drafts=list(_COLLECTIONS),
            pages_payload=list(_PAGES),
            policies_payload=list(_POLICIES),
            skeletons=skeletons,
            details_by_handle=details,
            alt_text_by_handle=dict(_ALT_TEXT),
            image_manifest=_images_manifest(),
            navigation_payload=dict(_NAVIGATION),
        )


# --------------------------------------------------------------------------- #
# scan_for_brand_leaks
# --------------------------------------------------------------------------- #


def test_scan_for_brand_leaks_clean_dataset_returns_none() -> None:
    data = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=list(_PAGES),
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    assert scan_for_brand_leaks(data) is None


def test_scan_for_brand_leaks_finds_leak_in_page_body() -> None:
    pages = [
        {"handle": "about", "title": "About", "body_html": "<p>RealBrand sells widgets.</p>"},
    ]
    data = assemble_records(
        identity=_identity_payload(),
        store_payload=_store_cache(),
        collection_drafts=list(_COLLECTIONS),
        pages_payload=pages,
        policies_payload=list(_POLICIES),
        skeletons=list(_SKELETONS),
        details_by_handle=dict(_DETAILS_BY_HANDLE),
        alt_text_by_handle=dict(_ALT_TEXT),
        image_manifest=_images_manifest(),
        navigation_payload=dict(_NAVIGATION),
    )
    leak = scan_for_brand_leaks(data, allowlist=load_allowlist())
    assert leak is not None
    field_path, hit = leak
    assert hit.token == "RealBrand"
    assert field_path.startswith("pages[")
    assert field_path.endswith(".body_html")


# --------------------------------------------------------------------------- #
# _step_for_field_path
# --------------------------------------------------------------------------- #


def test_step_for_field_path_routes_known_prefixes() -> None:
    assert _step_for_field_path("store.description") == "synth_store"
    assert _step_for_field_path("collections[2].title") == "synth_collections"
    assert _step_for_field_path("pages[0].body_html") == "synth_pages"
    assert _step_for_field_path("policies[3].body_html") == "synth_policies"
    assert _step_for_field_path("navigation.main-menu") == "synth_navigation"
    assert _step_for_field_path("products[12].description_html") == "synth_product_details"


def test_step_for_field_path_unknown_prefix_falls_back_to_details() -> None:
    assert _step_for_field_path("mystery.field") == "synth_product_details"


# --------------------------------------------------------------------------- #
# AssembleDataStep — step contract
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = AssembleDataStep()
    assert step.id == "assemble_data"
    assert step.phase == "data_synth"
    assert step.version == 1
    expected_outputs = {
        Path("data") / "store.json",
        Path("data") / "products.json",
        Path("data") / "collections.json",
        Path("data") / "pages.json",
        Path("data") / "policies.json",
        Path("data") / "navigation.json",
    }
    assert set(step.outputs) == expected_outputs
    assert set(step.depends_on) == {
        "synth_identity",
        "synth_store",
        "synth_collections",
        "synth_pages",
        "synth_policies",
        "synth_product_skeletons",
        "synth_product_details",
        "synth_alt_text",
        "gen_images",
        "synth_navigation",
    }


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.11 wires ``assemble_data`` into the Phase 2 phase listing."""
    assert "assemble_data" in list_steps()["data_synth"]


# --------------------------------------------------------------------------- #
# AssembleDataStep.run — happy path / integration
# --------------------------------------------------------------------------- #


def test_step_run_writes_six_data_files(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    AssembleDataStep().run(ctx)

    data_dir = out_dir / "data"
    for name in (
        "store.json",
        "products.json",
        "collections.json",
        "pages.json",
        "policies.json",
        "navigation.json",
    ):
        assert (data_dir / name).exists(), name


def test_step_run_outputs_round_trip_through_schema(tmp_path: Path) -> None:
    """SC1: ``data/*.json`` is accepted by the closed pydantic mirrors."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    AssembleDataStep().run(ctx)

    Store.model_validate_json((out_dir / "data" / "store.json").read_text(encoding="utf-8"))
    products_raw = json.loads((out_dir / "data" / "products.json").read_text(encoding="utf-8"))
    [Product.model_validate(p) for p in products_raw]
    collections_raw = json.loads(
        (out_dir / "data" / "collections.json").read_text(encoding="utf-8"),
    )
    [Collection.model_validate(c) for c in collections_raw]
    pages_raw = json.loads((out_dir / "data" / "pages.json").read_text(encoding="utf-8"))
    [Page.model_validate(p) for p in pages_raw]
    policies_raw = json.loads((out_dir / "data" / "policies.json").read_text(encoding="utf-8"))
    [Policy.model_validate(p) for p in policies_raw]
    nav_raw = json.loads((out_dir / "data" / "navigation.json").read_text(encoding="utf-8"))
    Navigation.model_validate(nav_raw)


def test_step_run_omits_null_dataset_version(tmp_path: Path) -> None:
    """``Store.dataset_version=None`` must not appear as ``null`` on disk.

    The ``shop_backend`` loader treats ``dataset_version`` as
    ``string | undefined`` and rejects ``null`` (see
    ``packages/shop_backend/src/data/loader.ts``). The Phase-2 pipeline
    leaves the field unset in v0.1 datasets, so the on-disk JSON must
    omit the key rather than serialise pydantic's default ``None`` as
    JSON ``null``.
    """
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    AssembleDataStep().run(ctx)

    raw: dict[str, Any] = json.loads(
        (out_dir / "data" / "store.json").read_text(encoding="utf-8"),
    )
    assert "dataset_version" not in raw, (
        f"expected dataset_version to be omitted when unset, got {raw.get('dataset_version')!r}"
    )
    # Round-trip is still valid: the schema treats the field as optional.
    assert Store.model_validate(raw).dataset_version is None

def test_step_run_is_byte_deterministic(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    AssembleDataStep().run(ctx)
    first = (out_dir / "data" / "products.json").read_bytes()
    AssembleDataStep().run(ctx)
    second = (out_dir / "data" / "products.json").read_bytes()
    assert first == second


def test_step_run_missing_identity_raises(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    (out_dir / "identity.json").unlink()
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match=r"identity\.json"):
        AssembleDataStep().run(ctx)


def test_step_run_missing_images_manifest_raises(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    (out_dir / ".shop_gen" / "stage_cache" / "images_manifest.json").unlink()
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match="images manifest"):
        AssembleDataStep().run(ctx)



# --------------------------------------------------------------------------- #
# Integration: drive the runner end-to-end against a stale assemble step.
# --------------------------------------------------------------------------- #


def test_step_runs_through_pipeline_runner(tmp_path: Path) -> None:
    """Drive ``assemble_data`` via :func:`run_pipeline` directly.

    Stub the ten upstream steps with no-op records so the runner can
    resolve the DAG; the cached payloads on disk are pre-materialised
    by ``_materialise_workspace`` so ``assemble_data`` itself runs
    against a realistic stage cache.
    """
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)

    registry = Registry()
    for upstream_id in (
        "synth_identity",
        "synth_store",
        "synth_collections",
        "synth_pages",
        "synth_policies",
        "synth_product_skeletons",
        "synth_product_details",
        "synth_alt_text",
        "gen_images",
        "synth_navigation",
    ):
        registry.register(_NoopStep(step_id=upstream_id))
    registry.register(AssembleDataStep())
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    result = run_pipeline(registry.all(), ctx)
    assert "assemble_data" in result.ran
    assert (out_dir / "data" / "products.json").exists()
