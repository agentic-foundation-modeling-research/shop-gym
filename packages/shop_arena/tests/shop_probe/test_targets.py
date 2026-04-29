"""Tests for `shop_probe.targets` (web_probe_patch.md).

Covers:

* JSON / dict round-trip for ``Target`` and ``Bench``.
* Unknown-field rejection (``extra="forbid"``).
* Group/label invariant (``label`` must agree with the group the target
  appears in).
* Bench-level uniqueness of ``name`` across the union of groups.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shop_probe.targets import Bench, Target

# --------------------------------------------------------------------------- #
# Target — round-trip + unknown-field rejection
# --------------------------------------------------------------------------- #


def test_target_round_trip_sandbox() -> None:
    raw = {
        "name": "shop_alpha",
        "base_url": "http://localhost:4000",
        "label": "sandbox",
        "notes": "deployed 2026-01-15",
    }
    target = Target.model_validate(raw)
    assert target.model_dump() == raw
    assert Target.model_validate_json(target.model_dump_json()) == target


def test_target_round_trip_real_no_notes() -> None:
    raw = {
        "name": "real_a",
        "base_url": "https://real-1.example.invalid",
        "label": "real",
    }
    target = Target.model_validate(raw)
    assert target.notes is None


def test_target_rejects_unknown_field() -> None:
    raw = {
        "name": "shop_alpha",
        "base_url": "https://example.invalid",
        "label": "sandbox",
        "extra_field": "nope",
    }
    with pytest.raises(ValidationError, match="extra_field"):
        Target.model_validate(raw)


def test_target_rejects_unknown_label() -> None:
    raw = {
        "name": "weird",
        "base_url": "https://example.invalid",
        "label": "source",
    }
    with pytest.raises(ValidationError):
        Target.model_validate(raw)


def test_target_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        Target.model_validate(
            {"name": "", "base_url": "https://example.invalid", "label": "sandbox"}
        )


# --------------------------------------------------------------------------- #
# Bench — round-trip + cross-group invariants
# --------------------------------------------------------------------------- #


def _sandbox(name: str = "shop_alpha") -> Target:
    return Target(name=name, base_url="http://localhost:4000", label="sandbox")


def _real(name: str = "real_a") -> Target:
    return Target(name=name, base_url="https://real-a.example.invalid", label="real")


def test_bench_round_trip() -> None:
    raw = {
        "version": "0.1",
        "sandboxes": [
            {
                "name": "shop_alpha",
                "base_url": "http://localhost:4000",
                "label": "sandbox",
                "notes": None,
            }
        ],
        "reals": [
            {
                "name": "real_a",
                "base_url": "https://real-a.example.invalid",
                "label": "real",
                "notes": None,
            }
        ],
    }
    bench = Bench.model_validate(raw)
    assert json.loads(bench.model_dump_json()) == raw
    assert Bench.model_validate_json(bench.model_dump_json()) == bench


def test_bench_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="oops"):
        Bench.model_validate({"version": "0.1", "oops": True})


def test_bench_accepts_empty_groups() -> None:
    bench = Bench(version="0.1")
    assert bench.sandboxes == ()
    assert bench.reals == ()


def test_bench_rejects_sandbox_with_real_label() -> None:
    raw = {
        "version": "0.1",
        "sandboxes": [
            {
                "name": "shop_alpha",
                "base_url": "http://localhost",
                "label": "real",
            }
        ],
    }
    with pytest.raises(ValidationError, match="expected 'sandbox'"):
        Bench.model_validate(raw)


def test_bench_rejects_real_with_sandbox_label() -> None:
    raw = {
        "version": "0.1",
        "reals": [
            {
                "name": "real_a",
                "base_url": "https://real.example.invalid",
                "label": "sandbox",
            }
        ],
    }
    with pytest.raises(ValidationError, match="expected 'real'"):
        Bench.model_validate(raw)


def test_bench_rejects_duplicate_name_within_group() -> None:
    with pytest.raises(ValidationError, match="duplicate target name"):
        Bench(version="0.1", sandboxes=(_sandbox("a"), _sandbox("a")))


def test_bench_rejects_duplicate_name_across_groups() -> None:
    with pytest.raises(ValidationError, match="duplicate target name"):
        Bench(
            version="0.1",
            sandboxes=(_sandbox("shared"),),
            reals=(_real("shared"),),
        )
