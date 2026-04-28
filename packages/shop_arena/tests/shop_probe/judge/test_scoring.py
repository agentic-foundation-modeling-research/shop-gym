"""Tests for `shop_probe.judge.scoring` (T5.3 — spec §5.5 step 7, §7 M5).

Exercise the spec §5.5 step 7 reduction over a population of
:class:`~shop_probe.report.JudgeCall` rows. The two guardrails (drop
swap-inconsistent + drop no-evidence per spec §5.5 step 6 + guardrails)
are pinned here so every downstream consumer sees the same denominator
across the cohort run (spec §7 M5).
"""

from __future__ import annotations

import pytest

from shop_probe.judge.scoring import JudgeAccuracy, score_judge_calls
from shop_probe.report import JudgeCall, JudgePick, JudgeTruth


def _call(
    *,
    pick: JudgePick = "A",
    truth: JudgeTruth = "A",
    swap_consistent: bool = True,
    evidence_cited: bool = True,
) -> JudgeCall:
    return JudgeCall(
        task_id="t",
        pair_label=("a", "b"),
        judge_pick=pick,
        truth=truth,
        swap_consistent=swap_consistent,
        evidence_cited=evidence_cited,
        confidence=0.5,
        prompt_hash="0" * 64,
        response_text="{}",
    )


def test_score_judge_calls_empty_returns_none_accuracy() -> None:
    """Spec §5.5 step 7: an empty population has an undefined fraction."""
    result = score_judge_calls([])
    assert result == JudgeAccuracy(accuracy=None, n_total=0, n_kept=0, n_dropped=0)


def test_score_judge_calls_all_correct() -> None:
    calls = [_call(pick="A", truth="A") for _ in range(4)]
    result = score_judge_calls(calls)
    assert result.accuracy == pytest.approx(1.0)
    assert result.n_total == 4  # noqa: PLR2004
    assert result.n_kept == 4  # noqa: PLR2004
    assert result.n_dropped == 0


def test_score_judge_calls_all_wrong() -> None:
    calls = [_call(pick="B", truth="A") for _ in range(4)]
    result = score_judge_calls(calls)
    assert result.accuracy == pytest.approx(0.0)
    assert result.n_total == 4  # noqa: PLR2004
    assert result.n_kept == 4  # noqa: PLR2004
    assert result.n_dropped == 0


def test_score_judge_calls_mixed_returns_fraction() -> None:
    """Three correct out of four kept → accuracy = 0.75."""
    calls = [
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A"),
        _call(pick="B", truth="A"),
    ]
    result = score_judge_calls(calls)
    assert result.accuracy == pytest.approx(0.75)
    assert result.n_total == 4  # noqa: PLR2004
    assert result.n_kept == 4  # noqa: PLR2004
    assert result.n_dropped == 0


def test_score_judge_calls_drops_swap_inconsistent_calls() -> None:
    """Spec §5.5 step 6: swap-inconsistent calls are dropped from scoring."""
    calls = [
        _call(pick="A", truth="A", swap_consistent=True),
        _call(pick="B", truth="A", swap_consistent=False),  # dropped → not penalized
        _call(pick="A", truth="A", swap_consistent=True),
    ]
    result = score_judge_calls(calls)
    assert result.accuracy == pytest.approx(1.0)
    assert result.n_total == 3  # noqa: PLR2004
    assert result.n_kept == 2  # noqa: PLR2004
    assert result.n_dropped == 1


def test_score_judge_calls_drops_no_evidence_calls() -> None:
    """Spec §5.5 guardrails: calls without evidence citation are dropped."""
    calls = [
        _call(pick="A", truth="A", evidence_cited=True),
        _call(pick="B", truth="A", evidence_cited=False),  # dropped
        _call(pick="A", truth="A", evidence_cited=True),
    ]
    result = score_judge_calls(calls)
    assert result.accuracy == pytest.approx(1.0)
    assert result.n_total == 3  # noqa: PLR2004
    assert result.n_kept == 2  # noqa: PLR2004
    assert result.n_dropped == 1


def test_score_judge_calls_drops_swap_inconsistent_and_no_evidence_independently() -> None:
    """Either guardrail alone is enough to drop a call."""
    calls = [
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A", swap_consistent=False),
        _call(pick="A", truth="A", evidence_cited=False),
        _call(pick="A", truth="A", swap_consistent=False, evidence_cited=False),
    ]
    result = score_judge_calls(calls)
    assert result.accuracy == pytest.approx(1.0)
    assert result.n_total == 4  # noqa: PLR2004
    assert result.n_kept == 1
    assert result.n_dropped == 3  # noqa: PLR2004


def test_score_judge_calls_all_dropped_returns_none_accuracy() -> None:
    """All calls dropped → accuracy is undefined (None), not zero."""
    calls = [_call(pick="A", truth="A", swap_consistent=False) for _ in range(3)]
    result = score_judge_calls(calls)
    assert result.accuracy is None
    assert result.n_total == 3  # noqa: PLR2004
    assert result.n_kept == 0
    assert result.n_dropped == 3  # noqa: PLR2004


def test_score_judge_calls_abstain_pick_never_correct() -> None:
    """Spec §5.5 guardrails: ``"abstain"`` cannot equal ``truth`` (literal mismatch)."""
    calls = [
        _call(pick="abstain", truth="A"),
        _call(pick="A", truth="A"),
    ]
    result = score_judge_calls(calls)
    # The ``"abstain"`` call survives both guardrails (swap_consistent + evidence_cited)
    # but cannot equal "A" / "B", so it counts as 0/2 even though it was kept.
    assert result.accuracy == pytest.approx(0.5)
    assert result.n_total == 2  # noqa: PLR2004
    assert result.n_kept == 2  # noqa: PLR2004
    assert result.n_dropped == 0


def test_score_judge_calls_uses_truth_position_for_control_pairs() -> None:
    """Control pairs designate one slot as "real"; correct = pick that slot.

    Spec §5.5 step 7: ``judge_accuracy_control`` is the fraction of
    ``(real, real)`` calls where the judge picks the designated slot.
    The pure scorer treats this identically to experimental scoring —
    the difference is in which slot the caller marks as ``truth``.
    """
    calls = [
        _call(pick="A", truth="A"),  # picked the designated real → correct
        _call(pick="B", truth="A"),  # picked the other real → "incorrect"
        _call(pick="A", truth="A"),
    ]
    result = score_judge_calls(calls)
    assert result.accuracy == pytest.approx(2.0 / 3.0)
