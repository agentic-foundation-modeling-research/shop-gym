"""Unit tests for :mod:`shop_gen.data_synth.collections`.

Covers the T3.5 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``synth_collections`` makes exactly one LLM call producing a JSON
  array of :class:`~shop_gen.data_synth.collections.CollectionDraft`-shaped
  objects.
* The cached payload at ``.shop_gen/stage_cache/collections.json`` is
  pydantic-validated.
* Count is enforced (default 10, optionally tuned to the merged stats).
* Plain-descriptive title rule: titles must NOT contain any allowlisted
  brand token (spec §5.6).
* Schema validity is asserted.
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
from shop_gen.brands.allowlist import load_allowlist
from shop_gen.config import ShopGenConfig
from shop_gen.data_synth import (
    CollectionDraft,
    StageSynthError,
    SynthCollectionsStep,
)
from shop_gen.data_synth.collections import (
    resolve_target_count,
    synth_collections_from_identity,
)
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import StepContext

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


_IDENTITY: dict[str, object] = {
    "name": "AisleArena",
    "descriptor": "boutique outdoor storefront",
    "tone": ["rugged", "warm"],
    "currency": "USD",
    "country": "US",
}

_CAPABILITIES: dict[str, object] = {
    "version": "0.1",
    "shop": {
        "descriptor": "boutique outdoor storefront",
        "category": "outdoor",
        "tone": ["rugged", "warm"],
    },
    "info_pages": ["about", "contact", "faq"],
}

_STATS_DEFAULT_10: dict[str, object] = {
    "products_total": 200,
    "collections_total": 10,
    "products_per_collection": {"avg": 20.0, "median": 20.0, "max": 30},
    "price": {"min": 5.0, "max": 200.0, "median": 40.0, "currency": "USD"},
    "products_with_variants_pct": 0.5,
    "variant_axes_observed": ["Size", "Color"],
    "navigation_depth_max": 2,
    "homepage_section_count": 3,
    "info_pages_count": 3,
    "feature_count": 5,
}

_DEFAULT_HANDLES: tuple[str, ...] = (
    "outerwear",
    "kitchen-tools",
    "trail-running",
    "footwear",
    "accessories",
    "bags",
    "headwear",
    "tops",
    "bottoms",
    "gear",
)
_DEFAULT_TARGET_COUNT: int = len(_DEFAULT_HANDLES)
"""Asserted count when ``stats.collections_total`` matches the spec default."""
_TARGET_COUNT_MIN: int = 3
_TARGET_COUNT_MAX: int = 30
"""Mirror :data:`shop_gen.data_synth.collections._TARGET_COUNT_MIN` /
``_TARGET_COUNT_MAX``; mirrored here so test assertions can name
the value rather than embedding magic numbers."""


def _draft(handle: str, *, title: str | None = None, count: int = 20) -> dict[str, object]:
    return {
        "title": title if title is not None else handle.replace("-", " "),
        "handle": handle,
        "description": f"Plain description of {handle}.",
        "sort_order": "manual",
        "target_product_count": count,
    }


def _stub_response(handles: tuple[str, ...] = _DEFAULT_HANDLES) -> str:
    return json.dumps([_draft(h) for h in handles])


def _materialise_workspace(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "identity.json").write_text(
        json.dumps(_IDENTITY, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manual_dir = out_dir / "manual"
    manual_dir.mkdir(parents=True, exist_ok=True)
    (manual_dir / "capabilities.json").write_text(
        json.dumps(_CAPABILITIES, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (manual_dir / "stats.json").write_text(
        json.dumps(_STATS_DEFAULT_10, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# resolve_target_count
# --------------------------------------------------------------------------- #


def test_resolve_target_count_uses_stats_when_positive() -> None:
    requested = 12
    assert resolve_target_count({"collections_total": requested}) == requested


def test_resolve_target_count_falls_back_to_default() -> None:
    assert resolve_target_count({}) == _DEFAULT_TARGET_COUNT
    assert resolve_target_count({"collections_total": 0}) == _DEFAULT_TARGET_COUNT
    assert resolve_target_count({"collections_total": -3}) == _DEFAULT_TARGET_COUNT


def test_resolve_target_count_clamps_high() -> None:
    assert resolve_target_count({"collections_total": 999}) == _TARGET_COUNT_MAX


def test_resolve_target_count_clamps_low() -> None:
    assert resolve_target_count({"collections_total": 1}) == _TARGET_COUNT_MIN


def test_resolve_target_count_ignores_non_int() -> None:
    """Booleans / strings / floats fall back to the default rather than coercing."""
    assert resolve_target_count({"collections_total": True}) == _DEFAULT_TARGET_COUNT
    assert resolve_target_count({"collections_total": "12"}) == _DEFAULT_TARGET_COUNT
    assert resolve_target_count({"collections_total": 12.5}) == _DEFAULT_TARGET_COUNT


# --------------------------------------------------------------------------- #
# synth_collections_from_identity
# --------------------------------------------------------------------------- #


def test_synth_collections_calls_llm_once_and_validates() -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    drafts = synth_collections_from_identity(
        identity=_IDENTITY,
        capabilities=_CAPABILITIES,
        stats=_STATS_DEFAULT_10,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert len(drafts) == _DEFAULT_TARGET_COUNT
    assert [d.handle for d in drafts] == list(_DEFAULT_HANDLES)
    assert all(isinstance(d, CollectionDraft) for d in drafts)


def test_synth_collections_strips_code_fence() -> None:
    fenced = "```json\n" + _stub_response() + "\n```"
    completer = _StubCompleter(responses=[fenced])
    drafts = synth_collections_from_identity(
        identity=_IDENTITY,
        capabilities=_CAPABILITIES,
        stats=_STATS_DEFAULT_10,
        completer=cast(LLMCompleter, completer),
    )
    assert [d.handle for d in drafts] == list(_DEFAULT_HANDLES)


def test_synth_collections_uses_stats_target_count() -> None:
    """When stats request 5 collections, the LLM is asked for 5 and the count is enforced."""
    requested = 5
    stats = {**_STATS_DEFAULT_10, "collections_total": requested}
    five_handles = _DEFAULT_HANDLES[:requested]
    completer = _StubCompleter(responses=[_stub_response(five_handles)])
    drafts = synth_collections_from_identity(
        identity=_IDENTITY,
        capabilities=_CAPABILITIES,
        stats=stats,
        completer=cast(LLMCompleter, completer),
    )
    assert len(drafts) == requested
    # Prompt must include the resolved target count so the LLM honors it.
    prompt = completer.prompts[0]
    assert f"{requested} collection" in prompt


def test_synth_collections_rejects_wrong_count() -> None:
    """The LLM emits 9 entries when stats default to 10; the step rejects."""
    short_count = _DEFAULT_TARGET_COUNT - 1
    short_handles = _DEFAULT_HANDLES[:short_count]
    completer = _StubCompleter(responses=[_stub_response(short_handles)])
    with pytest.raises(
        StageSynthError,
        match=f"expected {_DEFAULT_TARGET_COUNT} collections, got {short_count}",
    ):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_empty_response() -> None:
    completer = _StubCompleter(responses=[""])
    with pytest.raises(StageSynthError, match="empty response"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_empty_array() -> None:
    completer = _StubCompleter(responses=["[]"])
    with pytest.raises(StageSynthError, match="empty collections array"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_object_response() -> None:
    completer = _StubCompleter(responses=["{}"])
    with pytest.raises(StageSynthError, match="JSON array"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_duplicate_handles() -> None:
    dupes = (*_DEFAULT_HANDLES[:9], _DEFAULT_HANDLES[0])
    completer = _StubCompleter(responses=[_stub_response(dupes)])
    with pytest.raises(StageSynthError, match="duplicate collection handle"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_non_positive_target_count() -> None:
    bad = [_draft(h) for h in _DEFAULT_HANDLES]
    bad[3]["target_product_count"] = 0
    completer = _StubCompleter(responses=[json.dumps(bad)])
    with pytest.raises(StageSynthError, match="non-positive target_product_count"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_missing_field() -> None:
    """A draft lacking ``description`` fails the :class:`CollectionDraft` schema."""
    bad: list[dict[str, object]] = [_draft(h) for h in _DEFAULT_HANDLES]
    del bad[0]["description"]
    completer = _StubCompleter(responses=[json.dumps(bad)])
    with pytest.raises(StageSynthError, match="CollectionDraft schema validation"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_extra_field() -> None:
    """Closed schema: extra fields fail validation."""
    bad: list[dict[str, object]] = [_draft(h) for h in _DEFAULT_HANDLES]
    bad[0]["bonus"] = "not-allowed"
    completer = _StubCompleter(responses=[json.dumps(bad)])
    with pytest.raises(StageSynthError, match="CollectionDraft schema validation"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_rejects_allowlist_token_in_title() -> None:
    """Plain-descriptive rule (spec §5.6): no allowlist brand tokens in titles."""
    bad: list[dict[str, object]] = [_draft(h) for h in _DEFAULT_HANDLES]
    # Use an allowlist token from fake_brands.json; "AisleArena" is allowlisted.
    bad[2]["title"] = "AisleArena outerwear collection"
    completer = _StubCompleter(responses=[json.dumps(bad)])
    with pytest.raises(StageSynthError, match=r"AisleArena"):
        synth_collections_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            stats=_STATS_DEFAULT_10,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_collections_accepts_allowlist_override() -> None:
    """Caller can pass a custom :class:`Allowlist` for offline testing."""
    completer = _StubCompleter(responses=[_stub_response()])
    drafts = synth_collections_from_identity(
        identity=_IDENTITY,
        capabilities=_CAPABILITIES,
        stats=_STATS_DEFAULT_10,
        completer=cast(LLMCompleter, completer),
        allowlist=load_allowlist(),
    )
    assert len(drafts) == _DEFAULT_TARGET_COUNT


# --------------------------------------------------------------------------- #
# SynthCollectionsStep
# --------------------------------------------------------------------------- #


def test_step_metadata_for_multi_seed() -> None:
    step = SynthCollectionsStep(
        manual_step_ids=(
            "merge_capabilities",
            "merge_manual_prose",
            "compute_merge_stats",
        ),
    )
    assert step.id == "synth_collections"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "collections.json"]
    assert step.depends_on == [
        "synth_identity",
        "merge_capabilities",
        "merge_manual_prose",
        "compute_merge_stats",
    ]
    assert step.version == 1


def test_step_metadata_for_single_seed() -> None:
    step = SynthCollectionsStep(manual_step_ids=("copy_seed_manual",))
    assert step.depends_on == ["synth_identity", "copy_seed_manual"]


def test_step_metadata_listing_branch() -> None:
    step = SynthCollectionsStep()
    assert step.depends_on == ["synth_identity"]


def test_step_run_writes_stage_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthCollectionsStep(manual_step_ids=("copy_seed_manual",))
    step.run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "collections.json").read_text(
            encoding="utf-8",
        ),
    )
    assert isinstance(cached, list)
    assert [CollectionDraft.model_validate(entry).handle for entry in cached] == list(
        _DEFAULT_HANDLES,
    )


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
        step = SynthCollectionsStep(manual_step_ids=("copy_seed_manual",))
        step.run(ctx)
        return (out_dir / ".shop_gen" / "stage_cache" / "collections.json").read_bytes()

    assert _run() == _run()


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthCollectionsStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_identity(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    manual_dir = out_dir / "manual"
    manual_dir.mkdir()
    (manual_dir / "capabilities.json").write_text(
        json.dumps(_CAPABILITIES) + "\n",
        encoding="utf-8",
    )
    (manual_dir / "stats.json").write_text(
        json.dumps(_STATS_DEFAULT_10) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthCollectionsStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match=r"identity\.json"):
        step.run(ctx)


def test_step_run_missing_capabilities(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "identity.json").write_text(
        json.dumps(_IDENTITY) + "\n",
        encoding="utf-8",
    )
    manual_dir = out_dir / "manual"
    manual_dir.mkdir()
    (manual_dir / "stats.json").write_text(
        json.dumps(_STATS_DEFAULT_10) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthCollectionsStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match="capabilities"):
        step.run(ctx)


def test_step_run_missing_stats(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "identity.json").write_text(
        json.dumps(_IDENTITY) + "\n",
        encoding="utf-8",
    )
    manual_dir = out_dir / "manual"
    manual_dir.mkdir()
    (manual_dir / "capabilities.json").write_text(
        json.dumps(_CAPABILITIES) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthCollectionsStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match="stats"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.5 wires ``synth_collections`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_collections" in grouped["data_synth"]
