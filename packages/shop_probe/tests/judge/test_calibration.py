"""Tests for ``shop_probe.judge.calibration`` (T7.3 — spec §5.9 + §7 M7).

The T7.3 gate from ``docs/impl/web_probe_implementation.md`` reads:

    Check: Spearman ρ between human and LLM judge reported per dimension.

These tests pin Spearman ρ math and the pairing semantics so reviewers can
trust the v1.1 human-judge calibration number end-to-end:

* :class:`HumanLikertCall` schema — closed contract; ``extra="forbid"``;
  per-dimension scores are ``[1, 5]``; ``rater_id`` is required.
* :class:`DimensionCalibration` schema — ``spearman_rho`` is ``None`` iff
  ``n_matched < 2``.
* :class:`HumanCalibration` schema — closed contract; correlations cover
  every :data:`LikertDimension` exactly once in declaration order;
  per-dimension ``n_matched`` agrees with the cohort-level value.
* :func:`compute_human_calibration` headline math:
  perfect agreement, perfect inversion, partial agreement (worked
  example with ties), constant-score → ``None``, single-pair → ``None``,
  empty input → all ``None``.
* Pairing semantics — calls match by ``(task_id, target_label)``;
  unmatched rows are ignored; LLM ``evidence_cited=False`` rows on the
  matched sample are dropped per spec §5.5 guardrails and counted into
  ``dropped``.
* Error paths — duplicate keys on either side raise; mixed
  ``rater_id`` rows raise; ``rater_id`` mismatch with the explicit
  argument raises.
* JSON round-trip — :class:`HumanCalibration` reproduces from its
  serialized form so the v1.1 supplement table can read versioned
  reports.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from shop_probe.judge.calibration import (
    DimensionCalibration,
    HumanCalibration,
    HumanLikertCall,
    compute_human_calibration,
)
from shop_probe.report import LIKERT_DIMENSIONS, JudgeModelPin, LikertCall, LikertDimension

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_PROMPT_HASH: str = "d" * 64
_RATER_ID: str = "human_avg"


def _gpt5_pin() -> JudgeModelPin:
    return JudgeModelPin(
        provider="openai",
        model="gpt-5",
        model_version="gpt-5-2025-09-01",
        temperature=0.0,
    )


def _human(
    *,
    task_id: str = "t01_filter_open_pdp",
    target_label: str = "sandbox/hardware",
    rater_id: str = _RATER_ID,
    visual_coherence: int = 3,
    copy_realism: int = 3,
    error_plausibility: int = 3,
) -> HumanLikertCall:
    return HumanLikertCall(
        task_id=task_id,
        target_label=target_label,
        rater_id=rater_id,
        visual_coherence=visual_coherence,
        copy_realism=copy_realism,
        error_plausibility=error_plausibility,
    )


def _llm(
    *,
    task_id: str = "t01_filter_open_pdp",
    target_label: str = "sandbox/hardware",
    visual_coherence: int = 3,
    copy_realism: int = 3,
    error_plausibility: int = 3,
    evidence_cited: bool = True,
) -> LikertCall:
    return LikertCall(
        task_id=task_id,
        target_label=target_label,
        visual_coherence=visual_coherence,
        copy_realism=copy_realism,
        error_plausibility=error_plausibility,
        evidence_cited=evidence_cited,
        prompt_hash=_PROMPT_HASH,
        response_text='{"ratings": {...}}',
    )


# --------------------------------------------------------------------------- #
# Schema — HumanLikertCall.
# --------------------------------------------------------------------------- #


def test_human_likert_call_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        HumanLikertCall.model_validate(
            {
                "task_id": "t1",
                "target_label": "sandbox/x",
                "rater_id": _RATER_ID,
                "visual_coherence": 3,
                "copy_realism": 3,
                "error_plausibility": 3,
                "unknown_field": "rejected",
            }
        )


def test_human_likert_call_score_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _human(visual_coherence=0)
    with pytest.raises(ValidationError):
        _human(visual_coherence=6)


def test_human_likert_call_rater_id_required() -> None:
    with pytest.raises(ValidationError):
        _human(rater_id="")


def test_human_likert_call_score_helper() -> None:
    """``score(dimension)`` returns the per-dimension field uniformly."""
    call = _human(visual_coherence=1, copy_realism=4, error_plausibility=5)
    assert call.score("visual_coherence") == 1
    assert call.score("copy_realism") == 4  # noqa: PLR2004 — pinned fixture value.
    assert call.score("error_plausibility") == 5  # noqa: PLR2004 — pinned fixture value.


# --------------------------------------------------------------------------- #
# Schema — DimensionCalibration.
# --------------------------------------------------------------------------- #


def test_dimension_calibration_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        DimensionCalibration.model_validate(
            {
                "dimension": "visual_coherence",
                "n_matched": 0,
                "spearman_rho": None,
                "unknown_field": "rejected",
            }
        )


def test_dimension_calibration_rejects_rho_with_too_few_pairs() -> None:
    """``spearman_rho`` must be ``None`` when ``n_matched < 2``."""
    with pytest.raises(ValidationError):
        DimensionCalibration(dimension="visual_coherence", n_matched=1, spearman_rho=0.0)


def test_dimension_calibration_rho_range() -> None:
    """Pydantic clamps ``spearman_rho`` to ``[-1, 1]``."""
    with pytest.raises(ValidationError):
        DimensionCalibration(dimension="visual_coherence", n_matched=4, spearman_rho=1.5)
    with pytest.raises(ValidationError):
        DimensionCalibration(dimension="visual_coherence", n_matched=4, spearman_rho=-1.5)


# --------------------------------------------------------------------------- #
# Schema — HumanCalibration.
# --------------------------------------------------------------------------- #


def _full_correlations(*, n_matched: int, rho: float | None) -> tuple[DimensionCalibration, ...]:
    return tuple(
        DimensionCalibration(dimension=d, n_matched=n_matched, spearman_rho=rho)
        for d in LIKERT_DIMENSIONS
    )


def test_human_calibration_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        HumanCalibration.model_validate(
            {
                "rater_id": _RATER_ID,
                "judge_model": _gpt5_pin().model_dump(),
                "n_matched": 0,
                "dropped": 0,
                "correlations": [
                    DimensionCalibration(dimension=d, n_matched=0, spearman_rho=None).model_dump()
                    for d in LIKERT_DIMENSIONS
                ],
                "unknown_field": "rejected",
            }
        )


def test_human_calibration_rejects_missing_dimension() -> None:
    """All three :data:`LikertDimension` literals must appear exactly once."""
    incomplete = (
        DimensionCalibration(dimension="visual_coherence", n_matched=4, spearman_rho=0.5),
        DimensionCalibration(dimension="copy_realism", n_matched=4, spearman_rho=0.5),
    )
    with pytest.raises(ValidationError):
        HumanCalibration(
            rater_id=_RATER_ID,
            judge_model=_gpt5_pin(),
            n_matched=4,
            dropped=0,
            correlations=incomplete,
        )


def test_human_calibration_rejects_dimension_out_of_order() -> None:
    """Correlations must list dimensions in declaration order."""
    swapped: tuple[LikertDimension, ...] = (
        "copy_realism",
        "visual_coherence",
        "error_plausibility",
    )
    correlations = tuple(
        DimensionCalibration(dimension=d, n_matched=4, spearman_rho=0.5) for d in swapped
    )
    with pytest.raises(ValidationError):
        HumanCalibration(
            rater_id=_RATER_ID,
            judge_model=_gpt5_pin(),
            n_matched=4,
            dropped=0,
            correlations=correlations,
        )


def test_human_calibration_rejects_n_matched_disagreement() -> None:
    """Per-dimension ``n_matched`` must equal the cohort-level value."""
    mixed = (
        DimensionCalibration(dimension="visual_coherence", n_matched=4, spearman_rho=0.5),
        DimensionCalibration(dimension="copy_realism", n_matched=3, spearman_rho=0.5),
        DimensionCalibration(dimension="error_plausibility", n_matched=4, spearman_rho=0.5),
    )
    with pytest.raises(ValidationError):
        HumanCalibration(
            rater_id=_RATER_ID,
            judge_model=_gpt5_pin(),
            n_matched=4,
            dropped=0,
            correlations=mixed,
        )


# --------------------------------------------------------------------------- #
# compute_human_calibration — math.
# --------------------------------------------------------------------------- #


def _pair(
    i: int,
    *,
    human_scores: tuple[int, int, int],
    llm_scores: tuple[int, int, int],
) -> tuple[HumanLikertCall, LikertCall]:
    h = _human(
        task_id=f"t{i}",
        target_label=f"label_{i}",
        visual_coherence=human_scores[0],
        copy_realism=human_scores[1],
        error_plausibility=human_scores[2],
    )
    m = _llm(
        task_id=f"t{i}",
        target_label=f"label_{i}",
        visual_coherence=llm_scores[0],
        copy_realism=llm_scores[1],
        error_plausibility=llm_scores[2],
    )
    return h, m


def test_perfect_agreement_is_one() -> None:
    """Identical paired scores on a multi-value sample → ρ = 1.0 per dimension."""
    pairs = [
        _pair(1, human_scores=(1, 5, 3), llm_scores=(1, 5, 3)),
        _pair(2, human_scores=(2, 4, 2), llm_scores=(2, 4, 2)),
        _pair(3, human_scores=(3, 3, 5), llm_scores=(3, 3, 5)),
        _pair(4, human_scores=(5, 1, 1), llm_scores=(5, 1, 1)),
    ]
    humans = [h for h, _ in pairs]
    llms = [m for _, m in pairs]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 4  # noqa: PLR2004 — 4 paired observations.
    assert result.dropped == 0
    for entry in result.correlations:
        assert entry.spearman_rho is not None
        assert math.isclose(entry.spearman_rho, 1.0)


def test_perfect_inversion_is_minus_one() -> None:
    """Reversed paired ranks on a multi-value sample → ρ = -1.0."""
    pairs = [
        _pair(1, human_scores=(1, 1, 1), llm_scores=(5, 5, 5)),
        _pair(2, human_scores=(2, 2, 2), llm_scores=(4, 4, 4)),
        _pair(3, human_scores=(4, 4, 4), llm_scores=(2, 2, 2)),
        _pair(4, human_scores=(5, 5, 5), llm_scores=(1, 1, 1)),
    ]
    humans = [h for h, _ in pairs]
    llms = [m for _, m in pairs]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 4  # noqa: PLR2004 — 4 paired observations.
    for entry in result.correlations:
        assert entry.spearman_rho is not None
        assert math.isclose(entry.spearman_rho, -1.0)


def test_partial_agreement_with_ties_matches_worked_example() -> None:
    """Worked example with Likert ties — fractional ranks pin a known ρ.

    Layout (one row per matched pair, ``visual_coherence`` only):

        ====   human   llm
        p1      1       2
        p2      2       3
        p3      3       3
        p4      4       4
        p5      5       5

    Fractional ranks:
      human  → [1, 2, 3, 4, 5]
      llm    → [1, 2.5, 2.5, 4, 5]

    Pearson on those rank vectors gives a pinned numerical ρ.
    """
    pairs = [
        _pair(1, human_scores=(1, 1, 1), llm_scores=(2, 2, 2)),
        _pair(2, human_scores=(2, 2, 2), llm_scores=(3, 3, 3)),
        _pair(3, human_scores=(3, 3, 3), llm_scores=(3, 3, 3)),
        _pair(4, human_scores=(4, 4, 4), llm_scores=(4, 4, 4)),
        _pair(5, human_scores=(5, 5, 5), llm_scores=(5, 5, 5)),
    ]
    humans = [h for h, _ in pairs]
    llms = [m for _, m in pairs]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 5  # noqa: PLR2004 — 5 paired observations.
    # Pearson on x=[1,2,3,4,5], y=[1, 2.5, 2.5, 4, 5]:
    # mean_x=3, mean_y=3, var_x=10, var_y=9.5,
    # cov = (-2)(-2) + (-1)(-0.5) + 0*(-0.5) + 1*1 + 2*2 = 4 + 0.5 + 0 + 1 + 4 = 9.5
    # rho = 9.5 / sqrt(10 * 9.5) = 9.5 / sqrt(95) = sqrt(0.95)
    expected = 9.5 / math.sqrt(95.0)
    for entry in result.correlations:
        assert entry.spearman_rho is not None
        assert math.isclose(entry.spearman_rho, expected, abs_tol=1e-12)


def test_constant_human_scores_returns_none() -> None:
    """All human scores identical → variance zero → ρ undefined per spec."""
    pairs = [
        _pair(1, human_scores=(3, 3, 3), llm_scores=(1, 4, 5)),
        _pair(2, human_scores=(3, 3, 3), llm_scores=(2, 5, 4)),
        _pair(3, human_scores=(3, 3, 3), llm_scores=(4, 2, 1)),
        _pair(4, human_scores=(3, 3, 3), llm_scores=(5, 3, 2)),
    ]
    humans = [h for h, _ in pairs]
    llms = [m for _, m in pairs]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 4  # noqa: PLR2004 — 4 paired observations.
    for entry in result.correlations:
        assert entry.spearman_rho is None


def test_constant_llm_scores_returns_none() -> None:
    """All LLM scores identical on one dimension → ρ undefined for that dimension."""
    pairs = [
        _pair(1, human_scores=(1, 4, 5), llm_scores=(3, 3, 3)),
        _pair(2, human_scores=(2, 5, 4), llm_scores=(3, 3, 3)),
        _pair(3, human_scores=(4, 2, 1), llm_scores=(3, 3, 3)),
        _pair(4, human_scores=(5, 3, 2), llm_scores=(3, 3, 3)),
    ]
    humans = [h for h, _ in pairs]
    llms = [m for _, m in pairs]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 4  # noqa: PLR2004 — 4 paired observations.
    for entry in result.correlations:
        assert entry.spearman_rho is None


def test_single_matched_pair_returns_none() -> None:
    """``n_matched == 1`` is below the Spearman ρ threshold; ρ is undefined."""
    h, m = _pair(1, human_scores=(3, 4, 5), llm_scores=(3, 4, 5))
    result = compute_human_calibration(
        human_calls=[h],
        llm_calls=[m],
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 1
    for entry in result.correlations:
        assert entry.spearman_rho is None


def test_empty_input_returns_all_none() -> None:
    """No input on either side → all per-dimension ρ values are ``None``."""
    result = compute_human_calibration(
        human_calls=(),
        llm_calls=(),
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 0
    assert result.dropped == 0
    for entry in result.correlations:
        assert entry.spearman_rho is None


def test_per_dimension_correlations_are_independent() -> None:
    """Spearman ρ is computed per dimension; one constant column does not poison the rest."""
    pairs = [
        _pair(1, human_scores=(1, 3, 1), llm_scores=(1, 3, 5)),
        _pair(2, human_scores=(2, 3, 2), llm_scores=(2, 3, 4)),
        _pair(3, human_scores=(3, 3, 3), llm_scores=(3, 3, 3)),
        _pair(4, human_scores=(4, 3, 4), llm_scores=(4, 3, 2)),
        _pair(5, human_scores=(5, 3, 5), llm_scores=(5, 3, 1)),
    ]
    humans = [h for h, _ in pairs]
    llms = [m for _, m in pairs]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    by_dim = {entry.dimension: entry.spearman_rho for entry in result.correlations}
    # visual_coherence: human + llm both = [1..5] → ρ = 1.0
    assert by_dim["visual_coherence"] is not None
    assert math.isclose(by_dim["visual_coherence"], 1.0)
    # copy_realism: both constant → undefined
    assert by_dim["copy_realism"] is None
    # error_plausibility: human = [1..5], llm = [5..1] → ρ = -1.0
    assert by_dim["error_plausibility"] is not None
    assert math.isclose(by_dim["error_plausibility"], -1.0)


# --------------------------------------------------------------------------- #
# compute_human_calibration — pairing + filtering.
# --------------------------------------------------------------------------- #


def test_unmatched_calls_are_ignored() -> None:
    """Calls present on only one side never enter ρ."""
    humans = [
        _human(task_id="t1", target_label="x", visual_coherence=1),
        _human(task_id="t2", target_label="x", visual_coherence=2),
        _human(task_id="orphan_h", target_label="x", visual_coherence=5),
    ]
    llms = [
        _llm(task_id="t1", target_label="x", visual_coherence=1),
        _llm(task_id="t2", target_label="x", visual_coherence=2),
        _llm(task_id="orphan_l", target_label="x", visual_coherence=5),
    ]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 2  # noqa: PLR2004 — 2 paired (task_id, target_label) keys.
    assert result.dropped == 0


def test_drops_no_evidence_llm_calls() -> None:
    """LLM ``evidence_cited=False`` rows on matched keys are dropped per spec §5.5."""
    humans = [
        _human(task_id="t1", target_label="x", visual_coherence=1),
        _human(task_id="t2", target_label="x", visual_coherence=2),
        _human(task_id="t3", target_label="x", visual_coherence=3),
    ]
    llms = [
        _llm(
            task_id="t1",
            target_label="x",
            visual_coherence=1,
            evidence_cited=False,
        ),
        _llm(task_id="t2", target_label="x", visual_coherence=2),
        _llm(task_id="t3", target_label="x", visual_coherence=3),
    ]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 2  # noqa: PLR2004 — 2 surviving paired observations.
    assert result.dropped == 1


def test_target_label_matters_for_pairing() -> None:
    """``target_label`` is part of the matching key; different shops do not pair."""
    h = _human(task_id="t1", target_label="sandbox/hardware")
    m = _llm(task_id="t1", target_label="source/hardware")
    result = compute_human_calibration(
        human_calls=[h],
        llm_calls=[m],
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    assert result.n_matched == 0
    assert result.dropped == 0


def test_duplicate_human_keys_raises() -> None:
    humans = [
        _human(task_id="t1", target_label="x", visual_coherence=1),
        _human(task_id="t1", target_label="x", visual_coherence=2),
    ]
    llms = [_llm(task_id="t1", target_label="x")]
    with pytest.raises(ValueError, match="duplicate human call"):
        compute_human_calibration(
            human_calls=humans,
            llm_calls=llms,
            judge_model=_gpt5_pin(),
            rater_id=_RATER_ID,
        )


def test_duplicate_llm_keys_raises() -> None:
    humans = [_human(task_id="t1", target_label="x")]
    llms = [
        _llm(task_id="t1", target_label="x", visual_coherence=1),
        _llm(task_id="t1", target_label="x", visual_coherence=2),
    ]
    with pytest.raises(ValueError, match="duplicate llm call"):
        compute_human_calibration(
            human_calls=humans,
            llm_calls=llms,
            judge_model=_gpt5_pin(),
            rater_id=_RATER_ID,
        )


def test_mismatched_rater_id_raises() -> None:
    """A row whose ``rater_id`` ≠ the explicit argument must surface, not be silently averaged."""
    humans = [_human(task_id="t1", target_label="x", rater_id="other_human")]
    llms = [_llm(task_id="t1", target_label="x")]
    with pytest.raises(ValueError, match="rater_id"):
        compute_human_calibration(
            human_calls=humans,
            llm_calls=llms,
            judge_model=_gpt5_pin(),
            rater_id=_RATER_ID,
        )


# --------------------------------------------------------------------------- #
# JSON round-trip — paper supplement reads HumanCalibration from versioned reports.
# --------------------------------------------------------------------------- #


def test_human_calibration_json_round_trip() -> None:
    pairs = [
        _pair(1, human_scores=(1, 2, 3), llm_scores=(1, 2, 3)),
        _pair(2, human_scores=(4, 5, 1), llm_scores=(4, 5, 1)),
    ]
    humans = [h for h, _ in pairs]
    llms = [m for _, m in pairs]
    result = compute_human_calibration(
        human_calls=humans,
        llm_calls=llms,
        judge_model=_gpt5_pin(),
        rater_id=_RATER_ID,
    )
    payload = result.model_dump_json()
    round_trip = HumanCalibration.model_validate_json(payload)
    assert round_trip == result
