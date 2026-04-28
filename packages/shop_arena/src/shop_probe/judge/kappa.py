"""Cross-judge agreement (T7.1 — spec §5.9 + §7 M7).

The blinded pairwise judge (spec §5.5) runs *one* OpenAI flagship model in
v1. Spec §5.9 + §7 M7 promote a **second judge family** (Claude or Gemini)
to a v1.1 stretch deliverable so reviewers can read cross-lab triangulation
on top of the v1 single-judge result.

This module owns the aggregation layer: given two sequences of
:class:`shop_probe.report.JudgeCall` rows — one from each judge — paired by
``(task_id, pair_label)`` it emits :class:`CrossJudgeAgreement`, a closed
pydantic record whose headline number is **Cohen's κ** (spec §7 M7 gate
"cross-judge κ reported").

The wiring layer for actually running a second judge already exists. The
:class:`shop_probe.judge.llm.LLMClient` Protocol is vendor-neutral, so a
caller just instantiates a second :class:`shop_probe.judge.llm.PinnedJudge`
with a different :class:`shop_probe.report.JudgeModelPin` (e.g.
``provider="anthropic"``, ``model="claude-sonnet-4.5"``) and a matching
client implementation. Pair construction (T4.5), anonymization (T4.4), and
swap-consistency (T4.8) are shared across judges — only the model pin and
the client change.

Pairing semantics:

* Calls match when their ``(task_id, pair_label)`` tuples are equal. This
  assumes the caller runs both judges on the **same** pair construction
  (same cohort + seed + presentation order); shared upstream wiring
  guarantees this in production.
* Calls flagged ``swap_consistent=False`` or ``evidence_cited=False`` are
  dropped per spec §5.5 step 6 + guardrails before κ is computed. They
  are counted into :attr:`CrossJudgeAgreement.dropped`.
* Unmatched calls (present in only one judge's output) are ignored —
  Cohen's κ is only defined over a paired sample.

Cohen's κ formula (spec §7 M7 standard convention):

* ``p_o`` = observed agreement = fraction of matched pairs where both
  judges produced the same :data:`shop_probe.report.JudgePick`.
* ``p_e`` = expected agreement under independence, computed from the
  per-judge marginal pick distributions over the matched sample.
* ``kappa = (p_o - p_e) / (1 - p_e)``.

Edge cases:

* ``n_matched == 0`` — κ is undefined; ``kappa`` is ``None``.
* ``p_e == 1.0`` — the judges' marginals collapsed to a single category
  on the matched sample. κ is undefined; ``kappa`` is ``None`` (the
  ``(p_o - p_e) / (1 - p_e)`` ratio is 0/0). The degenerate "perfect
  agreement on a single category" case still leaves κ undefined per the
  classical definition, which is the conservative reporting convention.

The module is import-safe — no I/O at import time.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shop_probe.report import JudgeCall, JudgeModelPin, JudgePick

_PICK_CATEGORIES: Final[tuple[JudgePick, ...]] = tuple(get_args(JudgePick))
"""All :data:`JudgePick` literals (``"A"``, ``"B"``, ``"abstain"``)."""


class CrossJudgeAgreement(BaseModel):
    """Cross-judge agreement summary for one pair of judges (spec §7 M7).

    Closed schema so the v1.1 stretch result has a stable contract a
    paper-supplement table can pull from. The headline number is
    :attr:`kappa`; :attr:`n_matched` and :attr:`dropped` document the
    sample size and how many calls were excluded (per spec §5.5 step 6 +
    guardrails).

    Attributes:
        primary_model: Pinned model identity for the primary judge — the
            v1 OpenAI flagship in production runs.
        secondary_model: Pinned model identity for the secondary judge —
            the second-family judge introduced in v1.1 (Claude or Gemini
            per spec §5.9).
        n_matched: Count of paired ``(task_id, pair_label)`` calls that
            survived the swap-consistency + evidence-cited filters from
            spec §5.5 and contributed to ``kappa``.
        dropped: Count of pair-keys that matched across both judges but
            were dropped because at least one side had
            ``swap_consistent=False`` or ``evidence_cited=False``.
        observed_agreement: ``p_o`` — fraction of :attr:`n_matched`
            pairs where both judges produced the same pick. ``None``
            when ``n_matched == 0``.
        expected_agreement: ``p_e`` — chance agreement implied by the
            per-judge marginal distributions over the matched sample.
            ``None`` when ``n_matched == 0``.
        kappa: Cohen's κ. ``None`` when ``n_matched == 0`` or
            ``p_e == 1.0`` (κ undefined; see module docstring).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_model: JudgeModelPin
    secondary_model: JudgeModelPin
    n_matched: int = Field(ge=0)
    dropped: int = Field(ge=0)
    observed_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    kappa: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def _check_models_distinct(self) -> CrossJudgeAgreement:
        """Reject self-comparisons — two judge families means two pins."""
        if self.primary_model == self.secondary_model:
            msg = (
                "CrossJudgeAgreement requires distinct judge model pins; "
                f"got the same pin twice ({self.primary_model.model!r} @ "
                f"{self.primary_model.model_version!r})"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_agreement_consistency(self) -> CrossJudgeAgreement:
        """``observed_agreement`` / ``expected_agreement`` / ``kappa`` must agree on emptiness."""
        empty = self.n_matched == 0
        agreements_present = (
            self.observed_agreement is not None or self.expected_agreement is not None
        )
        if empty and agreements_present:
            msg = (
                "CrossJudgeAgreement: n_matched == 0 requires "
                "observed_agreement and expected_agreement to be None"
            )
            raise ValueError(msg)
        if not empty and (self.observed_agreement is None or self.expected_agreement is None):
            msg = (
                "CrossJudgeAgreement: n_matched > 0 requires both "
                "observed_agreement and expected_agreement to be set"
            )
            raise ValueError(msg)
        return self


def compute_cross_judge_kappa(
    *,
    primary_calls: Sequence[JudgeCall],
    secondary_calls: Sequence[JudgeCall],
    primary_model: JudgeModelPin,
    secondary_model: JudgeModelPin,
) -> CrossJudgeAgreement:
    """Compute Cohen's κ between two judges over their shared pairs.

    Pairs ``primary_calls`` and ``secondary_calls`` by
    ``(task_id, pair_label)``, drops swap-inconsistent or no-evidence
    rows on either side per spec §5.5 step 6 + guardrails, then computes
    Cohen's κ over the surviving picks.

    Calls present in only one judge's output are silently ignored: κ is
    only defined on paired observations, and reporting a "partial" κ
    over disjoint subsets would mislead reviewers.

    Args:
        primary_calls: All :class:`JudgeCall` rows from the primary
            (v1 OpenAI) judge for one cohort run.
        secondary_calls: All :class:`JudgeCall` rows from the secondary
            (Claude or Gemini) judge for the same cohort run.
        primary_model: Pinned model identity for the primary judge.
            Threaded into the result so the report header records both
            judges per spec §5.5 guardrails.
        secondary_model: Pinned model identity for the secondary judge.

    Returns:
        A validated :class:`CrossJudgeAgreement`. ``kappa`` is ``None``
        when the matched sample is empty or both judges' marginals
        collapse to a single category (κ undefined; see module
        docstring).

    Raises:
        ValueError: Either side contains duplicate ``(task_id,
            pair_label)`` keys (a defective upstream pair construction
            that would silently double-count calls).
    """
    primary_by_key = _index_by_pair_key(primary_calls, side="primary")
    secondary_by_key = _index_by_pair_key(secondary_calls, side="secondary")

    matched_keys = sorted(primary_by_key.keys() & secondary_by_key.keys())
    surviving: list[tuple[JudgePick, JudgePick]] = []
    dropped = 0
    for key in matched_keys:
        p_call = primary_by_key[key]
        s_call = secondary_by_key[key]
        if not _is_kept(p_call) or not _is_kept(s_call):
            dropped += 1
            continue
        surviving.append((p_call.judge_pick, s_call.judge_pick))

    if not surviving:
        return CrossJudgeAgreement(
            primary_model=primary_model,
            secondary_model=secondary_model,
            n_matched=0,
            dropped=dropped,
            observed_agreement=None,
            expected_agreement=None,
            kappa=None,
        )

    n = len(surviving)
    p_o = _observed_agreement(surviving)
    p_e = _expected_agreement(surviving)
    kappa = _kappa_from_components(p_o=p_o, p_e=p_e)
    return CrossJudgeAgreement(
        primary_model=primary_model,
        secondary_model=secondary_model,
        n_matched=n,
        dropped=dropped,
        observed_agreement=p_o,
        expected_agreement=p_e,
        kappa=kappa,
    )


# --------------------------------------------------------------------------- #
# Internals — kept separate so unit tests can pin every edge case directly.
# --------------------------------------------------------------------------- #


def _index_by_pair_key(
    calls: Iterable[JudgeCall], *, side: str
) -> dict[tuple[str, tuple[str, str]], JudgeCall]:
    """Index calls by ``(task_id, pair_label)`` and reject duplicates.

    A defective upstream pair construction that emitted the same key
    twice would silently double-count the second occurrence, so we
    raise loudly instead of last-write-wins.
    """
    out: dict[tuple[str, tuple[str, str]], JudgeCall] = {}
    for call in calls:
        key = (call.task_id, call.pair_label)
        if key in out:
            msg = (
                f"compute_cross_judge_kappa: duplicate {side} call for "
                f"task_id={call.task_id!r}, pair_label={call.pair_label!r}"
            )
            raise ValueError(msg)
        out[key] = call
    return out


def _is_kept(call: JudgeCall) -> bool:
    """Spec §5.5 step 6 + guardrails: drop swap-inconsistent / no-evidence calls."""
    return call.swap_consistent and call.evidence_cited


def _observed_agreement(picks: Sequence[tuple[JudgePick, JudgePick]]) -> float:
    """``p_o`` = fraction of paired observations where both judges agree."""
    agree = sum(1 for a, b in picks if a == b)
    return agree / len(picks)


def _expected_agreement(picks: Sequence[tuple[JudgePick, JudgePick]]) -> float:
    """``p_e`` from the per-judge marginal distributions on the matched sample.

    Cohen's κ uses the marginals **observed on the paired sample** (not a
    population prior) — this is the standard convention and the only one
    that makes ``κ = 0`` mean "no agreement beyond chance" on this run.
    """
    n = len(picks)
    primary_marginals: dict[JudgePick, int] = dict.fromkeys(_PICK_CATEGORIES, 0)
    secondary_marginals: dict[JudgePick, int] = dict.fromkeys(_PICK_CATEGORIES, 0)
    for primary_pick, secondary_pick in picks:
        primary_marginals[primary_pick] += 1
        secondary_marginals[secondary_pick] += 1
    return sum((primary_marginals[c] / n) * (secondary_marginals[c] / n) for c in _PICK_CATEGORIES)


def _kappa_from_components(*, p_o: float, p_e: float) -> float | None:
    """Cohen's κ from observed + expected agreement; ``None`` when undefined.

    Returns ``None`` when ``p_e == 1.0`` (the marginals collapse to a
    single category on the matched sample); the classical definition
    leaves κ undefined in that case and reporting it as ``1.0`` or
    ``0.0`` would silently overstate the result.
    """
    if p_e >= 1.0:
        return None
    return (p_o - p_e) / (1.0 - p_e)
