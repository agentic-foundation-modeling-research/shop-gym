"""Tests for `shop_probe.surface.metrics` (T2.1 acceptance — spec §5.4).

Covers:

* JSON / dict round-trip for ``SurfaceMetrics``.
* ``extra="forbid"`` unknown-field rejection.
* Non-negativity constraints on every count and aggregate (spec §5.4
  treats these as descriptive counts and ratios so negative values are
  invalid by construction).
* Frozen-instance immutability — ``ProbeReport`` is the public contract
  the paper figures read from, so silent mutation is rejected.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shop_probe.surface.metrics import SurfaceMetrics


def _payload(**overrides: object) -> dict[str, object]:
    """Return a valid ``SurfaceMetrics`` payload with optional overrides."""
    base: dict[str, object] = {
        "distinct_templates": 5,
        "routes_crawled": 38,
        "interactables_per_template_median": 24.0,
        "interactables_per_template_p95": 71.0,
        "forms_total": 4,
        "form_fields_total": 19,
        "catalog_products": 20,
        "catalog_collections": 8,
        "catalog_variants": 53,
        "filter_x_sort_state_space": 96,
        "median_dom_kb_gz": 42.5,
        "accessibility_nodes_per_template_median": 318.0,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Round-trip — every field survives dump → load unchanged.
# --------------------------------------------------------------------------- #


def test_surface_metrics_round_trip_full() -> None:
    raw = _payload()
    metrics = SurfaceMetrics.model_validate(raw)
    assert metrics.model_dump() == raw
    assert SurfaceMetrics.model_validate_json(metrics.model_dump_json()) == metrics


def test_surface_metrics_json_round_trip_preserves_numeric_types() -> None:
    metrics = SurfaceMetrics.model_validate(_payload())
    payload = json.loads(metrics.model_dump_json())
    # Integer fields stay JSON-integer; float fields stay JSON-number. This
    # matters for the surface bar chart (spec §8.4 row 3) which reads counts
    # as integers and ratios as floats.
    assert isinstance(payload["distinct_templates"], int)
    assert isinstance(payload["routes_crawled"], int)
    assert isinstance(payload["forms_total"], int)
    assert isinstance(payload["form_fields_total"], int)
    assert isinstance(payload["catalog_products"], int)
    assert isinstance(payload["catalog_collections"], int)
    assert isinstance(payload["catalog_variants"], int)
    assert isinstance(payload["filter_x_sort_state_space"], int)
    assert isinstance(payload["interactables_per_template_median"], float)
    assert isinstance(payload["interactables_per_template_p95"], float)
    assert isinstance(payload["median_dom_kb_gz"], float)
    assert isinstance(payload["accessibility_nodes_per_template_median"], float)


def test_surface_metrics_accepts_zero_floor_for_every_field() -> None:
    # Every metric must accept 0 — a freshly-deployed sandbox with no
    # catalog yet is a legitimate state during axis-B sanity checks
    # (spec §7 M2 gate).
    zero_payload: dict[str, object] = dict.fromkeys(_payload(), 0)
    metrics = SurfaceMetrics.model_validate(zero_payload)
    assert metrics.distinct_templates == 0
    assert metrics.median_dom_kb_gz == 0.0


# --------------------------------------------------------------------------- #
# Schema shape — the 12 fields from spec §5.4 are present, no more, no less.
# --------------------------------------------------------------------------- #


def test_surface_metrics_field_set_matches_spec_section_5_4() -> None:
    expected = {
        "distinct_templates",
        "routes_crawled",
        "interactables_per_template_median",
        "interactables_per_template_p95",
        "forms_total",
        "form_fields_total",
        "catalog_products",
        "catalog_collections",
        "catalog_variants",
        "filter_x_sort_state_space",
        "median_dom_kb_gz",
        "accessibility_nodes_per_template_median",
    }
    assert set(SurfaceMetrics.model_fields.keys()) == expected


# --------------------------------------------------------------------------- #
# Unknown-field rejection — closed schema rejects typos.
# --------------------------------------------------------------------------- #


def test_surface_metrics_rejects_unknown_field() -> None:
    raw = _payload()
    raw["bundle_size_kb"] = 320  # performance metrics are out of v1 (spec §5.9)
    with pytest.raises(ValidationError, match="bundle_size_kb"):
        SurfaceMetrics.model_validate(raw)


def test_surface_metrics_rejects_renamed_field() -> None:
    raw = _payload()
    # Common typo: ``forms`` instead of ``forms_total``.
    raw["forms"] = raw.pop("forms_total")
    with pytest.raises(ValidationError, match="forms"):
        SurfaceMetrics.model_validate(raw)


# --------------------------------------------------------------------------- #
# Non-negativity constraints — counts and aggregates are ≥ 0 by construction.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    [
        "distinct_templates",
        "routes_crawled",
        "forms_total",
        "form_fields_total",
        "catalog_products",
        "catalog_collections",
        "catalog_variants",
        "filter_x_sort_state_space",
    ],
)
def test_surface_metrics_rejects_negative_int_field(field: str) -> None:
    with pytest.raises(ValidationError):
        SurfaceMetrics.model_validate(_payload(**{field: -1}))


@pytest.mark.parametrize(
    "field",
    [
        "interactables_per_template_median",
        "interactables_per_template_p95",
        "median_dom_kb_gz",
        "accessibility_nodes_per_template_median",
    ],
)
def test_surface_metrics_rejects_negative_float_field(field: str) -> None:
    with pytest.raises(ValidationError):
        SurfaceMetrics.model_validate(_payload(**{field: -0.1}))


# --------------------------------------------------------------------------- #
# Frozen instances — silent mutation is rejected.
# --------------------------------------------------------------------------- #


def test_surface_metrics_is_frozen() -> None:
    metrics = SurfaceMetrics.model_validate(_payload())
    with pytest.raises(ValidationError):
        metrics.distinct_templates = 99  # type: ignore[misc]
