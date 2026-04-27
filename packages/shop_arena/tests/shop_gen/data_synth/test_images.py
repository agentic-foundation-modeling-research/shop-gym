"""Unit tests for :mod:`shop_gen.data_synth.images`.

Covers the T3.10 requirements from
``docs/impl/shop_gen_implementation.md``:

* :class:`PlaceholderBackend` emits well-formed SVG bytes that include
  the product title and category-derived shapes.
* Same inputs always produce the same bytes (deterministic
  fingerprint requirement, spec §5.7).
* :class:`AIBackend` is constructible but :meth:`render` raises
  :class:`NotImplementedError` (v0.1 stub; M8 follow-up).
* :func:`get_backend` resolves both backend literals and rejects
  unknown names.
* :class:`GenImagesStep`'s declared step contract matches spec §5.7.1.
* The step writes ``data/images/<handle>-<n>.svg`` for every
  ``ProductSkeleton`` and every ``images_per_product`` slot and a sentinel manifest under
  ``.shop_gen/stage_cache/images_manifest.json``.
* Pipeline registration surfaces ``gen_images`` in the data-synth
  phase listing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shop_gen.config import CatalogConfig, ShopGenConfig
from shop_gen.data_synth import (
    AIBackend,
    CollectionDraft,
    GenImagesStep,
    ImageBackend,
    PlaceholderBackend,
    ProductDetail,
    ProductSkeleton,
    get_backend,
)
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _collection(handle: str, *, count: int) -> CollectionDraft:
    return CollectionDraft(
        title=handle.replace("-", " ").title(),
        handle=handle,
        description=f"Plain description of {handle}.",
        sort_order="manual",
        target_product_count=count,
    )


_OUTERWEAR = _collection("outerwear", count=2)
_KITCHEN = _collection("kitchen-tools", count=2)
_COLLECTIONS: tuple[CollectionDraft, ...] = (_OUTERWEAR, _KITCHEN)


def _skeleton(handle: str, *, collection: str, title: str | None = None) -> ProductSkeleton:
    return ProductSkeleton(
        title=title or handle.replace("-", " "),
        handle=handle,
        price="29.99",
        collection_handle=collection,
    )


_OUTERWEAR_SKELETONS: list[ProductSkeleton] = [
    _skeleton("warm-winter-coat", collection="outerwear"),
    _skeleton("waterproof-rain-jacket", collection="outerwear"),
]
_KITCHEN_SKELETONS: list[ProductSkeleton] = [
    _skeleton("ceramic-coffee-mug", collection="kitchen-tools"),
    _skeleton("stainless-mixing-bowl", collection="kitchen-tools"),
]
_ALL_SKELETONS: list[ProductSkeleton] = _OUTERWEAR_SKELETONS + _KITCHEN_SKELETONS

_DEFAULT_IMAGES: int = 2
_LARGER_IMAGES: int = 3
_EXPECTED_TOTAL_IMAGES: int = len(_ALL_SKELETONS) * _DEFAULT_IMAGES


def _detail(
    handle: str,
    *,
    vendor: str = "AisleArena",
    product_type: str = "outerwear",
) -> ProductDetail:
    return ProductDetail.model_validate(
        {
            "handle": handle,
            "description_html": "<p>warm and quiet.</p>",
            "vendor": vendor,
            "product_type": product_type,
            "tags": ["warm", "winter"],
            "options": [
                {"name": "Size", "position": 1, "values": ["S", "M", "L"]},
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
            ],
        },
    )


_OUTERWEAR_DETAILS: list[ProductDetail] = [
    _detail("warm-winter-coat"),
    _detail("waterproof-rain-jacket"),
]
_KITCHEN_DETAILS: list[ProductDetail] = [
    _detail("ceramic-coffee-mug", product_type="mug"),
    _detail("stainless-mixing-bowl", product_type="bowl"),
]


def _materialise_workspace(
    out_dir: Path,
    *,
    collections: list[CollectionDraft] | None = None,
    skeletons: list[ProductSkeleton] | None = None,
    details_by_collection: dict[str, list[ProductDetail]] | None = None,
) -> None:
    actual_collections = collections if collections is not None else list(_COLLECTIONS)
    actual_skeletons = skeletons if skeletons is not None else _ALL_SKELETONS
    actual_details = (
        details_by_collection
        if details_by_collection is not None
        else {
            "outerwear": _OUTERWEAR_DETAILS,
            "kitchen-tools": _KITCHEN_DETAILS,
        }
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "collections.json").write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in actual_collections],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (cache_dir / "skeletons.json").write_text(
        json.dumps([s.model_dump(mode="json") for s in actual_skeletons], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    details_dir = cache_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, Any]] = []
    for collection in actual_collections:
        details = actual_details.get(collection.handle, [])
        file_name = f"{collection.handle}.json"
        (details_dir / file_name).write_text(
            json.dumps([d.model_dump(mode="json") for d in details], indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        manifest_entries.append(
            {
                "handle": collection.handle,
                "file": file_name,
                "details_count": len(details),
                "dropped_count": 0,
            },
        )
    manifest = {
        "collections": manifest_entries,
        "total_products": sum(len(d) for d in actual_details.values()),
        "total_dropped": 0,
    }
    (details_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# PlaceholderBackend
# --------------------------------------------------------------------------- #


def test_placeholder_backend_emits_well_formed_svg() -> None:
    backend = PlaceholderBackend()
    body = backend.render(
        handle="warm-winter-coat",
        index=0,
        title="warm winter coat",
        category="outerwear",
        width=800,
        height=800,
    )
    text = body.decode("utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    assert "<svg " in text
    assert text.rstrip().endswith("</svg>")
    assert 'width="800"' in text
    assert 'height="800"' in text
    assert 'viewBox="0 0 800 800"' in text
    assert "warm winter coat" in text


def test_placeholder_backend_is_deterministic() -> None:
    backend = PlaceholderBackend()
    args: dict[str, Any] = {
        "handle": "ceramic-coffee-mug",
        "index": 1,
        "title": "ceramic coffee mug",
        "category": "kitchen-tools",
        "width": 800,
        "height": 800,
    }
    assert backend.render(**args) == backend.render(**args)


def test_placeholder_backend_distinct_categories_produce_different_bytes() -> None:
    backend = PlaceholderBackend()
    a = backend.render(
        handle="x",
        index=0,
        title="t",
        category="outerwear",
        width=800,
        height=800,
    )
    b = backend.render(
        handle="x",
        index=0,
        title="t",
        category="kitchen-tools",
        width=800,
        height=800,
    )
    assert a != b


def test_placeholder_backend_distinct_indices_produce_different_icons() -> None:
    """Different ``index`` values yield different icon shapes for the same product."""
    backend = PlaceholderBackend()
    images_per_product = 8
    bodies = {
        backend.render(
            handle="x",
            index=i,
            title="t",
            category="c",
            width=800,
            height=800,
        )
        for i in range(images_per_product)
    }
    # With 4 shapes, 8 indices should produce at least 2 distinct outputs.
    distinct_min = 2
    assert len(bodies) >= distinct_min


def test_placeholder_backend_escapes_title_html() -> None:
    backend = PlaceholderBackend()
    body = backend.render(
        handle="x",
        index=0,
        title='hex<>"&',
        category="c",
        width=800,
        height=800,
    ).decode("utf-8")
    assert "<>" not in body
    assert "&lt;" in body
    assert "&gt;" in body
    assert "&amp;" in body


def test_placeholder_backend_rejects_non_positive_dimensions() -> None:
    backend = PlaceholderBackend()
    with pytest.raises(ValueError, match="positive dimensions"):
        backend.render(
            handle="x",
            index=0,
            title="t",
            category="c",
            width=0,
            height=800,
        )


def test_placeholder_backend_handles_empty_title() -> None:
    backend = PlaceholderBackend()
    body = backend.render(
        handle="x",
        index=0,
        title="",
        category="c",
        width=800,
        height=800,
    ).decode("utf-8")
    # Empty title still renders a valid (if mostly blank) SVG.
    assert "<svg" in body
    assert "</svg>" in body


def test_placeholder_backend_wraps_long_title() -> None:
    backend = PlaceholderBackend()
    body = backend.render(
        handle="x",
        index=0,
        title="this is a very long product title that needs wrapping",
        category="c",
        width=800,
        height=800,
    ).decode("utf-8")
    # Multi-tspan output indicates word-wrapping kicked in.
    expected_wrap_lines = 2
    assert body.count("<tspan") >= expected_wrap_lines


# --------------------------------------------------------------------------- #
# AIBackend
# --------------------------------------------------------------------------- #


def test_ai_backend_render_raises_not_implemented() -> None:
    backend = AIBackend()
    with pytest.raises(NotImplementedError, match="ai"):
        backend.render(
            handle="x",
            index=0,
            title="t",
            category="c",
            width=800,
            height=800,
        )


def test_ai_backend_metadata() -> None:
    backend = AIBackend()
    assert backend.name == "ai"
    assert backend.extension == ".png"


# --------------------------------------------------------------------------- #
# get_backend
# --------------------------------------------------------------------------- #


def test_get_backend_placeholder_returns_placeholder_backend() -> None:
    backend = get_backend("placeholder")
    assert isinstance(backend, PlaceholderBackend)


def test_get_backend_ai_returns_ai_backend() -> None:
    backend = get_backend("ai")
    assert isinstance(backend, AIBackend)


def test_image_backend_protocol_runtime_check() -> None:
    """Both shipped backends satisfy the :class:`ImageBackend` protocol."""
    assert isinstance(PlaceholderBackend(), ImageBackend)
    assert isinstance(AIBackend(), ImageBackend)


# --------------------------------------------------------------------------- #
# GenImagesStep
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = GenImagesStep()
    assert step.id == "gen_images"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "images_manifest.json"]
    assert step.depends_on == ["synth_product_details"]
    assert step.version == 1


def test_step_run_writes_one_svg_per_product_image_slot(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    GenImagesStep().run(ctx)

    images_dir = out_dir / "data" / "images"
    assert images_dir.is_dir()
    files = sorted(p.name for p in images_dir.iterdir())
    expected = sorted(f"{s.handle}-{i}.svg" for s in _ALL_SKELETONS for i in range(_DEFAULT_IMAGES))
    assert files == expected
    for path in images_dir.iterdir():
        body = path.read_text(encoding="utf-8")
        assert body.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
        assert "</svg>" in body


def test_step_run_writes_manifest(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    GenImagesStep().run(ctx)

    manifest_path = out_dir / ".shop_gen" / "stage_cache" / "images_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "placeholder"
    assert manifest["extension"] == ".svg"
    assert manifest["images_per_product"] == _DEFAULT_IMAGES
    assert manifest["total_images"] == _EXPECTED_TOTAL_IMAGES
    assert len(manifest["entries"]) == _EXPECTED_TOTAL_IMAGES
    handles = {entry["handle"] for entry in manifest["entries"]}
    assert handles == {s.handle for s in _ALL_SKELETONS}
    for entry in manifest["entries"]:
        assert entry["file"].startswith("data/images/")
        assert entry["file"].endswith(".svg")
        assert entry["width"] > 0
        assert entry["height"] > 0


def test_step_run_uses_configured_images_per_product(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        catalog=CatalogConfig(images_per_product=_LARGER_IMAGES),
    )
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    GenImagesStep().run(ctx)

    images_dir = out_dir / "data" / "images"
    assert sum(1 for _ in images_dir.iterdir()) == len(_ALL_SKELETONS) * _LARGER_IMAGES


def test_step_run_is_deterministic(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)

    def _run() -> tuple[bytes, bytes]:
        ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
        GenImagesStep().run(ctx)
        manifest_bytes = (
            out_dir / ".shop_gen" / "stage_cache" / "images_manifest.json"
        ).read_bytes()
        sample = (out_dir / "data" / "images" / "warm-winter-coat-0.svg").read_bytes()
        return manifest_bytes, sample

    assert _run() == _run()


def test_step_run_ai_backend_raises_not_implemented(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir, image_backend="ai")
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(NotImplementedError, match="ai"):
        GenImagesStep().run(ctx)


def test_step_run_missing_collections_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match="cached collections"):
        GenImagesStep().run(ctx)


def test_step_run_missing_skeletons_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in _COLLECTIONS]) + "\n",
        encoding="utf-8",
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match="cached skeletons"):
        GenImagesStep().run(ctx)


def test_step_run_missing_details_manifest(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in _COLLECTIONS]) + "\n",
        encoding="utf-8",
    )
    (cache_dir / "skeletons.json").write_text(
        json.dumps([s.model_dump(mode="json") for s in _ALL_SKELETONS]) + "\n",
        encoding="utf-8",
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match="details manifest"):
        GenImagesStep().run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.10 wires ``gen_images`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "gen_images" in grouped["data_synth"]
