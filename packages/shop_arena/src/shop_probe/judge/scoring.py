"""Pairwise judge scoring (T5.3 — spec §5.5 step 7, §7 M5).

Spec §5.5 step 7 (verbatim):

    Two numbers:

    * ``judge_accuracy_experimental`` — fraction of ``(sandbox, source)``
      calls where the judge picks the source. Range [0, 1]; 0.5 is naively
      "indistinguishable".
    * ``judge_accuracy_control`` — fraction of ``(real, real)`` calls
      where the judge picks a designated "real" position consistently.
      Used as a **noise floor**: the meaningful indistinguishability claim
      is ``|experimental - control| <= eps`` rather than
      ``experimental ≈ 0.5`` in absolute terms.

This module owns the spec §5.5 step 7 reduction over a population of
:class:`~shop_probe.report.JudgeCall` rows. The two guardrails from
spec §5.5 are applied here so every downstream consumer (paper figures,
fidelity table, CLI report) sees the same denominator:

* swap-inconsistent calls (spec §5.5 step 6) are dropped;
* no-evidence calls (spec §5.5 guardrails) are dropped.

The dropped count is preserved on every result object so reviewers can
reconcile ``judge_n_pairs - judge_dropped`` against the fraction.

The module is pure: no I/O, no network, no model calls. The
:mod:`shop_probe.judge.run` orchestrator hands raw
:class:`~shop_probe.report.JudgeCall` rows here once a cohort run has
emitted them; the M5 gate (spec §7 M5) is satisfied iff every cohort
report carries judge calls and these scoring helpers reduce them into
:attr:`~shop_probe.fidelity.PairFidelity.judge_accuracy_experimental`
plus :attr:`~shop_probe.fidelity.CohortFidelity.judge_accuracy_control`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shop_probe.report import JudgeCall


@dataclass(frozen=True, slots=True)
class JudgeAccuracy:
    """Scored ``judge_pick == truth`` rate over a :class:`JudgeCall` population.

    Used for both the experimental ``(sandbox, source)`` populations
    (one per pair) and the cohort-level control ``(real, real)``
    population. The semantics differ — experimental accuracy is the
    fraction of calls where the judge correctly picked the source;
    control accuracy is the noise floor against which the spec §5.7
    indistinguishability claim is evaluated — but the arithmetic is
    identical, so both share this dataclass.

    Attributes:
        accuracy: Fraction of kept calls where ``judge_pick == truth``,
            in ``[0.0, 1.0]``. ``None`` iff ``n_kept == 0`` (every call
            was dropped by the spec §5.5 guardrails); the empty mean is
            undefined and reported as missing rather than as ``0.0``.
        n_total: Total number of calls considered (kept + dropped).
        n_kept: Number of calls that survived both guardrails (i.e.
            ``swap_consistent and evidence_cited``).
        n_dropped: ``n_total - n_kept`` — the number of calls dropped
            for being swap-inconsistent or lacking evidence (spec §5.5
            step 6 + guardrails).
    """

    accuracy: float | None
    n_total: int
    n_kept: int
    n_dropped: int


def _split_calls(calls: Sequence[JudgeCall]) -> tuple[list[bool], int]:
    """Apply spec §5.5 guardrails and return ``(correct_flags, n_dropped)``.

    Drops swap-inconsistent calls (spec §5.5 step 6) and calls without
    evidence citation (spec §5.5 guardrails). For each survivor the
    result records ``judge_pick == truth``.
    """
    correct: list[bool] = []
    n_dropped = 0
    for call in calls:
        if not call.swap_consistent or not call.evidence_cited:
            n_dropped += 1
            continue
        correct.append(call.judge_pick == call.truth)
    return correct, n_dropped


def score_judge_calls(calls: Sequence[JudgeCall]) -> JudgeAccuracy:
    """Reduce a :class:`JudgeCall` population to a :class:`JudgeAccuracy`.

    Used for both experimental and control populations — see spec §5.5
    step 7 and the class docstring for the difference in interpretation.

    Args:
        calls: Raw judge calls as recorded by
            :class:`~shop_probe.judge.run.PairJudgeOutcome` and embedded
            in a closed :class:`~shop_probe.report.ProbeReport`.
            ``"abstain"`` picks (recorded by spec §5.5 guardrails on
            parse-error / no-evidence calls) cannot equal ``truth`` and
            therefore never count as correct; they are also dropped by
            the no-evidence filter.

    Returns:
        A :class:`JudgeAccuracy` with the kept-call fraction. Empty
        input or an all-dropped input returns ``accuracy=None`` so
        callers can render the missing measurement explicitly rather
        than as a misleading ``0.0``.
    """
    correct, n_dropped = _split_calls(calls)
    n_total = len(calls)
    n_kept = len(correct)
    accuracy = (sum(1 for c in correct if c) / n_kept) if n_kept > 0 else None
    return JudgeAccuracy(
        accuracy=accuracy,
        n_total=n_total,
        n_kept=n_kept,
        n_dropped=n_dropped,
    )
