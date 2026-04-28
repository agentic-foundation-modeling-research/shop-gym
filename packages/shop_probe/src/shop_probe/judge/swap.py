"""Position-bias / swap-consistency check (T4.8 — spec §5.5 step 6).

Spec §5.5 step 6 (verbatim):

    Position-bias check. Re-run with A/B swapped. Drop pairs where the
    judge flips on swap. Report drop rate.

A judge is *swap-consistent* on a pair iff its pick names the **same
underlying storefront** regardless of which presentation slot (A vs B)
that storefront occupies. Concretely, with the canonical pair
``members = (m0, m1)``:

* unswapped: ``A=m0``, ``B=m1``
* swapped:   ``A=m1``, ``B=m0``

The judge picked ``m0`` in both runs iff it said ``"A"`` unswapped and
``"B"`` swapped. Symmetrically for ``m1``. If the judge says the same
letter in both runs it has tracked the slot, not the shop — that is a
position-bias flip and the pair is dropped.

``"abstain"`` in either run is treated as inconsistent (drop): the spec
§5.5 guardrails already require evidence-cited abstention to be
discarded, and a half-abstaining pair carries no information about the
swap.

This module is pure: it operates on canonical
:class:`shop_probe.judge.pairwise.PairwisePair` values plus a
caller-supplied judge callable, and returns frozen result rows. The
real LLM wiring lands in T4.6; the unit tests under T4.8 use a stub
callable to exercise every consistency branch.

The module is import-safe — no I/O at import time.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from shop_probe.judge.pairwise import PairwisePair
from shop_probe.report import JudgePick
from shop_probe.targets import Target


@dataclass(frozen=True, slots=True)
class Presentation:
    """One canonical pair shown to the judge in a specific A/B order.

    Spec §5.5 step 5 randomizes presentation order, and step 6 re-runs
    with A/B swapped. This dataclass is the wire-level "what the judge
    sees" — :attr:`position_a` and :attr:`position_b` resolve the
    canonical members through the swap flag.

    Attributes:
        pair: Canonical pair (members in spec §5.5 step 4 order — sandbox
            first for experimental pairs).
        swap: ``False`` for the canonical order (``A=members[0]``,
            ``B=members[1]``); ``True`` for the swapped order
            (``A=members[1]``, ``B=members[0]``) used by the position-bias
            re-run.
    """

    pair: PairwisePair
    swap: bool

    @property
    def position_a(self) -> Target:
        """Storefront in the A slot under this presentation."""
        return self.pair.members[1] if self.swap else self.pair.members[0]

    @property
    def position_b(self) -> Target:
        """Storefront in the B slot under this presentation."""
        return self.pair.members[0] if self.swap else self.pair.members[1]


def presentations_for(pair: PairwisePair) -> tuple[Presentation, Presentation]:
    """Return both presentation orders for the spec §5.5 step 6 swap re-run.

    Args:
        pair: Canonical pair as built by
            :mod:`shop_probe.judge.pairwise`.

    Returns:
        ``(unswapped, swapped)`` — the canonical presentation followed by
        its A/B-swapped counterpart.
    """
    return (Presentation(pair=pair, swap=False), Presentation(pair=pair, swap=True))


def is_swap_consistent(unswapped_pick: JudgePick, swapped_pick: JudgePick) -> bool:
    """Return ``True`` iff the judge tracked the shop, not the slot (spec §5.5 step 6).

    The judge is swap-consistent iff its pick names the same canonical
    member in both presentations. That happens exactly when the pick
    *letters* differ between unswapped and swapped runs (because the
    same shop sits in different slots across the two runs).

    ``"abstain"`` in either run counts as inconsistent: the spec §5.5
    guardrails already discard evidence-less abstentions, and a partial
    abstention carries no signal about position bias either way.

    Args:
        unswapped_pick: Judge pick on the canonical presentation.
        swapped_pick: Judge pick on the A/B-swapped presentation.

    Returns:
        ``True`` if the judge picked the same underlying shop in both
        runs; ``False`` if it flipped on the slot or abstained on
        either run.
    """
    if unswapped_pick == "abstain" or swapped_pick == "abstain":
        return False
    return unswapped_pick != swapped_pick


@dataclass(frozen=True, slots=True)
class SwapConsistencyResult:
    """Per-pair outcome of the spec §5.5 step 6 position-bias check.

    Callers drop pairs with ``consistent=False`` before computing
    ``judge_accuracy_experimental`` / ``judge_accuracy_control`` (spec
    §5.5 step 7). The drop rate aggregated across the cohort is the M4
    gate metric (spec §7 M4: ≤ 5% swap-inconsistency rate).

    Attributes:
        pair_id: Canonical pair id (matches
            :attr:`PairwisePair.pair_id`).
        unswapped_pick: Judge pick on the canonical presentation.
        swapped_pick: Judge pick on the A/B-swapped presentation.
        consistent: ``True`` iff the judge tracked the shop, not the slot.
    """

    pair_id: str
    unswapped_pick: JudgePick
    swapped_pick: JudgePick
    consistent: bool


JudgeCallable = Callable[[Presentation], JudgePick]
"""Stub-friendly judge interface for the position-bias check.

T4.6 will provide the production LLM-backed callable. T4.8 only needs
to drive a callable in two presentation orders, so the contract is
deliberately narrow: take a :class:`Presentation`, return a
:data:`~shop_probe.report.JudgePick`.
"""


def evaluate_swap_consistency(
    pairs: Sequence[PairwisePair],
    judge: JudgeCallable,
) -> tuple[SwapConsistencyResult, ...]:
    """Run the swap-consistency check across a pair population (spec §5.5 step 6).

    For each pair the judge is invoked twice — once on the canonical
    presentation, once on the swapped presentation — and the two picks
    are reduced through :func:`is_swap_consistent`.

    Args:
        pairs: Canonical pairs (typically the full output of
            :func:`shop_probe.judge.pairwise.build_task_pairs`).
        judge: Caller-supplied callable that returns a
            :data:`~shop_probe.report.JudgePick` for one
            :class:`Presentation`. Production callers wire the pinned
            LLM judge from T4.6; tests pass stubs.

    Returns:
        One :class:`SwapConsistencyResult` per input pair, in input order.
    """
    results: list[SwapConsistencyResult] = []
    for pair in pairs:
        unswapped, swapped = presentations_for(pair)
        unswapped_pick = judge(unswapped)
        swapped_pick = judge(swapped)
        results.append(
            SwapConsistencyResult(
                pair_id=pair.pair_id,
                unswapped_pick=unswapped_pick,
                swapped_pick=swapped_pick,
                consistent=is_swap_consistent(unswapped_pick, swapped_pick),
            )
        )
    return tuple(results)


def swap_drop_rate(results: Sequence[SwapConsistencyResult]) -> float:
    """Fraction of pairs flagged inconsistent and therefore dropped (spec §5.5 step 6).

    The M4 gate (spec §7 M4) requires this rate to be ≤ 0.05 on the
    pilot pair before the cohort run is opened.

    Args:
        results: Per-pair outcomes from
            :func:`evaluate_swap_consistency`.

    Returns:
        ``# inconsistent / # results``, in ``[0.0, 1.0]``. Returns
        ``0.0`` for an empty input (no pairs run → no drops).
    """
    if not results:
        return 0.0
    inconsistent = sum(1 for r in results if not r.consistent)
    return inconsistent / len(results)
