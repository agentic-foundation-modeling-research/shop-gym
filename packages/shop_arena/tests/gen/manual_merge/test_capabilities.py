"""Unit tests for :mod:`shop_arena.gen.manual_merge.capabilities`.

Covers the T2.1 requirements from
``docs/impl/shop_gen_implementation.md``:

* Each per-area rule from spec §9.2 — booleans, lists, scalar majority,
  layout/style enums, ``shop.tone`` cap-3, ``homepage.section_types``
  cap-by-max-section-count, ``site_shell.nav_depth`` max,
  ``shop.descriptor`` LLM merge.
* Tie-breaking paths exercised through a stub :class:`LLMCompleter`.
* Schema enforcement — seeds with extra fields fail; the merged
  document validates against the closed
  :class:`shop_arena.explore.capabilities.Capabilities` schema.
* End-to-end :class:`MergeCapabilitiesStep` writes
  ``manual/capabilities.json`` and the conflict sidecar.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shop_arena.explore.capabilities import Capabilities, CapabilitiesValidationError
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.manual_merge.capabilities import (
    MergeCapabilitiesStep,
    MergeConflict,
    merge_capabilities_seeds,
)
from shop_arena.gen.steps.base import FileInput, Step, StepContext

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@dataclass
class _StubCompleter:
    """Recording :class:`LLMCompleter` that returns canned responses.

    Each call dequeues one response from ``responses``; an empty queue
    raises so tests fail loudly when the merge calls the LLM more
    times than expected.
    """

    responses: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM was called more times than expected")
        return self.responses.pop(0)


def _write_seed(seed_dir: Path, payload: dict[str, object]) -> Path:
    """Write a ``capabilities.json`` under the canonical seed layout."""
    artifact = seed_dir / "artifact"
    artifact.mkdir(parents=True, exist_ok=True)
    path = artifact / "capabilities.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _seed_payload(**overrides: object) -> dict[str, object]:
    """Return a minimal valid capabilities payload merged with ``overrides``."""
    base: dict[str, object] = {
        "version": "0.1",
        "shop": {
            "descriptor": "minimalist storefront",
            "category": "fashion",
            "currency": "USD",
            "tone": ["clean"],
        },
        "site_shell": {"nav_depth": 1},
        "homepage": {"section_types": [], "section_count": 0},
        "collection": {"filters": [], "sort": []},
        "product": {"variant_selectors": []},
        "search": {"predictive_types": []},
        "info_pages_present": [],
    }
    for key, value in overrides.items():
        base[key] = value
    return base


# --------------------------------------------------------------------------- #
# Schema-coverage meta-test
# --------------------------------------------------------------------------- #


def _enumerate_capability_leaves(model_cls: type) -> set[str]:
    """Collect every dotted leaf path of the closed capabilities schema."""
    leaves: set[str] = set()

    def _walk(cls: type, prefix: str) -> None:
        fields = getattr(cls, "model_fields", None)
        if fields is None:
            if prefix:
                leaves.add(prefix)
            return
        for name, info in fields.items():
            full = f"{prefix}.{name}" if prefix else name
            annotation = info.annotation
            origin = getattr(annotation, "__origin__", None)
            args = getattr(annotation, "__args__", ())
            inner = next(
                (arg for arg in args if isinstance(arg, type) and hasattr(arg, "model_fields")),
                None,
            )
            if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
                _walk(annotation, full)
            elif inner is not None and origin is not list:
                _walk(inner, full)
            else:
                leaves.add(full)

    _walk(model_cls, "")
    return leaves


def test_every_capabilities_leaf_has_a_merge_rule() -> None:
    """Every Capabilities leaf must have a §9.2 dispatch entry.

    Catches schema additions that forget to update the rule table.
    The merged document must include ``version`` (set to ``"0.1"`` by
    construction), so it is not part of the rule table.
    """
    from shop_arena.gen.manual_merge.capabilities import _RULES  # noqa: PLC0415

    leaves = _enumerate_capability_leaves(Capabilities) - {"version"}
    assert leaves == set(_RULES.keys())


# --------------------------------------------------------------------------- #
# Boolean union (spec §9.2 ``*.has_*``)
# --------------------------------------------------------------------------- #


def test_bool_union_propagates_true_and_records_conflict(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(cart={"has_promo_input": True}),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(cart={"has_promo_input": False}),
    )
    merged, conflicts = merge_capabilities_seeds([seed_a, seed_b])
    assert merged.cart.has_promo_input is True
    promo_conflicts = [c for c in conflicts if c.path == "cart.has_promo_input"]
    assert len(promo_conflicts) == 1
    assert promo_conflicts[0].rule == "bool_union"
    assert promo_conflicts[0].chosen_value is True


def test_bool_union_unanimous_no_conflict(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(product={"has_reviews": True, "variant_selectors": []}),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(product={"has_reviews": True, "variant_selectors": []}),
    )
    merged, conflicts = merge_capabilities_seeds([seed_a, seed_b])
    assert merged.product.has_reviews is True
    assert all(c.path != "product.has_reviews" for c in conflicts)


# --------------------------------------------------------------------------- #
# List union (spec §9.2 ``*.<list>``)
# --------------------------------------------------------------------------- #


def test_list_union_dedups_and_preserves_seed_order(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(collection={"filters": ["availability", "price"], "sort": []}),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(collection={"filters": ["price", "color", "availability"], "sort": []}),
    )
    merged, _ = merge_capabilities_seeds([seed_a, seed_b])
    # Seed-order prefix: seed_a wins for "availability", "price"; seed_b adds "color".
    assert merged.collection.filters == ["availability", "price", "color"]


def test_tone_capped_at_three(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            shop={
                "descriptor": "lab",
                "category": "fashion",
                "currency": "USD",
                "tone": ["clean", "modern"],
            }
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            shop={
                "descriptor": "lab",
                "category": "fashion",
                "currency": "USD",
                "tone": ["minimal", "premium", "warm"],
            }
        ),
    )
    merged, _ = merge_capabilities_seeds([seed_a, seed_b])
    assert merged.shop.tone == ["clean", "modern", "minimal"]


def test_section_types_capped_at_max_section_count(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            homepage={
                "section_types": ["hero", "grid", "press", "newsletter", "footer"],
                "section_count": 4,
            }
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            homepage={
                "section_types": ["hero", "video", "newsletter"],
                "section_count": 2,
            }
        ),
    )
    merged, _ = merge_capabilities_seeds([seed_a, seed_b])
    # max(4, 2) = 4 → cap union at 4.
    assert merged.homepage.section_types == ["hero", "grid", "press", "newsletter"]


# --------------------------------------------------------------------------- #
# Scalar majority + first-seed tiebreak
# --------------------------------------------------------------------------- #


def test_scalar_majority_clear_winner_records_conflict(tmp_path: Path) -> None:
    seeds = [
        _write_seed(
            tmp_path / "a",
            _seed_payload(
                shop={
                    "descriptor": "lab",
                    "category": "fashion",
                    "currency": "USD",
                    "tone": ["clean"],
                }
            ),
        ),
        _write_seed(
            tmp_path / "b",
            _seed_payload(
                shop={
                    "descriptor": "lab",
                    "category": "fashion",
                    "currency": "USD",
                    "tone": ["clean"],
                }
            ),
        ),
        _write_seed(
            tmp_path / "c",
            _seed_payload(
                shop={
                    "descriptor": "lab",
                    "category": "fashion",
                    "currency": "EUR",
                    "tone": ["clean"],
                }
            ),
        ),
    ]
    merged, conflicts = merge_capabilities_seeds(seeds)
    assert merged.shop.currency == "USD"
    [conflict] = [c for c in conflicts if c.path == "shop.currency"]
    assert conflict.rule == "scalar_majority"
    assert conflict.tiebreak is None
    assert conflict.chosen_value == "USD"


def test_scalar_majority_tie_falls_through_to_first_seed(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            shop={
                "descriptor": "lab",
                "category": "fashion",
                "currency": "USD",
                "tone": ["clean"],
            }
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            shop={
                "descriptor": "lab",
                "category": "fashion",
                "currency": "EUR",
                "tone": ["clean"],
            }
        ),
    )
    merged, conflicts = merge_capabilities_seeds([seed_a, seed_b])
    assert merged.shop.currency == "USD"
    [conflict] = [c for c in conflicts if c.path == "shop.currency"]
    assert conflict.tiebreak == "first_seed"


# --------------------------------------------------------------------------- #
# nav_depth max (spec §9.2)
# --------------------------------------------------------------------------- #


def test_nav_depth_takes_max_across_seeds(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(site_shell={"nav_depth": 1}),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(site_shell={"nav_depth": 3}),
    )
    seed_c = _write_seed(
        tmp_path / "c",
        _seed_payload(site_shell={"nav_depth": 2}),
    )
    merged, conflicts = merge_capabilities_seeds([seed_a, seed_b, seed_c])
    assert merged.site_shell.nav_depth == 3  # noqa: PLR2004
    [conflict] = [c for c in conflicts if c.path == "site_shell.nav_depth"]
    assert conflict.tiebreak == "max"


# --------------------------------------------------------------------------- #
# Layout / style enum (spec §9.2 ``*_layout`` / ``*_style``)
# --------------------------------------------------------------------------- #


def test_layout_style_enum_majority_no_llm_call(tmp_path: Path) -> None:
    seeds = [
        _write_seed(
            tmp_path / "a",
            _seed_payload(
                collection={
                    "layout": "grid",
                    "filters": [],
                    "sort": [],
                }
            ),
        ),
        _write_seed(
            tmp_path / "b",
            _seed_payload(
                collection={
                    "layout": "grid",
                    "filters": [],
                    "sort": [],
                }
            ),
        ),
        _write_seed(
            tmp_path / "c",
            _seed_payload(
                collection={
                    "layout": "list",
                    "filters": [],
                    "sort": [],
                }
            ),
        ),
    ]
    completer = _StubCompleter(responses=[])
    merged, _ = merge_capabilities_seeds(seeds, completer=completer)
    assert merged.collection.layout == "grid"
    assert completer.prompts == []


def test_layout_style_enum_tie_uses_llm_choice(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            shop={
                "descriptor": "lab",
                "category": "fashion",
                "currency": "USD",
                "tone": ["sleek"],
            },
            collection={"layout": "grid", "filters": [], "sort": []},
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            shop={
                "descriptor": "lab",
                "category": "fashion",
                "currency": "USD",
                "tone": ["sleek"],
            },
            collection={"layout": "list", "filters": [], "sort": []},
        ),
    )
    completer = _StubCompleter(responses=["list"])
    merged, conflicts = merge_capabilities_seeds([seed_a, seed_b], completer=completer)
    assert merged.collection.layout == "list"
    [conflict] = [c for c in conflicts if c.path == "collection.layout"]
    assert conflict.tiebreak == "llm"
    # Prompt embeds the candidates and the merged descriptor.
    [prompt] = completer.prompts
    assert "grid" in prompt
    assert "list" in prompt
    assert "lab" in prompt


def test_layout_style_enum_tie_falls_back_when_llm_returns_garbage(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            collection={"layout": "grid", "filters": [], "sort": []},
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            collection={"layout": "list", "filters": [], "sort": []},
        ),
    )
    completer = _StubCompleter(responses=["something_unrelated"])
    merged, conflicts = merge_capabilities_seeds([seed_a, seed_b], completer=completer)
    # Fallback to first-seed (seed_a's "grid").
    assert merged.collection.layout == "grid"
    [conflict] = [c for c in conflicts if c.path == "collection.layout"]
    assert conflict.tiebreak == "first_seed"


# --------------------------------------------------------------------------- #
# shop.descriptor LLM merge (spec §9.2)
# --------------------------------------------------------------------------- #


def test_descriptor_unanimous_skips_llm(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            shop={
                "descriptor": "minimalist storefront",
                "category": "fashion",
                "currency": "USD",
                "tone": ["clean"],
            }
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            shop={
                "descriptor": "minimalist storefront",
                "category": "fashion",
                "currency": "USD",
                "tone": ["clean"],
            }
        ),
    )
    completer = _StubCompleter(responses=[])
    merged, _ = merge_capabilities_seeds([seed_a, seed_b], completer=completer)
    assert merged.shop.descriptor == "minimalist storefront"
    assert completer.prompts == []


def test_descriptor_distinct_invokes_llm_with_tone_context(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            shop={
                "descriptor": "minimalist storefront",
                "category": "fashion",
                "currency": "USD",
                "tone": ["clean", "muted"],
            }
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            shop={
                "descriptor": "premium kitchenware brand",
                "category": "kitchen",
                "currency": "USD",
                "tone": ["bold"],
            }
        ),
    )
    completer = _StubCompleter(responses=["premium minimalist home goods storefront"])
    merged, conflicts = merge_capabilities_seeds([seed_a, seed_b], completer=completer)
    assert merged.shop.descriptor == "premium minimalist home goods storefront"
    [conflict] = [c for c in conflicts if c.path == "shop.descriptor"]
    assert conflict.tiebreak == "llm"
    [prompt] = completer.prompts
    # Tone tags are merged before the descriptor call so the prompt
    # contains the fully merged tone list.
    assert "clean" in prompt
    assert "muted" in prompt
    assert "bold" in prompt


def test_descriptor_disagreement_without_completer_raises(tmp_path: Path) -> None:
    seed_a = _write_seed(
        tmp_path / "a",
        _seed_payload(
            shop={
                "descriptor": "minimalist storefront",
                "category": "fashion",
                "currency": "USD",
                "tone": ["clean"],
            }
        ),
    )
    seed_b = _write_seed(
        tmp_path / "b",
        _seed_payload(
            shop={
                "descriptor": "premium kitchenware brand",
                "category": "fashion",
                "currency": "USD",
                "tone": ["bold"],
            }
        ),
    )
    with pytest.raises(ValueError, match="LLMCompleter"):
        merge_capabilities_seeds([seed_a, seed_b], completer=None)


# --------------------------------------------------------------------------- #
# Schema enforcement
# --------------------------------------------------------------------------- #


def test_seed_with_unknown_field_rejected(tmp_path: Path) -> None:
    payload = _seed_payload()
    payload["unknown_extra_field"] = "boom"
    seed = _write_seed(tmp_path / "a", payload)
    with pytest.raises(CapabilitiesValidationError):
        merge_capabilities_seeds([seed])


def test_missing_seed_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        merge_capabilities_seeds([tmp_path / "missing.json"])


def test_empty_seed_paths_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        merge_capabilities_seeds([])


def test_merged_document_validates_against_closed_schema(tmp_path: Path) -> None:
    seed_a = _write_seed(tmp_path / "a", _seed_payload())
    seed_b = _write_seed(tmp_path / "b", _seed_payload())
    merged, _ = merge_capabilities_seeds([seed_a, seed_b])
    # Round-trip the model_dump back through the schema to confirm.
    Capabilities.model_validate(merged.model_dump(mode="json"))


# --------------------------------------------------------------------------- #
# MergeCapabilitiesStep (the Step contract)
# --------------------------------------------------------------------------- #


def test_step_satisfies_step_protocol(tmp_path: Path) -> None:
    step = MergeCapabilitiesStep(seed_capabilities_paths=[tmp_path / "x.json"])
    assert isinstance(step, Step)
    assert step.id == "merge_capabilities"
    assert step.phase == "manual_merge"
    assert step.depends_on == []
    assert step.outputs == [
        Path("manual") / "capabilities.json",
        Path(".shop_gen") / "stage_cache" / "capability_conflicts.json",
    ]
    assert step.inputs == [FileInput(path=tmp_path / "x.json")]


def test_step_run_writes_capabilities_and_conflicts(tmp_path: Path) -> None:
    seed_a_dir = tmp_path / "seed_a"
    seed_b_dir = tmp_path / "seed_b"
    seed_a = _write_seed(
        seed_a_dir,
        _seed_payload(
            cart={"has_promo_input": True},
            site_shell={"nav_depth": 2},
        ),
    )
    seed_b = _write_seed(
        seed_b_dir,
        _seed_payload(
            cart={"has_promo_input": False},
            site_shell={"nav_depth": 5},
        ),
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed_a_dir, seed_b_dir], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    step = MergeCapabilitiesStep(seed_capabilities_paths=[seed_a, seed_b])
    step.run(ctx)

    caps_path = out_dir / "manual" / "capabilities.json"
    conflicts_path = out_dir / ".shop_gen" / "stage_cache" / "capability_conflicts.json"
    assert caps_path.is_file()
    assert conflicts_path.is_file()

    # Capabilities round-trip cleanly through the closed schema.
    merged = Capabilities.model_validate_json(caps_path.read_text(encoding="utf-8"))
    assert merged.cart.has_promo_input is True
    assert merged.site_shell.nav_depth == 5  # noqa: PLR2004

    # Conflicts sidecar is a JSON array of MergeConflict records.
    raw_conflicts = json.loads(conflicts_path.read_text(encoding="utf-8"))
    paths = {item["path"] for item in raw_conflicts}
    assert {"cart.has_promo_input", "site_shell.nav_depth"} <= paths
    # Each entry round-trips through the pydantic model.
    for item in raw_conflicts:
        MergeConflict.model_validate(item)


def test_step_run_is_deterministic_across_invocations(tmp_path: Path) -> None:
    """Two runs with the same seeds produce byte-identical outputs."""
    seed_a_dir = tmp_path / "seed_a"
    seed_b_dir = tmp_path / "seed_b"
    seed_a = _write_seed(seed_a_dir, _seed_payload(cart={"has_promo_input": True}))
    seed_b = _write_seed(seed_b_dir, _seed_payload(cart={"has_promo_input": False}))

    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"
    out_a.mkdir()
    out_b.mkdir()
    cfg = ShopGenConfig(seeds=[seed_a_dir, seed_b_dir], out_dir=out_a)
    ctx_a = StepContext(config=cfg, out_dir=out_a)
    ctx_b = StepContext(config=cfg, out_dir=out_b)

    step_one = MergeCapabilitiesStep(seed_capabilities_paths=[seed_a, seed_b])
    step_two = MergeCapabilitiesStep(seed_capabilities_paths=[seed_a, seed_b])
    step_one.run(ctx_a)
    step_two.run(ctx_b)

    a_bytes = (out_a / "manual" / "capabilities.json").read_bytes()
    b_bytes = (out_b / "manual" / "capabilities.json").read_bytes()
    assert a_bytes == b_bytes


# --------------------------------------------------------------------------- #
# Misc coverage
# --------------------------------------------------------------------------- #


def test_single_seed_passes_through_without_llm(tmp_path: Path) -> None:
    """A 1-seed merge is a copy: no conflicts, no LLM calls."""
    seed = _write_seed(tmp_path / "a", _seed_payload())
    completer = _StubCompleter(responses=[])
    merged, conflicts = merge_capabilities_seeds([seed], completer=completer)
    assert conflicts == []
    assert completer.prompts == []
    assert merged.shop.descriptor == "minimalist storefront"


def _conflict_paths(conflicts: Iterable[MergeConflict]) -> set[str]:
    return {conflict.path for conflict in conflicts}


def test_unanimous_seeds_record_no_conflicts(tmp_path: Path) -> None:
    payload = _seed_payload()
    seed_a = _write_seed(tmp_path / "a", payload)
    seed_b = _write_seed(tmp_path / "b", payload)
    _, conflicts = merge_capabilities_seeds([seed_a, seed_b])
    assert _conflict_paths(conflicts) == set()
