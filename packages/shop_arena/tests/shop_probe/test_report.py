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
    LIKERT_DIMENSIONS,
    BrowserMeta,
    CategoryScore,
    EvidenceRef,
    JudgeCall,
    JudgeModelPin,
    LikertCall,
    LikertDistribution,
    ProbeReport,
    ProbeResult,
    aggregate_likert_distributions,
)
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders — kept close to spec §5.6 examples so the tests double as
# documentation of the schema's wire format.
# --------------------------------------------------------------------------- #

_SANDBOX_TARGET: Target = Target(
    label="sandbox/1_run123",
    base_url="http://localhost:4000",
    kind="sandbox",
    pair_id="pair_1",
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


def _judge_model_pin() -> JudgeModelPin:
    return JudgeModelPin(
        provider="openai",
        model="gpt-5",
        model_version="gpt-5-2025-09-01",
        temperature=0.0,
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
        "judge_model": _judge_model_pin(),
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


# --------------------------------------------------------------------------- #
# JudgeModelPin (T4.6 — spec §5.5 step 5 + guardrails).
# --------------------------------------------------------------------------- #


def test_judge_model_pin_json_round_trip() -> None:
    pin = _judge_model_pin()
    assert JudgeModelPin.model_validate_json(pin.model_dump_json()) == pin


def test_judge_model_pin_rejects_unknown_field() -> None:
    payload = _judge_model_pin().model_dump()
    payload["top_p"] = 0.9
    with pytest.raises(ValidationError, match="top_p"):
        JudgeModelPin.model_validate(payload)


def test_judge_model_pin_is_frozen() -> None:
    pin = _judge_model_pin()
    with pytest.raises(ValidationError):
        pin.model = "gpt-4"  # type: ignore[misc]


def test_judge_model_pin_rejects_negative_temperature() -> None:
    with pytest.raises(ValidationError):
        JudgeModelPin(
            provider="openai",
            model="gpt-5",
            model_version="gpt-5-2025-09-01",
            temperature=-0.1,
        )


def test_judge_model_pin_accepts_v1_default_temperature_zero() -> None:
    pin = JudgeModelPin(
        provider="openai",
        model="gpt-5",
        model_version="gpt-5-2025-09-01",
        temperature=0.0,
    )
    assert pin.temperature == 0.0


def test_probe_report_with_judge_calls_requires_judge_model_pin() -> None:
    """Spec §5.5 guardrails: a report carrying axis-C calls must pin the model."""
    with pytest.raises(ValidationError, match="judge_model"):
        _probe_report(judge_model=None)


def test_probe_report_axis_a_only_run_omits_judge_model_pin() -> None:
    """Axis-A/B-only runs may carry no judge calls and no model pin."""
    report = _probe_report(judge_calls=(), judge_model=None)
    assert report.judge_calls == ()
    assert report.judge_model is None
    assert ProbeReport.model_validate_json(report.model_dump_json()) == report


def test_probe_report_pins_judge_model_in_header() -> None:
    """T4.6 check: pin assertions in report header."""
    report = _probe_report()
    assert report.judge_model is not None
    assert report.judge_model.provider == "openai"
    assert report.judge_model.model == "gpt-5"
    assert report.judge_model.temperature == 0.0
    payload = json.loads(report.model_dump_json())
    assert payload["judge_model"]["model"] == "gpt-5"
    assert payload["judge_model"]["temperature"] == 0.0


# --------------------------------------------------------------------------- #
# Likert quality dimensions (T7.2 — spec §5.9, §7 M7).
# --------------------------------------------------------------------------- #


def _likert_call(
    *,
    target_label: str = "sandbox/hardware_run123",
    visual_coherence: int = 4,
    copy_realism: int = 3,
    error_plausibility: int = 5,
) -> LikertCall:
    return LikertCall(
        task_id="t01_filter_open_pdp",
        target_label=target_label,
        visual_coherence=visual_coherence,
        copy_realism=copy_realism,
        error_plausibility=error_plausibility,
        evidence_cited=True,
        prompt_hash=_PROMPT_HASH,
        response_text='{"ratings": {}}',
    )


def test_likert_call_json_round_trip() -> None:
    call = _likert_call()
    assert LikertCall.model_validate_json(call.model_dump_json()) == call


def test_likert_call_score_returns_per_dimension_value() -> None:
    call = _likert_call(visual_coherence=4, copy_realism=3, error_plausibility=5)
    assert call.score("visual_coherence") == 4  # noqa: PLR2004
    assert call.score("copy_realism") == 3  # noqa: PLR2004
    assert call.score("error_plausibility") == 5  # noqa: PLR2004


def test_likert_call_rejects_unknown_field() -> None:
    payload = _likert_call().model_dump()
    payload["comment"] = "oops"  # not in the schema
    with pytest.raises(ValidationError, match="comment"):
        LikertCall.model_validate(payload)


@pytest.mark.parametrize("score", [0, 6, -1, 100])
def test_likert_call_rejects_score_outside_range(score: int) -> None:
    with pytest.raises(ValidationError):
        LikertCall(
            task_id="t",
            target_label="sandbox/x",
            visual_coherence=score,
            copy_realism=3,
            error_plausibility=3,
            evidence_cited=True,
            prompt_hash=_PROMPT_HASH,
            response_text="",
        )


def test_likert_call_rejects_non_hex_prompt_hash() -> None:
    with pytest.raises(ValidationError):
        LikertCall(
            task_id="t",
            target_label="sandbox/x",
            visual_coherence=3,
            copy_realism=3,
            error_plausibility=3,
            evidence_cited=True,
            prompt_hash="not-a-hash",
            response_text="",
        )


def test_likert_distribution_empty_round_trip() -> None:
    dist = LikertDistribution(dimension="visual_coherence", n_calls=0, counts={}, mean=None)
    assert LikertDistribution.model_validate_json(dist.model_dump_json()) == dist


def test_likert_distribution_rejects_non_zero_mean_when_empty() -> None:
    with pytest.raises(ValidationError, match="n_calls == 0"):
        LikertDistribution(dimension="visual_coherence", n_calls=0, counts={}, mean=3.0)


def test_likert_distribution_rejects_missing_mean_when_non_empty() -> None:
    with pytest.raises(ValidationError, match="n_calls > 0"):
        LikertDistribution(dimension="visual_coherence", n_calls=2, counts={3: 2}, mean=None)


def test_likert_distribution_rejects_counts_sum_mismatch() -> None:
    with pytest.raises(ValidationError, match="counts sum"):
        LikertDistribution(dimension="visual_coherence", n_calls=3, counts={3: 1, 4: 1}, mean=3.5)


def test_likert_distribution_rejects_score_outside_one_to_five() -> None:
    with pytest.raises(ValidationError, match="invalid score key"):
        LikertDistribution(dimension="visual_coherence", n_calls=1, counts={6: 1}, mean=5.0)


def test_aggregate_likert_distributions_returns_one_per_dimension() -> None:
    calls = (
        _likert_call(visual_coherence=5, copy_realism=4, error_plausibility=3),
        _likert_call(visual_coherence=4, copy_realism=4, error_plausibility=2),
    )
    distributions = aggregate_likert_distributions(calls)
    assert tuple(d.dimension for d in distributions) == LIKERT_DIMENSIONS
    by_dim = {d.dimension: d for d in distributions}
    assert by_dim["visual_coherence"].n_calls == 2  # noqa: PLR2004
    assert by_dim["visual_coherence"].counts == {4: 1, 5: 1}
    assert by_dim["visual_coherence"].mean == 4.5  # noqa: PLR2004
    assert by_dim["copy_realism"].counts == {4: 2}
    assert by_dim["copy_realism"].mean == 4.0  # noqa: PLR2004
    assert by_dim["error_plausibility"].counts == {2: 1, 3: 1}
    assert by_dim["error_plausibility"].mean == 2.5  # noqa: PLR2004


def test_aggregate_likert_distributions_handles_empty_input() -> None:
    distributions = aggregate_likert_distributions(())
    assert tuple(d.dimension for d in distributions) == LIKERT_DIMENSIONS
    for d in distributions:
        assert d.n_calls == 0
        assert d.counts == {}
        assert d.mean is None


def test_probe_report_with_likert_calls_round_trip() -> None:
    call = _likert_call()
    distributions = aggregate_likert_distributions((call,))
    report = _probe_report(
        likert_calls=(call,),
        likert_distributions=distributions,
    )
    assert report.likert_calls == (call,)
    assert tuple(d.dimension for d in report.likert_distributions) == LIKERT_DIMENSIONS
    assert ProbeReport.model_validate_json(report.model_dump_json()) == report


def test_probe_report_with_likert_calls_requires_judge_model_pin() -> None:
    """Spec §5.5 guardrails extend to the v1.1 Likert judge."""
    call = _likert_call()
    distributions = aggregate_likert_distributions((call,))
    with pytest.raises(ValidationError, match="judge_model"):
        _probe_report(
            judge_calls=(),
            judge_model=None,
            likert_calls=(call,),
            likert_distributions=distributions,
        )


def test_probe_report_with_likert_calls_requires_distributions() -> None:
    call = _likert_call()
    with pytest.raises(ValidationError, match="likert_distributions"):
        _probe_report(
            likert_calls=(call,),
            likert_distributions=(),
        )


def test_probe_report_likert_distributions_must_cover_all_dimensions() -> None:
    call = _likert_call()
    only_one = (
        LikertDistribution(
            dimension="visual_coherence",
            n_calls=1,
            counts={call.visual_coherence: 1},
            mean=float(call.visual_coherence),
        ),
    )
    with pytest.raises(ValidationError, match="missing dimension"):
        _probe_report(
            likert_calls=(call,),
            likert_distributions=only_one,
        )


def test_probe_report_likert_distributions_n_calls_must_match() -> None:
    call = _likert_call()
    # Build distributions claiming 7 contributing calls when only 1 was passed.
    bad = tuple(
        LikertDistribution(
            dimension=dim,
            n_calls=7,
            counts={call.score(dim): 7},
            mean=float(call.score(dim)),
        )
        for dim in LIKERT_DIMENSIONS
    )
    with pytest.raises(ValidationError, match="disagrees with len\\(likert_calls\\)"):
        _probe_report(
            likert_calls=(call,),
            likert_distributions=bad,
        )
