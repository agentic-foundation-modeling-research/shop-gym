"""Tests for `shop_probe.report`.

Covers:

* JSON round-trip for ``EvidenceRef``, ``BrowserMeta``, ``ProbeResult``,
  ``CategoryScore``, and ``ProbeReport``.
* ``extra="forbid"`` unknown-field rejection on every schema.
* Numeric range constraints (coverage ∈ [0, 1], duration ≥ 0,
  judge_cost_usd ≥ 0).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    EvidenceRef,
    ProbeReport,
    ProbeResult,
)
from shop_probe.targets import Target

_SANDBOX_TARGET: Target = Target(
    name="shop_alpha",
    base_url="http://localhost:4000",
    label="sandbox",
)
_RUBRIC_HASH: str = "a" * 64
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _evidence_ref() -> EvidenceRef:
    return EvidenceRef(
        kind="screenshot",
        path="evidence/site_shell_001/header.png",
        selector="header[role='banner']",
    )


def _probe_result() -> ProbeResult:
    return ProbeResult(
        id="site_shell.header.sticky",
        passed=True,
        evidence=(_evidence_ref(),),
        notes=None,
        duration_ms=412,
    )


def _category_score() -> CategoryScore:
    return CategoryScore(
        category="site_shell",
        weight_passed=12.0,
        weight_total=15.0,
        coverage=0.8,
    )


def _report(**overrides: object) -> ProbeReport:
    base: dict[str, object] = {
        "target": _SANDBOX_TARGET,
        "rubric_version": "v2",
        "rubric_hash": _RUBRIC_HASH,
        "runner_version": "0.0.0",
        "runtime": _browser_meta(),
        "timestamp": _TIMESTAMP,
        "probe_results": (_probe_result(),),
        "categories": (_category_score(),),
        "coverage_core": 0.8,
        "coverage_modern": 0.0,
        "coverage_advanced": 0.0,
        "coverage_weighted": 0.5,
    }
    base.update(overrides)
    return ProbeReport.model_validate(base)


# --------------------------------------------------------------------------- #
# Round-trip on every schema.
# --------------------------------------------------------------------------- #


def test_evidence_ref_round_trip() -> None:
    e = _evidence_ref()
    assert EvidenceRef.model_validate_json(e.model_dump_json()) == e


def test_browser_meta_round_trip() -> None:
    b = _browser_meta()
    assert BrowserMeta.model_validate_json(b.model_dump_json()) == b


def test_probe_result_round_trip() -> None:
    r = _probe_result()
    assert ProbeResult.model_validate_json(r.model_dump_json()) == r


def test_category_score_round_trip() -> None:
    c = _category_score()
    assert CategoryScore.model_validate_json(c.model_dump_json()) == c


def test_probe_report_round_trip() -> None:
    r = _report()
    assert ProbeReport.model_validate_json(r.model_dump_json()) == r


# --------------------------------------------------------------------------- #
# extra="forbid".
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("model_name", "extra_field"),
    [
        ("evidence_ref", "size_kb"),
        ("browser_meta", "device_pixel_ratio"),
        ("probe_result", "evidence_count"),
        ("category_score", "weight_skipped"),
    ],
)
def test_extra_forbid_on_inner_schemas(model_name: str, extra_field: str) -> None:
    factories = {
        "evidence_ref": _evidence_ref,
        "browser_meta": _browser_meta,
        "probe_result": _probe_result,
        "category_score": _category_score,
    }
    factory = factories[model_name]
    raw = json.loads(factory().model_dump_json())
    raw[extra_field] = "anything"
    with pytest.raises(ValidationError, match=extra_field):
        type(factory()).model_validate(raw)


def test_probe_report_rejects_unknown_field() -> None:
    raw = json.loads(_report().model_dump_json())
    raw["unknown"] = 1
    with pytest.raises(ValidationError, match="unknown"):
        ProbeReport.model_validate(raw)


# --------------------------------------------------------------------------- #
# Numeric range / pattern constraints.
# --------------------------------------------------------------------------- #


def test_probe_result_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        ProbeResult(id="x", passed=True, duration_ms=-1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("coverage_core", 1.5),
        ("coverage_modern", -0.1),
        ("coverage_advanced", 2.0),
        ("coverage_weighted", -1.0),
    ],
)
def test_probe_report_rejects_out_of_range_coverage(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _report(**{field: value})


# --------------------------------------------------------------------------- #
# Capture-judge cost side-channel fields.
# --------------------------------------------------------------------------- #


def test_probe_result_carries_judge_cost_fields() -> None:
    """Capture-judge results round-trip with judge cost / model."""
    r = ProbeResult(
        id="homepage.hero.has_value_proposition",
        passed=True,
        evidence=(_evidence_ref(),),
        notes=None,
        duration_ms=2_412,
        judge_cost_usd=0.0123,
        judge_model="claude-haiku-4-5",
    )
    assert ProbeResult.model_validate_json(r.model_dump_json()) == r


def test_probe_result_judge_cost_fields_default_to_none() -> None:
    """Deterministic probes leave judge fields ``None``."""
    r = _probe_result()
    assert r.judge_cost_usd is None
    assert r.judge_model is None


def test_probe_result_rejects_negative_judge_cost() -> None:
    with pytest.raises(ValidationError):
        ProbeResult(id="x", passed=True, duration_ms=1, judge_cost_usd=-0.01)


def test_probe_report_carries_total_judge_cost_rollup() -> None:
    r = _report(total_judge_cost_usd=0.08)
    payload = json.loads(r.model_dump_json())
    assert payload["total_judge_cost_usd"] == pytest.approx(0.08)
    assert ProbeReport.model_validate(payload) == r


def test_probe_report_total_judge_cost_rollup_defaults_to_none() -> None:
    r = _report()
    assert r.total_judge_cost_usd is None


def test_probe_report_rejects_negative_total_judge_cost() -> None:
    with pytest.raises(ValidationError):
        _report(total_judge_cost_usd=-0.5)
