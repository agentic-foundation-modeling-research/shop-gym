"""Tests for ``shop_probe.judge.swap`` (T4.8 — spec §5.5 step 6).

The T4.8 gate from ``docs/impl/web_probe_implementation.md`` reads:

    Check: swap-consistency unit test on a stub-judge fixture.

Coverage:

* :class:`Presentation` — ``position_a`` / ``position_b`` resolve canonical
  members through the ``swap`` flag (spec §5.5 step 5).
* :func:`presentations_for` — emits ``(unswapped, swapped)`` for the
  step 6 re-run.
* :func:`is_swap_consistent` — every (pick, pick) branch including
  abstain handling.
* :func:`evaluate_swap_consistency` — drives a stub
  :class:`JudgeCallable` over both presentations per pair and threads
  results in input order.
* :func:`swap_drop_rate` — fraction-of-inconsistent reduction; empty
  input; M4 gate boundary check (≤ 5%).
"""

from __future__ import annotations

import pytest

from shop_probe.judge.pairwise import PairwisePair, build_experimental_pairs
from shop_probe.judge.swap import (
    JudgeCallable,
    Presentation,
    SwapConsistencyResult,
    evaluate_swap_consistency,
    is_swap_consistent,
    presentations_for,
    swap_drop_rate,
)
from shop_probe.report import JudgePick
from shop_probe.targets import Cohort, Pair, Target, TargetKind

# --------------------------------------------------------------------------- #
# Fixture builders. Mirror tests/judge/test_pairwise.py: the shipped
# cohort.yaml is a v0.1 stub with TBD URLs, so we build a fully-populated
# cohort here so swap tests don't hinge on those open questions.
# --------------------------------------------------------------------------- #

_PAIR_IDS: tuple[str, str, str] = ("pair_hardware", "pair_hexclad", "pair_aloyoga")


def _target(label: str, kind: TargetKind, pair_id: str | None = None) -> Target:
    return Target(
        label=label,
        base_url=f"https://{label.replace('/', '-')}.example",
        kind=kind,
        pair_id=pair_id,
    )


def _full_cohort() -> Cohort:
    pairs = tuple(
        Pair(
            id=pid,
            source=_target(f"source/{pid}", "source", pid),
            sandbox=_target(f"sandbox/{pid}", "sandbox", pid),
        )
        for pid in _PAIR_IDS
    )
    real_unpaired = tuple(_target(f"real/unpaired_{i}", "real_unpaired") for i in range(3))
    return Cohort(version="0.1", pairs=pairs, real_unpaired=real_unpaired)


def _experimental_pair() -> PairwisePair:
    return build_experimental_pairs(_full_cohort())[0]


# --------------------------------------------------------------------------- #
# Presentation.
# --------------------------------------------------------------------------- #


def test_presentation_unswapped_resolves_members_in_canonical_order() -> None:
    pair = _experimental_pair()
    p = Presentation(pair=pair, swap=False)
    assert p.position_a == pair.members[0]
    assert p.position_b == pair.members[1]


def test_presentation_swapped_flips_members() -> None:
    pair = _experimental_pair()
    p = Presentation(pair=pair, swap=True)
    assert p.position_a == pair.members[1]
    assert p.position_b == pair.members[0]


def test_presentation_is_frozen() -> None:
    p = Presentation(pair=_experimental_pair(), swap=False)
    with pytest.raises(AttributeError):
        p.swap = True  # type: ignore[misc]


def test_presentations_for_returns_both_orders() -> None:
    pair = _experimental_pair()
    unswapped, swapped = presentations_for(pair)
    assert unswapped.swap is False
    assert swapped.swap is True
    assert unswapped.pair is pair
    assert swapped.pair is pair


# --------------------------------------------------------------------------- #
# is_swap_consistent — every branch (spec §5.5 step 6).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("unswapped", "swapped", "expected"),
    [
        # Letters differ -> judge tracked the shop, not the slot -> consistent.
        ("A", "B", True),
        ("B", "A", True),
        # Letters match -> judge tracked the slot -> position-bias flip.
        ("A", "A", False),
        ("B", "B", False),
        # abstain in either run -> drop (no signal).
        ("abstain", "A", False),
        ("A", "abstain", False),
        ("abstain", "B", False),
        ("B", "abstain", False),
        ("abstain", "abstain", False),
    ],
)
def test_is_swap_consistent_branches(
    unswapped: JudgePick, swapped: JudgePick, expected: bool
) -> None:
    assert is_swap_consistent(unswapped, swapped) is expected


# --------------------------------------------------------------------------- #
# evaluate_swap_consistency — stub-judge fixtures (T4.8 gate).
# --------------------------------------------------------------------------- #


def _shop_tracking_judge(target_label: str) -> JudgeCallable:
    """Stub: judge always picks the slot containing ``target_label``.

    This is the swap-consistent baseline — the judge tracks the shop, so
    its pick *letter* flips when A/B swap.
    """

    def _judge(presentation: Presentation) -> JudgePick:
        if presentation.position_a.label == target_label:
            return "A"
        if presentation.position_b.label == target_label:
            return "B"
        msg = f"target {target_label!r} not in presentation"
        raise AssertionError(msg)

    return _judge


def _slot_anchored_judge(slot: JudgePick) -> JudgeCallable:
    """Stub: judge always picks ``slot`` regardless of contents.

    This is the maximal position-bias case — the judge tracks the slot,
    so its pick letter never changes across the swap → never consistent.
    """

    def _judge(_presentation: Presentation) -> JudgePick:
        return slot

    return _judge


def _abstaining_judge() -> JudgeCallable:
    """Stub: judge always abstains."""

    def _judge(_presentation: Presentation) -> JudgePick:
        return "abstain"

    return _judge


def test_evaluate_swap_consistency_shop_tracking_judge_is_consistent() -> None:
    """A judge that follows the shop should be consistent on every pair."""
    cohort = _full_cohort()
    pairs = build_experimental_pairs(cohort)
    judge = _shop_tracking_judge(pairs[0].members[1].label)  # always picks the source

    # Apply per-pair so each pair has the correct target in scope.
    results: list[SwapConsistencyResult] = []
    for pair in pairs:
        # Re-bind to this pair's source label for each pair.
        per_pair = _shop_tracking_judge(pair.members[1].label)
        results.extend(evaluate_swap_consistency([pair], per_pair))

    assert tuple(r.pair_id for r in results) == tuple(p.pair_id for p in pairs)
    for r in results:
        assert r.consistent is True
        assert {r.unswapped_pick, r.swapped_pick} == {"A", "B"}
    assert swap_drop_rate(results) == 0.0
    # Silence unused-variable warning on the seed judge.
    _ = judge


def test_evaluate_swap_consistency_slot_anchored_judge_always_drops() -> None:
    """Slot-anchored stubs flip on swap → all pairs inconsistent."""
    pairs = build_experimental_pairs(_full_cohort())
    for slot in ("A", "B"):
        judge = _slot_anchored_judge(slot)  # type: ignore[arg-type]
        results = evaluate_swap_consistency(pairs, judge)

        assert len(results) == len(pairs)
        for r in results:
            assert r.unswapped_pick == slot
            assert r.swapped_pick == slot
            assert r.consistent is False
        assert swap_drop_rate(results) == 1.0


def test_evaluate_swap_consistency_abstaining_judge_drops_all() -> None:
    pairs = build_experimental_pairs(_full_cohort())
    results = evaluate_swap_consistency(pairs, _abstaining_judge())

    for r in results:
        assert r.unswapped_pick == "abstain"
        assert r.swapped_pick == "abstain"
        assert r.consistent is False
    assert swap_drop_rate(results) == 1.0


def test_evaluate_swap_consistency_preserves_input_order() -> None:
    pairs = build_experimental_pairs(_full_cohort())
    judge = _slot_anchored_judge("A")
    results = evaluate_swap_consistency(pairs, judge)

    assert tuple(r.pair_id for r in results) == tuple(p.pair_id for p in pairs)


def test_evaluate_swap_consistency_invokes_judge_twice_per_pair() -> None:
    """Spec §5.5 step 6: re-run with A/B swapped → exactly two calls per pair."""
    pairs = build_experimental_pairs(_full_cohort())
    calls: list[Presentation] = []

    def _recording_judge(presentation: Presentation) -> JudgePick:
        calls.append(presentation)
        return "A"

    evaluate_swap_consistency(pairs, _recording_judge)

    assert len(calls) == 2 * len(pairs)
    # Per pair, exactly one unswapped + one swapped invocation.
    for pair in pairs:
        per_pair = [c for c in calls if c.pair is pair]
        assert sorted(c.swap for c in per_pair) == [False, True]


def test_evaluate_swap_consistency_empty_input() -> None:
    assert evaluate_swap_consistency([], _slot_anchored_judge("A")) == ()


# --------------------------------------------------------------------------- #
# swap_drop_rate.
# --------------------------------------------------------------------------- #


def _result(pair_id: str, *, consistent: bool) -> SwapConsistencyResult:
    return SwapConsistencyResult(
        pair_id=pair_id,
        unswapped_pick="A",
        swapped_pick="B" if consistent else "A",
        consistent=consistent,
    )


def test_swap_drop_rate_empty_returns_zero() -> None:
    assert swap_drop_rate(()) == 0.0


def test_swap_drop_rate_all_consistent_is_zero() -> None:
    results = tuple(_result(f"p{i}", consistent=True) for i in range(5))
    assert swap_drop_rate(results) == 0.0


def test_swap_drop_rate_all_inconsistent_is_one() -> None:
    results = tuple(_result(f"p{i}", consistent=False) for i in range(4))
    assert swap_drop_rate(results) == 1.0


def test_swap_drop_rate_mixed() -> None:
    results = (
        _result("p0", consistent=True),
        _result("p1", consistent=False),
        _result("p2", consistent=True),
        _result("p3", consistent=False),
    )
    # 2 inconsistent / 4 total = 0.5
    assert swap_drop_rate(results) == 0.5  # noqa: PLR2004 — two of four flips.


def test_swap_drop_rate_at_m4_gate_boundary() -> None:
    """Spec §7 M4 gate: ≤ 5% swap-inconsistency rate.

    1 inconsistent out of 20 = 5% — sits exactly at the gate.
    """
    results = (
        _result("p0", consistent=False),
        *(_result(f"p{i}", consistent=True) for i in range(1, 20)),
    )
    rate = swap_drop_rate(results)
    assert rate == pytest.approx(0.05)
    assert rate <= 0.05  # noqa: PLR2004 — spec §7 M4 gate threshold.
