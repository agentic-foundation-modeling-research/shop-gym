"""Tests for ``shop_probe.judge.kappa`` (T7.1 — spec §5.9 + §7 M7).

The T7.1 gate from ``docs/impl/web_probe_implementation.md`` reads:

    Check: cross-judge κ reported.

These tests pin Cohen's κ math and the pairing semantics so reviewers can
trust the v1.1 cross-judge agreement number end-to-end:

* :class:`CrossJudgeAgreement` schema — closed contract; ``extra="forbid"``;
  agreement / kappa fields are ``None`` iff ``n_matched == 0``.
* :func:`compute_cross_judge_kappa` headline math:
  perfect agreement, total disagreement, partial agreement (Cohen's
  worked example), abstain handling.
* Pairing semantics — calls match by ``(task_id, pair_label)``; unmatched
  rows are ignored; swap-inconsistent or no-evidence rows on either side
  are dropped per spec §5.5 step 6 + guardrails and counted into
  ``dropped``.
* Error paths — duplicate ``(task_id, pair_label)`` keys raise; identical
  judge model pins raise.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from shop_probe.judge.kappa import (
    CrossJudgeAgreement,
    compute_cross_judge_kappa,
)
from shop_probe.report import JudgeCall, JudgeModelPin, JudgePick

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_PROMPT_HASH: str = "c" * 64


def _gpt5_pin() -> JudgeModelPin:
    return JudgeModelPin(
        provider="openai",
        model="gpt-5",
        model_version="gpt-5-2025-09-01",
        temperature=0.0,
    )


def _claude_pin() -> JudgeModelPin:
    return JudgeModelPin(
        provider="anthropic",
        model="claude-sonnet-4.5",
        model_version="claude-sonnet-4-5-2026-01-15",
        temperature=0.0,
    )


def _call(
    *,
    task_id: str = "t01_filter_open_pdp",
    pair_label: tuple[str, str] = ("traj/A", "traj/B"),
    judge_pick: JudgePick = "A",
    swap_consistent: bool = True,
    evidence_cited: bool = True,
) -> JudgeCall:
    return JudgeCall(
        task_id=task_id,
        pair_label=pair_label,
        judge_pick=judge_pick,
        truth="B",
        swap_consistent=swap_consistent,
        evidence_cited=evidence_cited,
        confidence=0.5,
        prompt_hash=_PROMPT_HASH,
        response_text='{"pick": "A", "rationale": "..."}',
    )


# --------------------------------------------------------------------------- #
# Schema — CrossJudgeAgreement.
# --------------------------------------------------------------------------- #


def test_cross_judge_agreement_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        CrossJudgeAgreement.model_validate(
            {
                "primary_model": _gpt5_pin().model_dump(),
                "secondary_model": _claude_pin().model_dump(),
                "n_matched": 0,
                "dropped": 0,
                "observed_agreement": None,
                "expected_agreement": None,
                "kappa": None,
                "unknown_field": "rejected",
            }
        )


def test_cross_judge_agreement_rejects_identical_pins() -> None:
    with pytest.raises(ValidationError):
        CrossJudgeAgreement(
            primary_model=_gpt5_pin(),
            secondary_model=_gpt5_pin(),
            n_matched=0,
            dropped=0,
        )


def test_cross_judge_agreement_rejects_empty_with_agreements_set() -> None:
    """``n_matched == 0`` requires both agreement fields to be ``None``."""
    with pytest.raises(ValidationError):
        CrossJudgeAgreement(
            primary_model=_gpt5_pin(),
            secondary_model=_claude_pin(),
            n_matched=0,
            dropped=0,
            observed_agreement=1.0,
            expected_agreement=1.0,
        )


def test_cross_judge_agreement_rejects_nonempty_with_agreements_unset() -> None:
    """``n_matched > 0`` requires both agreement fields to be set."""
    with pytest.raises(ValidationError):
        CrossJudgeAgreement(
            primary_model=_gpt5_pin(),
            secondary_model=_claude_pin(),
            n_matched=4,
            dropped=0,
            observed_agreement=None,
            expected_agreement=None,
        )


# --------------------------------------------------------------------------- #
# compute_cross_judge_kappa — math.
# --------------------------------------------------------------------------- #


def test_kappa_perfect_agreement_is_one() -> None:
    """Both judges always agree on a multi-category sample → κ = 1.0."""
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="B"),
        _call(task_id="t3", pair_label=("e", "f"), judge_pick="A"),
        _call(task_id="t4", pair_label=("g", "h"), judge_pick="B"),
    )
    secondary = primary
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 4  # noqa: PLR2004 — 4 matched picks set up above.
    assert result.dropped == 0
    assert result.observed_agreement == 1.0
    assert result.kappa is not None
    assert math.isclose(result.kappa, 1.0)


def test_kappa_total_disagreement_is_negative() -> None:
    """Two-category sample where judges always pick the opposite → κ = -1.0."""
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="A"),
        _call(task_id="t3", pair_label=("e", "f"), judge_pick="B"),
        _call(task_id="t4", pair_label=("g", "h"), judge_pick="B"),
    )
    secondary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="B"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="B"),
        _call(task_id="t3", pair_label=("e", "f"), judge_pick="A"),
        _call(task_id="t4", pair_label=("g", "h"), judge_pick="A"),
    )
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 4  # noqa: PLR2004 — 4 matched picks set up above.
    assert result.observed_agreement == 0.0
    # Marginals (A/B) are 50/50 on each side → p_e = 0.5; κ = (0 - 0.5) / 0.5 = -1.
    assert result.kappa is not None
    assert math.isclose(result.kappa, -1.0)


def test_kappa_partial_agreement_matches_worked_example() -> None:
    """Cohen's worked example: pinned numerical κ on a 10-pair mixed sample.

    Layout (one row per matched pair):

    ====   primary   secondary
    p1      A           A
    p2      A           A
    p3      A           B
    p4      A           B
    p5      A           B
    p6      B           A
    p7      B           A
    p8      B           B
    p9      B           B
    p10     B           B

    Observed agreement: 5 / 10 = 0.5.
    Marginals: primary A=5, B=5; secondary A=4, B=6.
    p_e = (5/10)*(4/10) + (5/10)*(6/10) = 0.20 + 0.30 = 0.50.
    κ = (0.5 - 0.5) / (1 - 0.5) = 0.0.
    """
    primary_picks: tuple[JudgePick, ...] = (
        "A",
        "A",
        "A",
        "A",
        "A",
        "B",
        "B",
        "B",
        "B",
        "B",
    )
    secondary_picks: tuple[JudgePick, ...] = (
        "A",
        "A",
        "B",
        "B",
        "B",
        "A",
        "A",
        "B",
        "B",
        "B",
    )
    primary = tuple(
        _call(task_id=f"t{i}", pair_label=(f"a{i}", f"b{i}"), judge_pick=p)
        for i, p in enumerate(primary_picks)
    )
    secondary = tuple(
        _call(task_id=f"t{i}", pair_label=(f"a{i}", f"b{i}"), judge_pick=p)
        for i, p in enumerate(secondary_picks)
    )
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 10  # noqa: PLR2004 — 10 paired observations in the worked example.
    assert result.observed_agreement == pytest.approx(0.5)
    assert result.expected_agreement == pytest.approx(0.5)
    assert result.kappa is not None
    assert math.isclose(result.kappa, 0.0, abs_tol=1e-9)


def test_kappa_handles_abstain_as_third_category() -> None:
    """Abstain is a recorded category; κ math uses all three pick values."""
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="abstain"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="abstain"),
        _call(task_id="t3", pair_label=("e", "f"), judge_pick="A"),
        _call(task_id="t4", pair_label=("g", "h"), judge_pick="B"),
    )
    secondary = primary
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 4  # noqa: PLR2004 — 4 matched picks set up above.
    assert result.kappa is not None
    assert math.isclose(result.kappa, 1.0)


def test_kappa_collapsed_marginals_returns_none() -> None:
    """Both judges always pick A → p_e == 1; κ undefined → ``None``."""
    primary = tuple(
        _call(task_id=f"t{i}", pair_label=(f"a{i}", f"b{i}"), judge_pick="A") for i in range(3)
    )
    secondary = primary
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 3  # noqa: PLR2004 — 3 matched picks set up above.
    assert result.observed_agreement == 1.0
    assert result.expected_agreement == 1.0
    assert result.kappa is None


# --------------------------------------------------------------------------- #
# compute_cross_judge_kappa — pairing + filtering.
# --------------------------------------------------------------------------- #


def test_kappa_unmatched_calls_are_ignored() -> None:
    """Calls present in only one judge's output never enter κ."""
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="A"),
        _call(task_id="orphan", pair_label=("p", "q"), judge_pick="B"),
    )
    secondary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="A"),
        _call(task_id="other_orphan", pair_label=("x", "y"), judge_pick="A"),
    )
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 2  # noqa: PLR2004 — 2 matched (task_id, pair_label) keys.
    assert result.dropped == 0


def test_kappa_drops_swap_inconsistent_calls() -> None:
    """Swap-inconsistent calls on either side are dropped (spec §5.5 step 6)."""
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A", swap_consistent=False),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="A"),
    )
    secondary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="A", swap_consistent=False),
    )
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 0
    assert result.dropped == 2  # noqa: PLR2004 — both pairs dropped by swap filter.
    assert result.kappa is None
    assert result.observed_agreement is None
    assert result.expected_agreement is None


def test_kappa_drops_no_evidence_calls() -> None:
    """No-evidence calls on either side are dropped (spec §5.5 guardrails)."""
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A", evidence_cited=False),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="A"),
    )
    secondary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="A"),
    )
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 1
    assert result.dropped == 1


def test_kappa_empty_inputs() -> None:
    """No primary or secondary calls → empty result with ``kappa=None``."""
    result = compute_cross_judge_kappa(
        primary_calls=(),
        secondary_calls=(),
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 0
    assert result.dropped == 0
    assert result.kappa is None
    assert result.observed_agreement is None
    assert result.expected_agreement is None


def test_kappa_duplicate_primary_keys_raises() -> None:
    """Defective upstream pair construction must surface, not silently dedupe."""
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="B"),
    )
    secondary = (_call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),)
    with pytest.raises(ValueError, match="duplicate primary call"):
        compute_cross_judge_kappa(
            primary_calls=primary,
            secondary_calls=secondary,
            primary_model=_gpt5_pin(),
            secondary_model=_claude_pin(),
        )


def test_kappa_duplicate_secondary_keys_raises() -> None:
    secondary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="B"),
    )
    primary = (_call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),)
    with pytest.raises(ValueError, match="duplicate secondary call"):
        compute_cross_judge_kappa(
            primary_calls=primary,
            secondary_calls=secondary,
            primary_model=_gpt5_pin(),
            secondary_model=_claude_pin(),
        )


def test_kappa_pair_label_order_must_match() -> None:
    """``pair_label`` order is part of the matching key — different presentation
    orders are different observations and do not pair.
    """
    primary = (_call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),)
    secondary = (_call(task_id="t1", pair_label=("b", "a"), judge_pick="A"),)
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    assert result.n_matched == 0
    assert result.dropped == 0


# --------------------------------------------------------------------------- #
# JSON round-trip — the v1.1 supplement table reads CrossJudgeAgreement.
# --------------------------------------------------------------------------- #


def test_cross_judge_agreement_json_round_trip() -> None:
    primary = (
        _call(task_id="t1", pair_label=("a", "b"), judge_pick="A"),
        _call(task_id="t2", pair_label=("c", "d"), judge_pick="B"),
    )
    secondary = primary
    result = compute_cross_judge_kappa(
        primary_calls=primary,
        secondary_calls=secondary,
        primary_model=_gpt5_pin(),
        secondary_model=_claude_pin(),
    )
    payload = result.model_dump_json()
    round_trip = CrossJudgeAgreement.model_validate_json(payload)
    assert round_trip == result
