"""Smoke tests for the v1.0 rubric: schema validation + content hashing.

Covers the shipped ``shop_arena/probe/rubric/rubric.yaml`` plus a few targeted
in-memory cases against :class:`shop_arena.probe.rubric.RubricEntry`'s
per-kind contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_arena.probe.rubric import (
    Rubric,
    RubricEntry,
    RubricLoadError,
    compute_content_hash,
    load_rubric,
    load_rubric_bytes,
)

_PACKAGED_RUBRIC: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "shop_arena"
    / "probe"
    / "rubric"
    / "rubric.yaml"
)


def test_packaged_rubric_loads_and_hashes() -> None:
    rubric = load_rubric(_PACKAGED_RUBRIC)
    assert isinstance(rubric, Rubric)
    assert rubric.version == "1.0"
    expected = compute_content_hash(_PACKAGED_RUBRIC.read_bytes())
    assert rubric.content_hash == expected
    # 1 obs.shape + 5 info_slots + 1 action.space + 5 control_slots + 5 transitions = 17.
    assert len(rubric.entries) == 17


def test_packaged_rubric_families_balanced() -> None:
    rubric = load_rubric(_PACKAGED_RUBRIC)
    families = {entry.family for entry in rubric.entries}
    assert families == {"observation", "action", "transition"}
    kinds_per_family = {
        "observation": {"shape", "info_slot"},
        "action": {"space", "control_slot"},
        "transition": {"scripted"},
    }
    for entry in rubric.entries:
        assert entry.kind in kinds_per_family[entry.family]


def test_rubric_entry_rejects_unknown_kind_for_family() -> None:
    with pytest.raises(ValueError, match="requires kind in"):
        RubricEntry(
            id="bad", family="observation", kind="scripted", page_type="cart"
        )


def test_rubric_entry_scripted_rejects_modalities() -> None:
    with pytest.raises(ValueError, match="must not set 'modalities'"):
        RubricEntry(
            id="bad",
            family="transition",
            kind="scripted",
            page_type="cart",
            modalities=("a11y",),
            script="cart_checkout",
            expected_change="url_changes_to_checkout",
        )


def test_rubric_entry_info_slot_requires_prompt() -> None:
    with pytest.raises(ValueError, match="requires 'prompt'"):
        RubricEntry(
            id="bad",
            family="observation",
            kind="info_slot",
            page_type="product",
            modalities=("a11y",),
        )


def test_load_rubric_bytes_rejects_duplicate_id() -> None:
    yaml = b"""
version: "1.0"
entries:
  - id: dup
    family: transition
    kind: scripted
    page_type: cart
    script: cart_checkout
    expected_change: url_changes_to_checkout
  - id: dup
    family: transition
    kind: scripted
    page_type: cart
    script: cart_checkout
    expected_change: url_changes_to_checkout
"""
    with pytest.raises(RubricLoadError, match="duplicate entry id"):
        load_rubric_bytes(yaml)
