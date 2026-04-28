"""Human-judge calibration of the v1.1 Likert judge (T7.3 — spec §5.9 + §7 M7).

The blinded pairwise judge (spec §5.5) and the v1.1 Likert quality judge
(spec §5.9, T7.2) both run an LLM against anonymized trajectories. Spec
§5.9 + §7 M7 promote a **~50-trace human-judge calibration** to a
v1.1 stretch deliverable: an external rater scores the same anonymized
trajectories on the same Likert dimensions, and the report carries the
**Spearman ρ between human and LLM judge per dimension** as the gate
metric (spec §7 M7 stretch + impl T7.3 check).

This module owns the aggregation layer: given two sequences —
:class:`HumanLikertCall` rows from a pinned human rater and
:class:`shop_probe.report.LikertCall` rows from the LLM judge — paired by
``(task_id, target_label)``, it emits :class:`HumanCalibration`, a closed
pydantic record whose headline number is **Spearman ρ per
:data:`shop_probe.report.LikertDimension`**.

Pairing semantics:

* Calls match when their ``(task_id, target_label)`` tuples are equal.
  This assumes the human rated the **same anonymized trajectories** the
  LLM judge saw; shared upstream wiring (the pinned trajectory dump per
  trace) guarantees this in production.
* :class:`shop_probe.report.LikertCall` rows flagged
  ``evidence_cited=False`` are dropped per spec §5.5 guardrails before ρ
  is computed. They are counted into :attr:`HumanCalibration.dropped`.
* Unmatched calls (present in only one side's output) are ignored —
  Spearman ρ is only defined over a paired sample.
* Duplicate ``(task_id, target_label)`` keys on either side raise; a
  defective upstream pair construction would silently double-count rows.

Spearman ρ formula:

* Spearman ρ is the Pearson correlation of fractional ranks. Ties are
  broken by averaging — the standard convention for ordinal Likert data.
* The correlation is computed independently per
  :data:`shop_probe.report.LikertDimension` so each dimension's
  agreement is reported on its own (per impl T7.3 check).

Edge cases:

* ``n_matched < 2`` — Spearman ρ is undefined; the per-dimension
  ``spearman_rho`` is ``None``.
* All scores constant on either side — the ranks collapse, the variance
  is zero, and Pearson is undefined; ``spearman_rho`` is ``None``. This
  is the conservative reporting convention: a constant-rank judge
  carries no signal.

The module is import-safe — no I/O at import time.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shop_probe.report import (
    LIKERT_DIMENSIONS,
    JudgeModelPin,
    LikertCall,
    LikertDimension,
)

_MIN_PAIRS_FOR_RHO: Final[int] = 2
"""Minimum paired sample size for Spearman ρ to be defined."""


class HumanLikertCall(BaseModel):
    """One human Likert rating on a single anonymized trajectory (T7.3, spec §5.9).

    Mirrors :class:`shop_probe.report.LikertCall` for the per-trace +
    per-dimension scores but drops the LLM-only metadata
    (``prompt_hash``, ``response_text``) and adds an explicit
    :attr:`rater_id` so the report attributes the calibration to a
    specific human (or, for aggregated raters, an explicit aggregate id
    like ``"human_avg"``).

    The schema deliberately exposes one explicit field per dimension
    (rather than a ``dict[LikertDimension, int]``) so pyright in strict
    mode pins each rating's ``[1, 5]`` constraint at the field level and
    so per-dimension paper figures pull a single column without re-keying
    a dict — same convention as :class:`shop_probe.report.LikertCall`.

    Attributes:
        task_id: Identifier of the judge task from
            ``judge/tasks/v1.yaml`` (spec §5.5 step 1; shared with the
            pairwise + Likert judges).
        target_label: ``Target.label`` of the storefront the trajectory
            was recorded on. Calibration is per-trajectory, so the
            target is named explicitly — same as
            :class:`shop_probe.report.LikertCall`.
        rater_id: Stable identifier for the human rater (or the
            aggregation strategy when multiple humans are averaged into
            one row, e.g. ``"human_avg"``).
        visual_coherence: 1..5 score on the visual-coherence dimension
            (theme consistency, layout polish).
        copy_realism: 1..5 score on the copy-realism dimension
            (product copy, microcopy, error strings).
        error_plausibility: 1..5 score on the error-plausibility
            dimension (failure modes look like real-world Shopify
            failures).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    rater_id: str = Field(min_length=1)
    visual_coherence: int = Field(ge=1, le=5)
    copy_realism: int = Field(ge=1, le=5)
    error_plausibility: int = Field(ge=1, le=5)

    def score(self, dimension: LikertDimension) -> int:
        """Return this rating's score on ``dimension`` (1..5)."""
        return int(getattr(self, dimension))


class DimensionCalibration(BaseModel):
    """Per-dimension human / LLM Spearman ρ summary (T7.3, spec §5.9).

    One :class:`DimensionCalibration` per :data:`LikertDimension` is
    carried by :class:`HumanCalibration`. ``spearman_rho`` is ``None``
    when the correlation is undefined on the matched sample (see module
    docstring); ``n_matched`` documents the sample size that fed ρ so
    reviewers can read the calibration confidence at a glance.

    Attributes:
        dimension: The :data:`LikertDimension` this row scores.
        n_matched: Count of paired ``(task_id, target_label)`` keys that
            survived the LLM evidence-cited filter from spec §5.5
            guardrails and contributed to ``spearman_rho``.
        spearman_rho: Spearman rank correlation in ``[-1, 1]``, or
            ``None`` when undefined (``n_matched < 2`` or constant
            scores on either side).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: LikertDimension
    n_matched: int = Field(ge=0)
    spearman_rho: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def _check_rho_consistency(self) -> DimensionCalibration:
        """Reject ``spearman_rho`` set when the sample is too small for ρ."""
        if self.n_matched < _MIN_PAIRS_FOR_RHO and self.spearman_rho is not None:
            msg = (
                "DimensionCalibration: spearman_rho must be None when "
                f"n_matched < {_MIN_PAIRS_FOR_RHO}; got n_matched="
                f"{self.n_matched}, spearman_rho={self.spearman_rho!r}"
            )
            raise ValueError(msg)
        return self


class HumanCalibration(BaseModel):
    """Cohort-level human-judge calibration of the v1.1 Likert judge (T7.3, spec §5.9).

    Closed schema so the v1.1 stretch result has a stable contract a
    paper-supplement table can pull from. The headline numbers are the
    per-dimension Spearman ρ values in :attr:`correlations`;
    :attr:`n_matched` and :attr:`dropped` document the sample size and
    how many calls were excluded (per spec §5.5 guardrails).

    Attributes:
        rater_id: Stable identifier of the human rater (or aggregation
            strategy) that produced the calibration sample. Mirrors
            :attr:`HumanLikertCall.rater_id`.
        judge_model: Pinned model identity for the LLM judge being
            calibrated against — typically the v1.1 Likert judge's
            :class:`JudgeModelPin`. Threaded into the result so the
            report header records which judge revision the human ρ
            attributes to, per spec §5.5 guardrails.
        n_matched: Count of paired ``(task_id, target_label)`` calls
            that survived the evidence-cited filter and contributed to
            every per-dimension ρ.
        dropped: Count of pair-keys that matched across both sides but
            were dropped because the LLM call was flagged
            ``evidence_cited=False`` (spec §5.5 guardrails).
        correlations: One :class:`DimensionCalibration` per
            :data:`LikertDimension`, in declaration order. The schema
            requires every dimension exactly once so paper supplement
            tables can pull a per-dimension column without re-keying a
            dict.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rater_id: str = Field(min_length=1)
    judge_model: JudgeModelPin
    n_matched: int = Field(ge=0)
    dropped: int = Field(ge=0)
    correlations: tuple[DimensionCalibration, ...]

    @model_validator(mode="after")
    def _check_correlations_complete(self) -> HumanCalibration:
        """Require exactly one entry per :data:`LikertDimension`, in order."""
        seen: list[LikertDimension] = [c.dimension for c in self.correlations]
        expected: tuple[LikertDimension, ...] = get_args(LikertDimension)
        if tuple(seen) != expected:
            msg = (
                "HumanCalibration: correlations must list every "
                f"LikertDimension exactly once in declaration order; "
                f"got {seen!r}, expected {list(expected)!r}"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_correlations_n_matched(self) -> HumanCalibration:
        """Per-dimension ``n_matched`` must equal the cohort-level ``n_matched``."""
        for entry in self.correlations:
            if entry.n_matched != self.n_matched:
                msg = (
                    "HumanCalibration: correlations["
                    f"{entry.dimension!r}].n_matched={entry.n_matched} "
                    f"disagrees with HumanCalibration.n_matched={self.n_matched}"
                )
                raise ValueError(msg)
        return self


def compute_human_calibration(
    *,
    human_calls: Sequence[HumanLikertCall],
    llm_calls: Sequence[LikertCall],
    judge_model: JudgeModelPin,
    rater_id: str,
) -> HumanCalibration:
    """Compute per-dimension Spearman ρ between a human rater and the LLM judge.

    Pairs ``human_calls`` and ``llm_calls`` by ``(task_id, target_label)``,
    drops LLM rows flagged ``evidence_cited=False`` per spec §5.5
    guardrails, then computes Spearman ρ per :data:`LikertDimension` over
    the surviving paired scores.

    Calls present in only one side's output are silently ignored:
    Spearman ρ is only defined on paired observations, and reporting a
    "partial" ρ over disjoint subsets would mislead reviewers — same
    convention as :func:`shop_probe.judge.kappa.compute_cross_judge_kappa`.

    Args:
        human_calls: All :class:`HumanLikertCall` rows from one human
            rater (or one aggregation strategy) for the calibration
            sample. Every row's ``rater_id`` must equal ``rater_id``;
            mixed rater ids would silently average across raters
            without exposing it in the report.
        llm_calls: All :class:`LikertCall` rows from the LLM judge for
            the same trajectories. Calls already discarded by
            :class:`shop_probe.judge.likert.LikertJudge`
            (parse-error, missing-dimension) do not appear here; rows
            with ``evidence_cited=False`` are filtered defensively.
        judge_model: Pinned model identity for the LLM judge being
            calibrated against. Threaded into the result.
        rater_id: Stable identifier for the human rater. Required so
            empty-sample calibrations still attribute to a rater, and
            so the schema rejects mixed rater ids in
            ``human_calls``.

    Returns:
        A validated :class:`HumanCalibration` with one
        :class:`DimensionCalibration` per :data:`LikertDimension`.
        ``spearman_rho`` is ``None`` per dimension when ρ is undefined
        on the matched sample (see module docstring).

    Raises:
        ValueError: ``human_calls`` mixes multiple ``rater_id`` values,
            disagrees with the ``rater_id`` argument, or either side
            contains duplicate ``(task_id, target_label)`` keys.
    """
    _check_rater_id_consistency(human_calls=human_calls, rater_id=rater_id)
    human_by_key = _index_human_by_pair_key(human_calls)
    llm_by_key = _index_llm_by_pair_key(llm_calls)

    matched_keys = sorted(human_by_key.keys() & llm_by_key.keys())
    surviving: list[tuple[HumanLikertCall, LikertCall]] = []
    dropped = 0
    for key in matched_keys:
        h = human_by_key[key]
        m = llm_by_key[key]
        if not _is_kept(m):
            dropped += 1
            continue
        surviving.append((h, m))

    n = len(surviving)
    correlations = tuple(
        DimensionCalibration(
            dimension=dimension,
            n_matched=n,
            spearman_rho=_spearman_rho(
                [float(h.score(dimension)) for h, _ in surviving],
                [float(m.score(dimension)) for _, m in surviving],
            ),
        )
        for dimension in LIKERT_DIMENSIONS
    )
    return HumanCalibration(
        rater_id=rater_id,
        judge_model=judge_model,
        n_matched=n,
        dropped=dropped,
        correlations=correlations,
    )


# --------------------------------------------------------------------------- #
# Internals — kept separate so unit tests can pin every edge case directly.
# --------------------------------------------------------------------------- #


def _check_rater_id_consistency(*, human_calls: Iterable[HumanLikertCall], rater_id: str) -> None:
    """Reject mixed rater ids; reject any row whose rater id ≠ ``rater_id``."""
    seen: set[str] = set()
    for call in human_calls:
        if call.rater_id != rater_id:
            msg = (
                "compute_human_calibration: human_calls contains rater_id="
                f"{call.rater_id!r}, expected {rater_id!r}"
            )
            raise ValueError(msg)
        seen.add(call.rater_id)
    if len(seen) > 1:
        # Defensive: the per-row check above already rejects mismatches, so
        # this branch is unreachable in normal use. Kept for clarity.
        msg = (
            "compute_human_calibration: human_calls mixes rater ids "
            f"{sorted(seen)!r}; pass exactly one rater per calibration"
        )
        raise ValueError(msg)


def _index_human_by_pair_key(
    calls: Iterable[HumanLikertCall],
) -> dict[tuple[str, str], HumanLikertCall]:
    """Index human calls by ``(task_id, target_label)`` and reject duplicates."""
    out: dict[tuple[str, str], HumanLikertCall] = {}
    for call in calls:
        key = (call.task_id, call.target_label)
        if key in out:
            msg = (
                "compute_human_calibration: duplicate human call for "
                f"task_id={call.task_id!r}, target_label={call.target_label!r}"
            )
            raise ValueError(msg)
        out[key] = call
    return out


def _index_llm_by_pair_key(
    calls: Iterable[LikertCall],
) -> dict[tuple[str, str], LikertCall]:
    """Index LLM calls by ``(task_id, target_label)`` and reject duplicates."""
    out: dict[tuple[str, str], LikertCall] = {}
    for call in calls:
        key = (call.task_id, call.target_label)
        if key in out:
            msg = (
                "compute_human_calibration: duplicate llm call for "
                f"task_id={call.task_id!r}, target_label={call.target_label!r}"
            )
            raise ValueError(msg)
        out[key] = call
    return out


def _is_kept(call: LikertCall) -> bool:
    """Spec §5.5 guardrails: drop no-evidence calls before ρ."""
    return call.evidence_cited


def _spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman ρ on paired scores; ``None`` when undefined.

    Spearman ρ is the Pearson correlation of fractional ranks. Ties are
    broken by averaging (the standard convention for ordinal Likert
    data). Returns ``None`` when ``len(xs) < 2`` or when either side has
    zero rank variance (all scores identical), where ρ is classically
    undefined.
    """
    if len(xs) != len(ys):  # pragma: no cover — caller invariant.
        msg = f"_spearman_rho: length mismatch {len(xs)} vs {len(ys)}"
        raise ValueError(msg)
    if len(xs) < _MIN_PAIRS_FOR_RHO:
        return None
    x_ranks = _fractional_ranks(xs)
    y_ranks = _fractional_ranks(ys)
    return _pearson(x_ranks, y_ranks)


def _fractional_ranks(values: Sequence[float]) -> list[float]:
    """Return 1-indexed fractional ranks (ties → averaged ranks)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # 1-indexed average of the tied positions [i+1, ..., j+1].
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation; ``None`` when either side has zero variance."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0.0 or var_y == 0.0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    rho = cov / (var_x**0.5 * var_y**0.5)
    # Clamp tiny floating-point excursions outside [-1, 1] before pydantic sees them.
    if rho > 1.0:
        return 1.0
    if rho < -1.0:
        return -1.0
    return rho
