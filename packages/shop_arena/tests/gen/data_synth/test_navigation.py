"""Unit tests for :mod:`shop_arena.gen.data_synth.navigation`.

Covers the T3.8 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``synth_navigation`` makes exactly one LLM call producing a JSON
  object validated against
  :class:`~shop_arena.gen.data_synth.schema.Navigation`.
* Both ``main-menu`` and ``footer`` are required.
* Every collection handle is reachable from ``main-menu``.
* The cached payload at ``.shop_gen/stage_cache/navigation.json`` is
  pydantic-validated.
* The step requires ``ctx.runtime`` and surfaces a clear error when it
  is ``None`` or when an upstream cache is missing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from harness.runtimes import LLMCompleter
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.data_synth import (
    Navigation,
    StageSynthError,
    SynthNavigationStep,
)
from shop_arena.gen.data_synth.navigation import synth_navigation_from_collections
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


_COLLECTIONS: list[dict[str, object]] = [
    {
        "title": "Outerwear",
        "handle": "outerwear",
        "description": "Jackets and coats.",
        "sort_order": "manual",
        "target_product_count": 5,
    },
    {
        "title": "Kitchen Tools",
        "handle": "kitchen-tools",
        "description": "Cookware and utensils.",
        "sort_order": "manual",
        "target_product_count": 5,
    },
]

_PAGES: list[dict[str, object]] = [
    {"handle": "about", "title": "About", "body_html": "<p>About</p>"},
    {"handle": "contact", "title": "Contact", "body_html": "<p>Contact</p>"},
]

_CAPABILITIES: dict[str, object] = {
    "version": "0.1",
    "shop": {
        "descriptor": "boutique outdoor storefront",
        "category": "outdoor",
        "tone": ["rugged", "warm"],
    },
    "info_pages": ["about", "contact"],
}


def _stub_response(
    *,
    main_menu_collections: tuple[str, ...] = ("outerwear", "kitchen-tools"),
    footer_pages: tuple[str, ...] = ("about", "contact"),
) -> str:
    main_items = [
        {
            "title": handle.replace("-", " ").title(),
            "url": f"/collections/{handle}",
            "type": "COLLECTION",
            "children": [],
        }
        for handle in main_menu_collections
    ]
    footer_items = [
        {
            "title": handle.title(),
            "url": f"/pages/{handle}",
            "type": "PAGE",
            "children": [],
        }
        for handle in footer_pages
    ]
    return json.dumps({"main-menu": main_items, "footer": footer_items})


def _materialise_workspace(out_dir: Path) -> None:
    """Lay out the upstream caches the step reads."""
    stage_cache = out_dir / ".shop_gen" / "stage_cache"
    stage_cache.mkdir(parents=True, exist_ok=True)
    (stage_cache / "collections.json").write_text(
        json.dumps(_COLLECTIONS, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (stage_cache / "pages.json").write_text(
        json.dumps(_PAGES, indent=2, sort_keys=True) + "\n",
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
# synth_navigation_from_collections
# --------------------------------------------------------------------------- #


def test_synth_navigation_calls_llm_once_and_validates() -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    nav = synth_navigation_from_collections(
        collections=_COLLECTIONS,
        pages=_PAGES,
        capabilities=_CAPABILITIES,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert isinstance(nav, Navigation)
    assert set(nav.root.keys()) == {"main-menu", "footer"}
    main_menu = nav.root["main-menu"]
    assert {item.url for item in main_menu} == {
        "/collections/outerwear",
        "/collections/kitchen-tools",
    }


def test_synth_navigation_strips_code_fence() -> None:
    fenced = "```json\n" + _stub_response() + "\n```"
    completer = _StubCompleter(responses=[fenced])
    nav = synth_navigation_from_collections(
        collections=_COLLECTIONS,
        pages=_PAGES,
        capabilities=_CAPABILITIES,
        completer=cast(LLMCompleter, completer),
    )
    assert set(nav.root.keys()) == {"main-menu", "footer"}


def test_synth_navigation_reaches_collections_through_grouping() -> None:
    """Collections nested under an HTTP grouping still count as reachable."""
    grouped = json.dumps(
        {
            "main-menu": [
                {
                    "title": "Shop",
                    "url": "/",
                    "type": "HTTP",
                    "children": [
                        {
                            "title": "Outerwear",
                            "url": "/collections/outerwear",
                            "type": "COLLECTION",
                            "children": [],
                        },
                        {
                            "title": "Kitchen Tools",
                            "url": "/collections/kitchen-tools",
                            "type": "COLLECTION",
                            "children": [],
                        },
                    ],
                },
            ],
            "footer": [
                {
                    "title": "About",
                    "url": "/pages/about",
                    "type": "PAGE",
                    "children": [],
                },
            ],
        },
    )
    completer = _StubCompleter(responses=[grouped])
    nav = synth_navigation_from_collections(
        collections=_COLLECTIONS,
        pages=_PAGES,
        capabilities=_CAPABILITIES,
        completer=cast(LLMCompleter, completer),
    )
    top = nav.root["main-menu"][0]
    assert top.type == "HTTP"
    assert {child.url for child in top.children} == {
        "/collections/outerwear",
        "/collections/kitchen-tools",
    }


def test_synth_navigation_rejects_missing_collection() -> None:
    """Spec/T3.8 check: every collection handle must be reachable from main-menu."""
    completer = _StubCompleter(
        responses=[_stub_response(main_menu_collections=("outerwear",))],
    )
    with pytest.raises(StageSynthError, match="missing collection handles"):
        synth_navigation_from_collections(
            collections=_COLLECTIONS,
            pages=_PAGES,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_navigation_rejects_missing_required_menu() -> None:
    only_main = json.dumps(
        {
            "main-menu": [
                {
                    "title": "Outerwear",
                    "url": "/collections/outerwear",
                    "type": "COLLECTION",
                    "children": [],
                },
                {
                    "title": "Kitchen Tools",
                    "url": "/collections/kitchen-tools",
                    "type": "COLLECTION",
                    "children": [],
                },
            ],
        },
    )
    completer = _StubCompleter(responses=[only_main])
    with pytest.raises(StageSynthError, match="missing required menu handles"):
        synth_navigation_from_collections(
            collections=_COLLECTIONS,
            pages=_PAGES,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_navigation_rejects_array_response() -> None:
    completer = _StubCompleter(responses=["[]"])
    with pytest.raises(StageSynthError, match="JSON object"):
        synth_navigation_from_collections(
            collections=_COLLECTIONS,
            pages=_PAGES,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_navigation_rejects_empty_response() -> None:
    completer = _StubCompleter(responses=[""])
    with pytest.raises(StageSynthError, match="empty response"):
        synth_navigation_from_collections(
            collections=_COLLECTIONS,
            pages=_PAGES,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_navigation_rejects_extra_field() -> None:
    """A nav-item with an unknown field fails the closed schema."""
    bad = json.dumps(
        {
            "main-menu": [
                {
                    "title": "Outerwear",
                    "url": "/collections/outerwear",
                    "type": "COLLECTION",
                    "children": [],
                    "icon": "jacket",
                },
                {
                    "title": "Kitchen Tools",
                    "url": "/collections/kitchen-tools",
                    "type": "COLLECTION",
                    "children": [],
                },
            ],
            "footer": [],
        },
    )
    completer = _StubCompleter(responses=[bad])
    with pytest.raises(StageSynthError, match="Navigation schema validation"):
        synth_navigation_from_collections(
            collections=_COLLECTIONS,
            pages=_PAGES,
            capabilities=_CAPABILITIES,
            completer=cast(LLMCompleter, completer),
        )


# --------------------------------------------------------------------------- #
# SynthNavigationStep
# --------------------------------------------------------------------------- #


def test_step_metadata_for_multi_seed() -> None:
    step = SynthNavigationStep(
        manual_step_ids=("merge_capabilities", "merge_manual_prose"),
    )
    assert step.id == "synth_navigation"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "navigation.json"]
    assert step.depends_on == [
        "synth_collections",
        "synth_pages",
        "merge_capabilities",
        "merge_manual_prose",
    ]
    assert step.version == 1


def test_step_metadata_for_single_seed() -> None:
    step = SynthNavigationStep(manual_step_ids=("copy_seed_manual",))
    assert step.depends_on == [
        "synth_collections",
        "synth_pages",
        "copy_seed_manual",
    ]


def test_step_metadata_listing_branch() -> None:
    step = SynthNavigationStep()
    assert step.depends_on == ["synth_collections", "synth_pages"]


def test_step_run_writes_stage_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )

    step = SynthNavigationStep(manual_step_ids=("copy_seed_manual",))
    step.run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "navigation.json").read_text(
            encoding="utf-8",
        ),
    )
    assert isinstance(cached, dict)
    assert set(cached.keys()) == {"main-menu", "footer"}
    nav = Navigation.model_validate(cached)
    main_menu_urls = {item.url for item in nav.root["main-menu"]}
    assert main_menu_urls == {
        "/collections/outerwear",
        "/collections/kitchen-tools",
    }


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
        step = SynthNavigationStep(manual_step_ids=("copy_seed_manual",))
        step.run(ctx)
        return (out_dir / ".shop_gen" / "stage_cache" / "navigation.json").read_bytes()

    assert _run() == _run()


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthNavigationStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_collections_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # pages + capabilities present, collections cache missing.
    stage_cache = out_dir / ".shop_gen" / "stage_cache"
    stage_cache.mkdir(parents=True)
    (stage_cache / "pages.json").write_text(
        json.dumps(_PAGES) + "\n",
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
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )
    step = SynthNavigationStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match="cached collections"):
        step.run(ctx)


def test_step_run_missing_pages_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stage_cache = out_dir / ".shop_gen" / "stage_cache"
    stage_cache.mkdir(parents=True)
    (stage_cache / "collections.json").write_text(
        json.dumps(_COLLECTIONS) + "\n",
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
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )
    step = SynthNavigationStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match="cached pages"):
        step.run(ctx)


def test_step_run_missing_capabilities(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stage_cache = out_dir / ".shop_gen" / "stage_cache"
    stage_cache.mkdir(parents=True)
    (stage_cache / "collections.json").write_text(
        json.dumps(_COLLECTIONS) + "\n",
        encoding="utf-8",
    )
    (stage_cache / "pages.json").write_text(
        json.dumps(_PAGES) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )
    step = SynthNavigationStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match="capabilities"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.8 wires ``synth_navigation`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_navigation" in grouped["data_synth"]
