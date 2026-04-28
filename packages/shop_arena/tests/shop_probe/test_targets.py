"""Tests for `shop_probe.targets` (T1.2 acceptance — spec §5.2).

Covers:

* JSON / dict round-trip for ``Target`` and ``Cohort``.
* Unknown-field rejection (``extra="forbid"``).
* The ``pair_id`` / ``kind`` invariant from spec §5.2.
* Pair-level kind + pair_id consistency.
* Cohort-level cross-pair uniqueness and unpaired-kind invariant.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shop_probe.targets import Cohort, Pair, Target

# --------------------------------------------------------------------------- #
# Target — round-trip + unknown-field rejection
# --------------------------------------------------------------------------- #


def test_target_round_trip_sandbox() -> None:
    raw = {
        "label": "sandbox/hardware_run123",
        "base_url": "http://localhost:4000",
        "kind": "sandbox",
        "pair_id": "pair_hardware",
        "notes": "calibrated 2026-01-15",
    }
    target = Target.model_validate(raw)
    assert target.model_dump() == raw
    # JSON round-trip too — confirms no exotic default coercion.
    assert Target.model_validate_json(target.model_dump_json()) == target


def test_target_round_trip_real_unpaired_optional_notes() -> None:
    raw = {
        "label": "real/aloyoga",
        "base_url": "https://aloyoga.com",
        "kind": "real_unpaired",
    }
    target = Target.model_validate(raw)
    assert target.pair_id is None
    assert target.notes is None


def test_target_rejects_unknown_field() -> None:
    raw = {
        "label": "source/hardware",
        "base_url": "https://hardware.shopify.com",
        "kind": "source",
        "pair_id": "pair_hardware",
        "extra_field": "nope",
    }
    with pytest.raises(ValidationError, match="extra_field"):
        Target.model_validate(raw)


def test_target_rejects_unknown_kind() -> None:
    raw = {
        "label": "weird",
        "base_url": "https://example.com",
        "kind": "bogus",
        "pair_id": None,
    }
    with pytest.raises(ValidationError):
        Target.model_validate(raw)


# --------------------------------------------------------------------------- #
# Target — pair_id / kind invariant (spec §5.2)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["sandbox", "source"])
def test_target_requires_pair_id_when_kind_is_paired(kind: str) -> None:
    with pytest.raises(ValidationError, match="pair_id is required"):
        Target.model_validate(
            {
                "label": f"{kind}/hardware",
                "base_url": "http://localhost",
                "kind": kind,
                "pair_id": None,
            }
        )


@pytest.mark.parametrize("kind", ["sandbox", "source"])
def test_target_rejects_empty_pair_id_when_kind_is_paired(kind: str) -> None:
    with pytest.raises(ValidationError):
        Target.model_validate(
            {
                "label": f"{kind}/hardware",
                "base_url": "http://localhost",
                "kind": kind,
                "pair_id": "",
            }
        )


def test_target_rejects_pair_id_when_kind_is_real_unpaired() -> None:
    with pytest.raises(ValidationError, match="pair_id must be None"):
        Target.model_validate(
            {
                "label": "real/aloyoga",
                "base_url": "https://aloyoga.com",
                "kind": "real_unpaired",
                "pair_id": "pair_aloyoga",
            }
        )


# --------------------------------------------------------------------------- #
# Pair — kind + pair_id consistency
# --------------------------------------------------------------------------- #


def _source(pair_id: str = "pair_hardware") -> Target:
    return Target(
        label="source/hardware",
        base_url="https://hardware.shopify.com",
        kind="source",
        pair_id=pair_id,
    )


def _sandbox(pair_id: str = "pair_hardware") -> Target:
    return Target(
        label="sandbox/hardware",
        base_url="http://localhost:4000",
        kind="sandbox",
        pair_id=pair_id,
    )


def test_pair_accepts_matched_members() -> None:
    pair = Pair(id="pair_hardware", source=_source(), sandbox=_sandbox())
    # Round-trip via dump / validate keeps us honest about defaults.
    assert Pair.model_validate(pair.model_dump()) == pair


def test_pair_rejects_mismatched_source_kind() -> None:
    with pytest.raises(ValidationError, match=r"source\.kind must be 'source'"):
        Pair(
            id="pair_hardware",
            source=_sandbox(),  # wrong kind
            sandbox=_sandbox(),
        )


def test_pair_rejects_mismatched_sandbox_kind() -> None:
    with pytest.raises(ValidationError, match=r"sandbox\.kind must be 'sandbox'"):
        Pair(
            id="pair_hardware",
            source=_source(),
            sandbox=_source(),  # wrong kind
        )


def test_pair_rejects_pair_id_disagreement_on_source() -> None:
    with pytest.raises(ValidationError, match=r"source\.pair_id must equal id"):
        Pair(
            id="pair_hardware",
            source=_source(pair_id="pair_other"),
            sandbox=_sandbox(),
        )


def test_pair_rejects_pair_id_disagreement_on_sandbox() -> None:
    with pytest.raises(ValidationError, match=r"sandbox\.pair_id must equal id"):
        Pair(
            id="pair_hardware",
            source=_source(),
            sandbox=_sandbox(pair_id="pair_other"),
        )


# --------------------------------------------------------------------------- #
# Cohort — round-trip + cross-pair invariants
# --------------------------------------------------------------------------- #


def test_cohort_round_trip_matches_spec_section_8_2() -> None:
    raw = {
        "version": "0.1",
        "pairs": [
            {
                "id": "pair_hardware",
                "source": {
                    "label": "source/hardware",
                    "base_url": "https://hardware.shopify.com",
                    "kind": "source",
                    "pair_id": "pair_hardware",
                    "notes": None,
                },
                "sandbox": {
                    "label": "sandbox/hardware",
                    "base_url": "http://localhost:4000",
                    "kind": "sandbox",
                    "pair_id": "pair_hardware",
                    "notes": None,
                },
            }
        ],
        "real_unpaired": [
            {
                "label": "real/TBD_1",
                "base_url": "https://tbd1.example.com",
                "kind": "real_unpaired",
                "pair_id": None,
                "notes": None,
            }
        ],
    }
    cohort = Cohort.model_validate(raw)
    # Pydantic dumps `tuple[...]` as Python tuples; compare via JSON, which
    # is the canonical wire format and normalises sequences to lists.
    assert json.loads(cohort.model_dump_json()) == raw
    assert Cohort.model_validate_json(cohort.model_dump_json()) == cohort


def test_cohort_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="oops"):
        Cohort.model_validate({"version": "0.1", "oops": True})


def test_cohort_rejects_duplicate_pair_id() -> None:
    pair_a = Pair(id="pair_hardware", source=_source(), sandbox=_sandbox())
    pair_b = Pair(id="pair_hardware", source=_source(), sandbox=_sandbox())
    with pytest.raises(ValidationError, match="duplicate pair id"):
        Cohort(version="0.1", pairs=(pair_a, pair_b))


def test_cohort_accepts_empty_pairs_and_real_unpaired() -> None:
    cohort = Cohort(version="0.1")
    assert cohort.pairs == ()
    assert cohort.real_unpaired == ()


def test_cohort_real_unpaired_kind_is_validated_by_target() -> None:
    # A `Target` with kind != "real_unpaired" cannot be constructed without
    # a pair_id, and one with a pair_id is rejected by the model-level
    # validator. Together this means real_unpaired entries cannot smuggle
    # the wrong kind through the Cohort, which is what spec §5.2 requires.
    with pytest.raises(ValidationError):
        Cohort.model_validate(
            {
                "version": "0.1",
                "real_unpaired": [
                    {
                        "label": "real/oops",
                        "base_url": "https://oops.example.com",
                        "kind": "source",  # wrong kind for real_unpaired slot
                        "pair_id": "pair_oops",
                    }
                ],
            }
        )
