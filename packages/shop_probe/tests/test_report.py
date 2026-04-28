"""Tests for `shop_probe.report` (T1.5 acceptance — spec §5.6).

Covers:

* JSON round-trip for ``EvidenceRef``, ``BrowserMeta``, ``ProbeResult``,
  ``CategoryScore``, ``JudgeCall``, and ``ProbeReport`` (the full closed
  schema including a nested ``Target`` and tuples of children).
* ``extra="forbid"`` unknown-field rejection on every schema in the
  module — this is the contract the paper figures read against, so a
  typo must fail validation rather than silently zero the field.
* The numeric range constraints from spec §5.6 (coverage ∈ [0, 1],
  duration ≥ 0, rerun_index ≥ 1, prompt_hash 64-hex).
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
    JudgeCall,
    ProbeReport,
    ProbeResult,
)
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders — kept close to spec §5.6 examples so the tests double as
# documentation of the schema's wire format.
# --------------------------------------------------------------------------- #

_SANDBOX_TARGET: Target = Target(
    label="sandbox/hardware_run123",
    base_url="http://localhost:4000",
    kind="sandbox",
    pair_id="pair_hardware",
)

_RUBRIC_HASH: str = "a" * 64
_PROMPT_HASH: str = "b" * 64
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


def _judge_call() -> JudgeCall:
    return JudgeCall(
        task_id="t01_filter_open_pdp",
        pair_label=("traj/A", "traj/B"),
        judge_pick="A",
        truth="B",
        swap_consistent=True,
        evidence_cited=True,
        confidence=0.72,
        prompt_hash=_PROMPT_HASH,
        response_text='{"pick": "A", "rationale": "..."}',
    )


def _probe_report(**overrides: object) -> ProbeReport:
    base: dict[str, object] = {
        "target": _SANDBOX_TARGET,
        "rubric_version": "v1",
        "rubric_hash": _RUBRIC_HASH,
        "runner_version": "0.0.0",
        "runtime": _browser_meta(),
        "timestamp": _TIMESTAMP,
        "probe_results": (_probe_result(),),
        "categories": (_category_score(),),
        "coverage_core": 0.85,
        "coverage_modern": 0.60,
        "coverage_advanced": 0.0,
        "coverage_weighted": 0.74,
        "judge_calls": (_judge_call(),),
        "rerun_index": 1,
        "flake_rate_per_probe": {"site_shell.header.sticky": 0.0},
    }
    base.update(overrides)
    return ProbeReport.model_validate(base)


# --------------------------------------------------------------------------- #
# JSON round-trip — every schema must survive dump → load unchanged.
# --------------------------------------------------------------------------- #


def test_evidence_ref_json_round_trip() -> None:
    ref = _evidence_ref()
    assert EvidenceRef.model_validate_json(ref.model_dump_json()) == ref


def test_evidence_ref_selector_optional() -> None:
    ref = EvidenceRef(kind="har", path="evidence/run.har")
    assert ref.selector is None
    assert EvidenceRef.model_validate_json(ref.model_dump_json()) == ref


def test_browser_meta_json_round_trip() -> None:
    meta = _browser_meta()
    # Tuples become 2-element JSON arrays on the wire; round-trip must coerce
    # back to a tuple, which is what `==` compares.
    payload = json.loads(meta.model_dump_json())
    assert payload["viewport"] == [1280, 800]
    assert BrowserMeta.model_validate_json(meta.model_dump_json()) == meta


def test_probe_result_json_round_trip_with_evidence() -> None:
    result = _probe_result()
    assert ProbeResult.model_validate_json(result.model_dump_json()) == result


def test_probe_result_passed_none_means_not_applicable() -> None:
    result = ProbeResult(
        id="i18n.locale_switcher",
        passed=None,
        notes="single-locale storefront",
        duration_ms=87,
    )
    assert result.passed is None
    assert result.evidence == ()
    assert ProbeResult.model_validate_json(result.model_dump_json()) == result


def test_category_score_json_round_trip() -> None:
    score = _category_score()
    assert CategoryScore.model_validate_json(score.model_dump_json()) == score


def test_judge_call_json_round_trip_preserves_pair_label_tuple() -> None:
    call = _judge_call()
    payload = json.loads(call.model_dump_json())
    assert payload["pair_label"] == ["traj/A", "traj/B"]
    assert JudgeCall.model_validate_json(call.model_dump_json()) == call


def test_probe_report_json_round_trip_full() -> None:
    report = _probe_report()
    assert ProbeReport.model_validate_json(report.model_dump_json()) == report


def test_probe_report_axis_a_only_run_has_empty_judge_calls() -> None:
    report = _probe_report(judge_calls=())
    assert report.judge_calls == ()
    assert ProbeReport.model_validate_json(report.model_dump_json()) == report


def test_probe_report_dict_round_trip_normalises_via_json() -> None:
    # Pydantic dumps tuples as Python tuples in `model_dump`; the canonical
    # wire format is JSON, where tuples become lists. We assert both round
    # trips so reviewers can re-load reports from disk.
    report = _probe_report()
    assert ProbeReport.model_validate(report.model_dump()) == report


# --------------------------------------------------------------------------- #
# Unknown-field rejection — closed schemas reject typos on every model.
# --------------------------------------------------------------------------- #


def test_evidence_ref_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra_field"):
        EvidenceRef.model_validate(
            {"kind": "screenshot", "path": "x.png", "extra_field": "nope"},
        )


def test_browser_meta_rejects_unknown_field() -> None:
    payload = _browser_meta().model_dump()
    payload["unexpected"] = "nope"
    with pytest.raises(ValidationError, match="unexpected"):
        BrowserMeta.model_validate(payload)


def test_probe_result_rejects_unknown_field() -> None:
    payload = _probe_result().model_dump()
    payload["score"] = 0.9  # not in the schema
    with pytest.raises(ValidationError, match="score"):
        ProbeResult.model_validate(payload)


def test_category_score_rejects_unknown_field() -> None:
    payload = _category_score().model_dump()
    payload["foo"] = "bar"
    with pytest.raises(ValidationError, match="foo"):
        CategoryScore.model_validate(payload)


def test_judge_call_rejects_unknown_field() -> None:
    payload = _judge_call().model_dump()
    payload["model_name"] = "gpt-5"  # belongs in BrowserMeta-equivalent, not here
    with pytest.raises(ValidationError, match="model_name"):
        JudgeCall.model_validate(payload)


def test_probe_report_rejects_unknown_field() -> None:
    payload = json.loads(_probe_report().model_dump_json())
    payload["coverage_total"] = 0.74  # typo for coverage_weighted
    with pytest.raises(ValidationError, match="coverage_total"):
        ProbeReport.model_validate(payload)


# --------------------------------------------------------------------------- #
# Numeric / format constraints from spec §5.6.
# --------------------------------------------------------------------------- #


def test_probe_result_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        ProbeResult(
            id="x",
            passed=True,
            duration_ms=-1,
        )


def test_category_score_rejects_coverage_above_one() -> None:
    with pytest.raises(ValidationError):
        CategoryScore(
            category="cart",
            weight_passed=2.0,
            weight_total=1.0,
            coverage=2.0,
        )


def test_judge_call_rejects_confidence_above_one() -> None:
    with pytest.raises(ValidationError):
        JudgeCall(
            task_id="t",
            pair_label=("a", "b"),
            judge_pick="A",
            truth="A",
            swap_consistent=True,
            evidence_cited=True,
            confidence=1.5,
            prompt_hash=_PROMPT_HASH,
            response_text="",
        )


def test_judge_call_rejects_non_hex_prompt_hash() -> None:
    with pytest.raises(ValidationError):
        JudgeCall(
            task_id="t",
            pair_label=("a", "b"),
            judge_pick="A",
            truth="A",
            swap_consistent=True,
            evidence_cited=True,
            confidence=0.5,
            prompt_hash="not-a-hash",
            response_text="",
        )


def test_probe_report_rejects_rerun_index_below_one() -> None:
    with pytest.raises(ValidationError):
        _probe_report(rerun_index=0)


def test_probe_report_rejects_coverage_above_one() -> None:
    with pytest.raises(ValidationError):
        _probe_report(coverage_weighted=1.2)


def test_probe_report_rejects_non_hex_rubric_hash() -> None:
    with pytest.raises(ValidationError):
        _probe_report(rubric_hash="not-a-real-hash")
