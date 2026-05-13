"""Unit tests for :mod:`shop_arena.gen.data_synth.pages`.

Covers the T3.4 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``synth_pages`` makes exactly one LLM call producing a JSON array of
  :class:`~shop_arena.gen.data_synth.schema.Page`-shaped objects.
* The cached payload at ``.shop_gen/stage_cache/pages.json`` is
  pydantic-validated.
* Duplicate / empty payloads are rejected.
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
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.data_synth import Page, StageSynthError, SynthPagesStep
from shop_arena.gen.data_synth.pages import synth_pages_from_identity
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


def _stub_response(handles: tuple[str, ...] = ("about", "contact", "faq")) -> str:
    return json.dumps(
        [
            {
                "handle": handle,
                "title": handle.replace("-", " ").title(),
                "body_html": f"<p>{handle}</p>",
            }
            for handle in handles
        ],
    )


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


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# synth_pages_from_identity
# --------------------------------------------------------------------------- #


def test_synth_pages_calls_llm_once_and_validates() -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    pages = synth_pages_from_identity(
        identity=_IDENTITY,
        capabilities=_CAPABILITIES,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert [p.handle for p in pages] == ["about", "contact", "faq"]
    assert all(isinstance(p, Page) for p in pages)


def test_synth_pages_strips_code_fence() -> None:
    fenced = "```json\n" + _stub_response() + "\n```"
    completer = _StubCompleter(responses=[fenced])
    pages = synth_pages_from_identity(
        identity=_IDENTITY,
        capabilities=_CAPABILITIES,
        completer=cast(LLMCompleter, completer),
    )
    assert [p.handle for p in pages] == ["about", "contact", "faq"]


def test_synth_pages_rejects_empty_response() -> None:
    completer = _StubCompleter(responses=[""])
    with pytest.raises(StageSynthError, match="empty response"):
        synth_pages_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_pages_rejects_empty_array() -> None:
    completer = _StubCompleter(responses=["[]"])
    with pytest.raises(StageSynthError, match="empty pages array"):
        synth_pages_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_pages_rejects_object_response() -> None:
    completer = _StubCompleter(responses=["{}"])
    with pytest.raises(StageSynthError, match="JSON array"):
        synth_pages_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_pages_rejects_duplicate_handles() -> None:
    completer = _StubCompleter(responses=[_stub_response(("about", "contact", "about"))])
    with pytest.raises(StageSynthError, match="duplicate page handle"):
        synth_pages_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_pages_rejects_missing_field() -> None:
    """A page lacking ``body_html`` fails the :class:`Page` schema."""
    bad = json.dumps([{"handle": "about", "title": "About"}])
    completer = _StubCompleter(responses=[bad])
    with pytest.raises(StageSynthError, match="Page schema validation"):
        synth_pages_from_identity(
            identity=_IDENTITY,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


# --------------------------------------------------------------------------- #
# SynthPagesStep
# --------------------------------------------------------------------------- #


def test_step_metadata_for_multi_seed() -> None:
    step = SynthPagesStep(manual_step_ids=("merge_capabilities", "merge_manual_prose"))
    assert step.id == "synth_pages"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "pages.json"]
    assert step.depends_on == [
        "synth_identity",
        "merge_capabilities",
        "merge_manual_prose",
    ]
    assert step.version == 1


def test_step_metadata_for_single_seed() -> None:
    step = SynthPagesStep(manual_step_ids=("copy_seed_manual",))
    assert step.depends_on == ["synth_identity", "copy_seed_manual"]


def test_step_metadata_listing_branch() -> None:
    step = SynthPagesStep()
    assert step.depends_on == ["synth_identity"]


def test_step_run_writes_stage_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthPagesStep(manual_step_ids=("copy_seed_manual",))
    step.run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "pages.json").read_text(encoding="utf-8"),
    )
    assert isinstance(cached, list)
    assert [Page.model_validate(entry).handle for entry in cached] == [
        "about",
        "contact",
        "faq",
    ]


def test_step_run_is_deterministic(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    response = _stub_response()

    def _run() -> bytes:
        completer = _StubCompleter(responses=[response])
        ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
        step = SynthPagesStep(manual_step_ids=("copy_seed_manual",))
        step.run(ctx)
        return (out_dir / ".shop_gen" / "stage_cache" / "pages.json").read_bytes()

    assert _run() == _run()


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthPagesStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_identity(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Only capabilities is materialised; identity.json is missing.
    manual_dir = out_dir / "manual"
    manual_dir.mkdir()
    (manual_dir / "capabilities.json").write_text(
        json.dumps(_CAPABILITIES) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthPagesStep(manual_step_ids=("copy_seed_manual",))
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
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthPagesStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match="capabilities"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.4 wires ``synth_pages`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_pages" in grouped["data_synth"]
