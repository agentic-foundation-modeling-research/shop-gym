"""Unit tests for :mod:`shop_arena.gen.data_synth.skeletons`.

Covers the T3.6 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``synth_product_skeletons`` makes exactly one bulk LLM call producing
  a JSON array of
  :class:`~shop_arena.gen.data_synth.skeletons.ProductSkeleton`-shaped objects.
* The cached payload at ``.shop_gen/stage_cache/skeletons.json`` is
  pydantic-validated.
* Per-collection dedup: duplicate handles within a single collection
  fail; cross-collection clashes are tolerated.
* Schema validity is asserted (closed schema rejects extras / missing
  fields).
* The 5-word naming rule is enforced both at validation time and via a
  prompt-asserting test.
* The step requires ``ctx.runtime`` and surfaces a clear error when it
  is ``None``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from harness.runtimes import LLMCompleter
from shop_arena.gen.brands.allowlist import load_allowlist
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.data_synth import (
    CollectionDraft,
    ProductSkeleton,
    StageSynthError,
    SynthProductSkeletonsStep,
)
from shop_arena.gen.data_synth.prompts import load_synth_product_skeletons_template
from shop_arena.gen.data_synth.skeletons import synth_product_skeletons_from_collections
from shop_arena.gen.pipeline import list_steps
from shop_arena.gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


@dataclass
class _StubCompleter:
    """Recording :class:`LLMCompleter` returning a queue of canned responses."""

    responses: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM was called more times than expected")
        return self.responses.pop(0)


def _draft_collection(handle: str, *, count: int) -> CollectionDraft:
    return CollectionDraft(
        title=handle.replace("-", " "),
        handle=handle,
        description=f"Plain description of {handle}.",
        sort_order="manual",
        target_product_count=count,
    )


_TWO_COLLECTIONS: tuple[CollectionDraft, ...] = (
    _draft_collection("outerwear", count=3),
    _draft_collection("kitchen-tools", count=2),
)
_TOTAL_PRODUCTS: int = sum(c.target_product_count for c in _TWO_COLLECTIONS)


def _skeleton_dict(
    handle: str,
    *,
    collection_handle: str,
    title: str | None = None,
    price: str = "29.99",
) -> dict[str, object]:
    return {
        "title": title if title is not None else handle.replace("-", " "),
        "handle": handle,
        "price": price,
        "collection_handle": collection_handle,
    }


def _default_skeletons() -> list[dict[str, object]]:
    """Return a valid skeleton payload matching :data:`_TWO_COLLECTIONS`."""
    return [
        _skeleton_dict("warm-winter-coat", collection_handle="outerwear"),
        _skeleton_dict("waterproof-rain-jacket", collection_handle="outerwear"),
        _skeleton_dict("packable-down-vest", collection_handle="outerwear"),
        _skeleton_dict("ceramic-coffee-mug", collection_handle="kitchen-tools"),
        _skeleton_dict("stainless-mixing-bowl", collection_handle="kitchen-tools"),
    ]


def _stub_response(skeletons: list[dict[str, object]] | None = None) -> str:
    payload = skeletons if skeletons is not None else _default_skeletons()
    return json.dumps(payload)


def _materialise_workspace(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "collections.json").write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in _TWO_COLLECTIONS],
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


# --------------------------------------------------------------------------- #
# Prompt-asserting tests
# --------------------------------------------------------------------------- #


def test_prompt_template_states_two_to_five_word_rule() -> None:
    """The prompt body itself ships the 2-5 word naming rule (T3.6 prompt-asserting test)."""
    body = load_synth_product_skeletons_template()
    assert "Two to five whitespace-" in body
    assert "separated words" in body


def test_prompt_template_forbids_brand_tokens() -> None:
    """The prompt body forbids brand-shaped tokens in titles."""
    body = load_synth_product_skeletons_template()
    assert "no brand-shaped tokens" in body.lower() or "do not invent brand names" in body.lower()


# --------------------------------------------------------------------------- #
# synth_product_skeletons_from_collections
# --------------------------------------------------------------------------- #


def test_synth_skeletons_calls_llm_once_and_validates() -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    skeletons = synth_product_skeletons_from_collections(
        collections=list(_TWO_COLLECTIONS),
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert len(skeletons) == _TOTAL_PRODUCTS
    assert all(isinstance(s, ProductSkeleton) for s in skeletons)


def test_synth_skeletons_prompt_includes_total_and_collection_handles() -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    synth_product_skeletons_from_collections(
        collections=list(_TWO_COLLECTIONS),
        completer=cast(LLMCompleter, completer),
    )
    prompt = completer.prompts[0]
    assert str(_TOTAL_PRODUCTS) in prompt
    for collection in _TWO_COLLECTIONS:
        assert collection.handle in prompt


def test_synth_skeletons_strips_code_fence() -> None:
    fenced = "```json\n" + _stub_response() + "\n```"
    completer = _StubCompleter(responses=[fenced])
    skeletons = synth_product_skeletons_from_collections(
        collections=list(_TWO_COLLECTIONS),
        completer=cast(LLMCompleter, completer),
    )
    assert len(skeletons) == _TOTAL_PRODUCTS


def test_synth_skeletons_rejects_empty_collections() -> None:
    completer = _StubCompleter(responses=[])
    with pytest.raises(StageSynthError, match="empty collection list"):
        synth_product_skeletons_from_collections(
            collections=[],
            completer=cast(LLMCompleter, completer),
        )
    assert completer.prompts == []


def test_synth_skeletons_rejects_empty_response() -> None:
    completer = _StubCompleter(responses=[""])
    with pytest.raises(StageSynthError, match="empty response"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_empty_array() -> None:
    completer = _StubCompleter(responses=["[]"])
    with pytest.raises(StageSynthError, match="empty skeletons array"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_object_response() -> None:
    completer = _StubCompleter(responses=["{}"])
    with pytest.raises(StageSynthError, match="JSON array"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_wrong_total_count() -> None:
    short = _default_skeletons()[:-1]
    completer = _StubCompleter(responses=[_stub_response(short)])
    with pytest.raises(
        StageSynthError,
        match=f"expected {_TOTAL_PRODUCTS} skeletons, got {_TOTAL_PRODUCTS - 1}",
    ):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_unknown_collection_handle() -> None:
    bad = _default_skeletons()
    bad[0]["collection_handle"] = "phantom"
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match="unknown collection_handle 'phantom'"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_per_collection_count_mismatch() -> None:
    """Reassign one outerwear skeleton to kitchen-tools; counts diverge."""
    bad = _default_skeletons()
    bad[0]["collection_handle"] = "kitchen-tools"
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match=r"collection 'outerwear' expected 3 skeletons"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_intra_collection_duplicate_handles() -> None:
    """Per-collection dedup: same handle twice within outerwear fails."""
    bad = _default_skeletons()
    bad[1]["handle"] = bad[0]["handle"]
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match="duplicate skeleton handle"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_tolerates_cross_collection_handle_clash() -> None:
    """Cross-collection conflicts are allowed (assembled-time disambiguation per spec §5.3)."""
    payload = _default_skeletons()
    # Reuse an outerwear handle inside kitchen-tools.
    payload[3] = _skeleton_dict(
        cast("str", payload[0]["handle"]),
        collection_handle="kitchen-tools",
    )
    completer = _StubCompleter(responses=[_stub_response(payload)])
    skeletons = synth_product_skeletons_from_collections(
        collections=list(_TWO_COLLECTIONS),
        completer=cast(LLMCompleter, completer),
    )
    assert len(skeletons) == _TOTAL_PRODUCTS


def test_synth_skeletons_rejects_too_few_words_in_title() -> None:
    bad = _default_skeletons()
    bad[0]["title"] = "coat"  # one word
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match=r"has 1 words; expected between 2 and 5"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_too_many_words_in_title() -> None:
    bad = _default_skeletons()
    bad[0]["title"] = "extra long winter parka coat with hood"  # 7 words
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match=r"has 7 words; expected between 2 and 5"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_missing_field() -> None:
    """A skeleton lacking ``price`` fails the :class:`ProductSkeleton` schema."""
    bad: list[dict[str, object]] = _default_skeletons()
    del bad[0]["price"]
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match="ProductSkeleton schema validation"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_extra_field() -> None:
    """Closed schema: extra fields fail validation."""
    bad: list[dict[str, object]] = _default_skeletons()
    bad[0]["bonus"] = "not-allowed"
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match="ProductSkeleton schema validation"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_rejects_allowlist_token_in_title() -> None:
    """Plain-descriptive rule (spec §5.6): no allowlist brand tokens in titles."""
    bad = _default_skeletons()
    # ``AisleArena`` is allowlisted in fake_brands.json.
    bad[0]["title"] = "AisleArena warm winter coat"
    completer = _StubCompleter(responses=[_stub_response(bad)])
    with pytest.raises(StageSynthError, match=r"AisleArena"):
        synth_product_skeletons_from_collections(
            collections=list(_TWO_COLLECTIONS),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_skeletons_accepts_allowlist_override() -> None:
    """Caller can pass a custom :class:`Allowlist` for offline testing."""
    completer = _StubCompleter(responses=[_stub_response()])
    skeletons = synth_product_skeletons_from_collections(
        collections=list(_TWO_COLLECTIONS),
        completer=cast(LLMCompleter, completer),
        allowlist=load_allowlist(),
    )
    assert len(skeletons) == _TOTAL_PRODUCTS


# --------------------------------------------------------------------------- #
# SynthProductSkeletonsStep
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = SynthProductSkeletonsStep()
    assert step.id == "synth_product_skeletons"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "skeletons.json"]
    assert step.depends_on == ["synth_collections"]
    assert step.version == 1


def test_step_run_writes_stage_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthProductSkeletonsStep()
    step.run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "skeletons.json").read_text(
            encoding="utf-8",
        ),
    )
    assert isinstance(cached, list)
    assert len(cached) == _TOTAL_PRODUCTS
    # Every entry round-trips through the pydantic schema.
    for entry in cached:
        ProductSkeleton.model_validate(entry)


def test_step_run_is_deterministic(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    response = _stub_response()

    def _run() -> bytes:
        completer = _StubCompleter(responses=[response])
        ctx = StepContext(
            config=config,
            out_dir=out_dir,
            runtime=cast(LLMCompleter, completer),
        )
        step = SynthProductSkeletonsStep()
        step.run(ctx)
        return (out_dir / ".shop_gen" / "stage_cache" / "skeletons.json").read_bytes()

    assert _run() == _run()


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthProductSkeletonsStep()
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_collections_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthProductSkeletonsStep()
    with pytest.raises(FileNotFoundError, match=r"cached collections"):
        step.run(ctx)


def test_step_run_rejects_malformed_collections_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text("{}", encoding="utf-8")
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthProductSkeletonsStep()
    with pytest.raises(StageSynthError, match="must be a JSON array"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.6 wires ``synth_product_skeletons`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_product_skeletons" in grouped["data_synth"]
