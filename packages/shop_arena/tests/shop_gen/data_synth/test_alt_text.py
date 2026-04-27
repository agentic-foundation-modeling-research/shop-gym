"""Unit tests for :mod:`shop_gen.data_synth.alt_text`.

Covers the T3.9 requirements from
``docs/impl/shop_gen_implementation.md``:

* Happy path: one LLM call per collection (parallel; ≤ 5 concurrent),
  pydantic-validated mapping cached at
  ``.shop_gen/stage_cache/alt_text.json``.
* Coverage: every product handle in ``skeletons`` is keyed in the
  response. Missing handles fail the step.
* Cardinality: each value list has exactly ``images_per_product``
  strings. Off-by-one fails the step.
* Length bounds: every alt-text string is between
  ``_MIN_ALT_CHARS`` and ``_MAX_ALT_CHARS`` characters inclusive.
* Step contract: id, phase, outputs, depends_on, version; runtime
  required; cached upstream files required; ``alt_text.json`` is
  byte-deterministic.
* Pipeline registration surfaces ``synth_alt_text`` in the data-synth
  phase listing.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from harness.runtimes import LLMCompleter
from shop_gen.config import CatalogConfig, ShopGenConfig
from shop_gen.data_synth import (
    AltTextPayload,
    CollectionDraft,
    ProductDetail,
    ProductSkeleton,
    StageSynthError,
    SynthAltTextStep,
)
from shop_gen.data_synth.alt_text import (
    _MAX_ALT_CHARS,
    _MIN_ALT_CHARS,
    synth_alt_text_for_collection,
)
from shop_gen.data_synth.prompts import load_synth_alt_text_template
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


def _collection(handle: str, *, count: int) -> CollectionDraft:
    return CollectionDraft(
        title=handle.replace("-", " "),
        handle=handle,
        description=f"Plain description of {handle}.",
        sort_order="manual",
        target_product_count=count,
    )


_OUTERWEAR = _collection("outerwear", count=2)
_KITCHEN = _collection("kitchen-tools", count=2)
_COLLECTIONS: tuple[CollectionDraft, ...] = (_OUTERWEAR, _KITCHEN)


def _skeleton(handle: str, *, collection: str) -> ProductSkeleton:
    return ProductSkeleton(
        title=handle.replace("-", " "),
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
_EXPECTED_COLLECTIONS: int = 2


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


def _alts_for(handle: str, *, count: int) -> list[str]:
    base = handle.replace("-", " ")
    angles = [
        f"front view of the {base} on a wooden bench",
        f"close up of the stitched seam on the {base}",
        f"three quarter angle of the {base} draped over a chair back",
        f"flat lay of the {base} on a linen surface",
    ]
    return angles[:count]


def _payload_for(skeletons: list[ProductSkeleton], *, count: int = 2) -> dict[str, list[str]]:
    return {s.handle: _alts_for(s.handle, count=count) for s in skeletons}


def _response_for(skeletons: list[ProductSkeleton], *, count: int = 2) -> str:
    return json.dumps(_payload_for(skeletons, count=count))


@dataclass
class _StubCompleter:
    """Thread-safe :class:`LLMCompleter` returning a dict of canned responses.

    Looks up each prompt by the first collection handle that appears in it,
    so parallel per-collection calls remain deterministic regardless of the
    thread-pool's scheduling order.
    """

    responses: dict[str, list[str]] = field(default_factory=dict)
    prompts: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        with self._lock:
            self.prompts.append(prompt)
            handle = _route_prompt(prompt, list(self.responses.keys()))
            queue = self.responses.get(handle)
            if not queue:
                raise AssertionError(
                    f"unexpected LLM call for collection={handle!r}; "
                    f"prompts so far={len(self.prompts)}",
                )
            return queue.pop(0)


def _route_prompt(prompt: str, handles: list[str]) -> str:
    for handle in handles:
        if f'"handle": "{handle}"' in prompt:
            return handle
    raise AssertionError(f"prompt does not reference any of {handles!r}")


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
        json.dumps(
            [s.model_dump(mode="json") for s in actual_skeletons],
            indent=2,
            sort_keys=True,
        )
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
# Prompt-asserting tests
# --------------------------------------------------------------------------- #


def test_prompt_template_states_length_bounds() -> None:
    body = load_synth_alt_text_template()
    assert "{min_chars}" in body
    assert "{max_chars}" in body
    assert "{images_per_product}" in body


def test_prompt_template_forbids_brand_tokens() -> None:
    body = load_synth_alt_text_template()
    assert "NO brand names" in body
    assert "plain descriptive" in body.lower()


# --------------------------------------------------------------------------- #
# synth_alt_text_for_collection
# --------------------------------------------------------------------------- #


def test_synth_alt_text_calls_llm_once_per_collection_happy_path() -> None:
    completer = _StubCompleter(
        responses={"outerwear": [_response_for(_OUTERWEAR_SKELETONS)]},
    )
    mapping = synth_alt_text_for_collection(
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        details=_OUTERWEAR_DETAILS,
        images_per_product=2,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert list(mapping.keys()) == ["warm-winter-coat", "waterproof-rain-jacket"]
    for alts in mapping.values():
        assert len(alts) == _DEFAULT_IMAGES
        for alt in alts:
            assert _MIN_ALT_CHARS <= len(alt) <= _MAX_ALT_CHARS


def test_synth_alt_text_strips_code_fence() -> None:
    fenced = "```json\n" + _response_for(_OUTERWEAR_SKELETONS) + "\n```"
    completer = _StubCompleter(responses={"outerwear": [fenced]})
    mapping = synth_alt_text_for_collection(
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        details=_OUTERWEAR_DETAILS,
        images_per_product=2,
        completer=cast(LLMCompleter, completer),
    )
    assert set(mapping.keys()) == {"warm-winter-coat", "waterproof-rain-jacket"}


def test_synth_alt_text_rejects_empty_skeleton_list() -> None:
    completer = _StubCompleter(responses={})
    with pytest.raises(StageSynthError, match="empty skeleton list"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=[],
            details=[],
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )
    assert completer.prompts == []


def test_synth_alt_text_rejects_non_positive_images_per_product() -> None:
    completer = _StubCompleter(responses={})
    with pytest.raises(StageSynthError, match="images_per_product must be positive"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=0,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_alt_text_rejects_array_response() -> None:
    completer = _StubCompleter(responses={"outerwear": ["[]"]})
    with pytest.raises(StageSynthError, match="JSON object"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_alt_text_rejects_missing_handle() -> None:
    """Coverage check (T3.9): every product handle must be in the response."""
    partial = json.dumps({"warm-winter-coat": _alts_for("warm-winter-coat", count=2)})
    completer = _StubCompleter(responses={"outerwear": [partial]})
    with pytest.raises(StageSynthError, match="missing"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_alt_text_rejects_unexpected_handle() -> None:
    """Cardinality check (T3.9): no extra handles outside the requested set."""
    payload = _payload_for(_OUTERWEAR_SKELETONS)
    payload["phantom-product"] = _alts_for("phantom-product", count=2)
    completer = _StubCompleter(responses={"outerwear": [json.dumps(payload)]})
    with pytest.raises(StageSynthError, match="unexpected handles"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_alt_text_rejects_wrong_alt_count() -> None:
    """Cardinality check (T3.9): each handle must have exactly ``images_per_product`` strings."""
    payload = _payload_for(_OUTERWEAR_SKELETONS, count=2)
    payload["warm-winter-coat"] = payload["warm-winter-coat"][:1]
    completer = _StubCompleter(responses={"outerwear": [json.dumps(payload)]})
    with pytest.raises(StageSynthError, match="expected exactly 2"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_alt_text_rejects_short_string() -> None:
    """Length-bound check (T3.9): below ``_MIN_ALT_CHARS`` fails."""
    payload = _payload_for(_OUTERWEAR_SKELETONS)
    payload["warm-winter-coat"][0] = "short"
    completer = _StubCompleter(responses={"outerwear": [json.dumps(payload)]})
    with pytest.raises(StageSynthError, match="outside bounds"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_alt_text_rejects_long_string() -> None:
    """Length-bound check (T3.9): above ``_MAX_ALT_CHARS`` fails."""
    payload = _payload_for(_OUTERWEAR_SKELETONS)
    payload["warm-winter-coat"][0] = "x" * (_MAX_ALT_CHARS + 1)
    completer = _StubCompleter(responses={"outerwear": [json.dumps(payload)]})
    with pytest.raises(StageSynthError, match="outside bounds"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_alt_text_rejects_non_string_alt() -> None:
    """Schema check: alt-text values must be strings."""
    payload: dict[str, Any] = {"warm-winter-coat": [123, 456]}
    payload["waterproof-rain-jacket"] = _alts_for("waterproof-rain-jacket", count=2)
    completer = _StubCompleter(responses={"outerwear": [json.dumps(payload)]})
    with pytest.raises(StageSynthError, match="schema validation"):
        synth_alt_text_for_collection(
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            details=_OUTERWEAR_DETAILS,
            images_per_product=2,
            completer=cast(LLMCompleter, completer),
        )


# --------------------------------------------------------------------------- #
# AltTextPayload schema
# --------------------------------------------------------------------------- #


def test_alt_text_payload_round_trips() -> None:
    raw = {"warm-winter-coat": ["a moderately long alt", "another moderately long alt"]}
    payload = AltTextPayload.model_validate(raw)
    assert payload.root == raw


# --------------------------------------------------------------------------- #
# SynthAltTextStep
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = SynthAltTextStep()
    assert step.id == "synth_alt_text"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "alt_text.json"]
    assert step.depends_on == ["synth_product_details"]
    assert step.version == 1


def test_step_run_writes_cache_for_every_product(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(
        responses={
            "outerwear": [_response_for(_OUTERWEAR_SKELETONS)],
            "kitchen-tools": [_response_for(_KITCHEN_SKELETONS)],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )

    SynthAltTextStep().run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "alt_text.json").read_text(encoding="utf-8"),
    )
    assert isinstance(cached, dict)
    assert set(cached.keys()) == {s.handle for s in _ALL_SKELETONS}
    for alts in cached.values():
        assert len(alts) == _DEFAULT_IMAGES
        for alt in alts:
            assert _MIN_ALT_CHARS <= len(alt) <= _MAX_ALT_CHARS
    assert len(completer.prompts) == _EXPECTED_COLLECTIONS  # one per collection


def test_step_run_uses_configured_images_per_product(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(
        responses={
            "outerwear": [_response_for(_OUTERWEAR_SKELETONS, count=_LARGER_IMAGES)],
            "kitchen-tools": [_response_for(_KITCHEN_SKELETONS, count=_LARGER_IMAGES)],
        },
    )
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        catalog=CatalogConfig(images_per_product=_LARGER_IMAGES),
    )
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )

    SynthAltTextStep().run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "alt_text.json").read_text(encoding="utf-8"),
    )
    for alts in cached.values():
        assert len(alts) == _LARGER_IMAGES


def test_step_run_is_deterministic(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)

    def _run() -> bytes:
        completer = _StubCompleter(
            responses={
                "outerwear": [_response_for(_OUTERWEAR_SKELETONS)],
                "kitchen-tools": [_response_for(_KITCHEN_SKELETONS)],
            },
        )
        ctx = StepContext(
            config=config,
            out_dir=out_dir,
            runtime=cast(LLMCompleter, completer),
        )
        SynthAltTextStep().run(ctx)
        return (out_dir / ".shop_gen" / "stage_cache" / "alt_text.json").read_bytes()

    assert _run() == _run()


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(ValueError, match="LLMCompleter"):
        SynthAltTextStep().run(ctx)


def test_step_run_missing_collections_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completer = _StubCompleter(responses={})
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )
    with pytest.raises(FileNotFoundError, match="cached collections"):
        SynthAltTextStep().run(ctx)


def test_step_run_missing_skeletons_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in _COLLECTIONS]) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(responses={})
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )
    with pytest.raises(FileNotFoundError, match="cached skeletons"):
        SynthAltTextStep().run(ctx)


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
    completer = _StubCompleter(responses={})
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )
    with pytest.raises(FileNotFoundError, match="details manifest"):
        SynthAltTextStep().run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.9 wires ``synth_alt_text`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_alt_text" in grouped["data_synth"]
