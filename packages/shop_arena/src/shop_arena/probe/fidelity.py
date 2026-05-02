"""Cohort-level fidelity rollup for ShopProbe v1.0 (spec §5.5 / §8.2).

Inputs are two populations of :class:`shop_arena.probe.report.ProbeReport` —
sandboxes and reals — emitted from the same rubric. The outputs feed
:mod:`shop_arena.probe.report_writer.tables` and the per-family headlines.

Three families, three claim shapes:

* **observation.shape / action.space** — continuous metrics per
  (page_type, modality, metric). For each tuple, report
  ``(mean_real, q1, q3, median_sandbox, U, p, cliffs_delta)``.
* **observation.info_slots / action.control_slots** — per-shop pass /
  fail per (page_type, slot_id, modality). The cohort claim is RBC
  against the real-cohort majority baseline:

  ``majority_baseline = { slot : pass_rate_real(slot) ≥ ⌈n_real/2 + 1⌉ / n_real }``

  ``RBC(shop) = |{slot ∈ baseline : shop passes}| / |baseline|``.
  Sandbox-mean RBC is compared against the leave-one-out range of
  RBC over the real cohort.
* **transition** — per (page_type, slot_id) per-bit success rates,
  sandbox vs real, no inferential test.

Mann-Whitney U and Cliff's δ are implemented locally (no scipy/numpy
dependency); the U test uses the normal approximation without tie
correction — adequate for our regime of small n on integer-valued
counts.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from shop_arena.probe.report import ProbeReport, TransitionResult
from shop_arena.probe.rubric.schema import Modality, PageType

_SHAPE_METRIC_FIELDS: Final[tuple[str, ...]] = (
    "nodes",
    "tokens",
    "actionable_count",
    "megapixels",
    "byte_size_kb",
)
"""Numeric fields on :class:`ShapeMetrics` we compare cohort-vs-cohort."""

_SPACE_METRIC_FIELDS: Final[tuple[str, ...]] = (
    "actionable_count",
    "unique_role_name_rate",
)
"""Numeric fields on :class:`ActionSpaceMetrics`."""

_TRANSITION_BITS: Final[tuple[str, ...]] = (
    "action_found",
    "action_executed",
    "state_changed",
    "state_changed_as_expected",
)
"""4-bit verdict on :class:`TransitionResult`."""


# ---------- Math helpers ---------------------------------------------------


def _median(values: Sequence[float]) -> float | None:
    """Return the median of ``values``, or ``None`` if empty."""
    if not values:
        return None
    sorted_values = sorted(values)
    n = len(sorted_values)
    mid = n // 2
    if n % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def _quartiles(values: Sequence[float]) -> tuple[float, float] | None:
    """Return ``(q1, q3)`` via linear interpolation, or ``None`` if empty.

    Uses the inclusive method (numpy default): ``q = v[k] + d * (v[k+1] - v[k])``
    where ``(n - 1) * p == k + d``.
    """
    if not values:
        return None
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0], sorted_values[0]

    def _percentile(p: float) -> float:
        position = (n - 1) * p
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return sorted_values[lower]
        weight = position - lower
        return sorted_values[lower] + weight * (sorted_values[upper] - sorted_values[lower])

    return _percentile(0.25), _percentile(0.75)


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _ranks(values: Sequence[float]) -> list[float]:
    """Average-rank assignment with tie correction."""
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = rank
        i = j + 1
    return ranks


def _normal_sf(z: float) -> float:
    """Survival function (1 - Φ) of the standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _mann_whitney(x: Sequence[float], y: Sequence[float]) -> tuple[float, float] | None:
    """Two-sided Mann-Whitney U + p-value via normal approximation.

    Returns ``None`` when either sample is empty or both samples are
    constant (no rank variance).
    """
    if not x or not y:
        return None
    combined = list(x) + list(y)
    ranks = _ranks(combined)
    n1, n2 = len(x), len(y)
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    u = min(u1, u2)

    mean_u = n1 * n2 / 2.0
    var_u = n1 * n2 * (n1 + n2 + 1) / 12.0
    if var_u <= 0.0:
        return None
    sigma = math.sqrt(var_u)
    z = (u - mean_u) / sigma
    p_value = 2.0 * _normal_sf(abs(z))
    return u, max(0.0, min(1.0, p_value))


def _cliffs_delta(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Cliff's δ ∈ [-1, 1] between two samples; ``None`` if either is empty."""
    if not x or not y:
        return None
    greater = 0
    less = 0
    for xi in x:
        for yj in y:
            if xi > yj:
                greater += 1
            elif xi < yj:
                less += 1
    total = len(x) * len(y)
    return (greater - less) / total


def cliffs_delta_label(delta: float) -> str:
    """Map δ magnitude to the Romano et al. effect-size buckets."""
    magnitude = abs(delta)
    if magnitude < 0.147:
        return "negligible"
    if magnitude < 0.33:
        return "small"
    if magnitude < 0.474:
        return "medium"
    return "large"


# ---------- Output schemas -------------------------------------------------


class ContinuousStat(BaseModel):
    """Cohort comparison row for one continuous metric on one (page_type, modality)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_type: PageType
    modality: Modality
    metric: str = Field(min_length=1)
    n_real: int = Field(ge=0)
    n_sandbox: int = Field(ge=0)
    mean_real: float | None = None
    q1_real: float | None = None
    q3_real: float | None = None
    median_sandbox: float | None = None
    u_statistic: float | None = None
    p_value: float | None = None
    cliffs_delta: float | None = None


class SlotPassRate(BaseModel):
    """One slot's real-cohort pass rate; baseline membership is derived."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_type: PageType
    slot_id: str = Field(min_length=1)
    modality: Modality
    pass_rate_real: float = Field(ge=0.0, le=1.0)
    in_baseline: bool


class SlotFamilyCoverage(BaseModel):
    """RBC rollup for one slot family (info_slots OR control_slots)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family_label: str = Field(min_length=1)  # e.g. "observation.info_slots"
    n_real: int = Field(ge=0)
    n_sandbox: int = Field(ge=0)
    quorum_k: int = Field(ge=0)
    baseline_size: int = Field(ge=0)
    slots: tuple[SlotPassRate, ...] = ()
    rbc_per_sandbox: dict[str, float] = Field(default_factory=dict)
    mean_rbc_sandbox: float | None = None
    rbc_real_loo: dict[str, float] = Field(default_factory=dict)
    min_rbc_real_loo: float | None = None
    max_rbc_real_loo: float | None = None


class TransitionRates(BaseModel):
    """Per-bit success rates for one (page_type, slot_id) transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_type: PageType
    slot_id: str = Field(min_length=1)
    n_real: int = Field(ge=0)
    n_sandbox: int = Field(ge=0)
    real_rates: dict[str, float] = Field(default_factory=dict)
    sandbox_rates: dict[str, float] = Field(default_factory=dict)


class BenchComparison(BaseModel):
    """Aggregate cohort-vs-cohort comparison consumed by the report writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric_version: str = Field(min_length=1)
    rubric_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    n_real: int = Field(ge=0)
    n_sandbox: int = Field(ge=0)

    shape_stats: tuple[ContinuousStat, ...] = ()
    space_stats: tuple[ContinuousStat, ...] = ()

    info_slots: SlotFamilyCoverage
    control_slots: SlotFamilyCoverage

    transitions: tuple[TransitionRates, ...] = ()

    mean_modality_consistency_sandbox: dict[PageType, float] = Field(
        default_factory=lambda: {}
    )
    mean_modality_consistency_real: dict[PageType, float] = Field(
        default_factory=lambda: {}
    )


# ---------- Continuous-metric collection ----------------------------------


def _collect_shape_values(
    reports: Sequence[ProbeReport],
    page_type: PageType,
    modality: Modality,
    metric: str,
) -> list[float]:
    out: list[float] = []
    for report in reports:
        modal = report.observation.shape.get(page_type, {}).get(modality)
        if modal is None:
            continue
        value = getattr(modal, metric, None)
        if value is not None:
            out.append(float(value))
    return out


def _collect_space_values(
    reports: Sequence[ProbeReport],
    page_type: PageType,
    modality: Modality,
    metric: str,
) -> list[float]:
    out: list[float] = []
    for report in reports:
        modal = report.action.space.get(page_type, {}).get(modality)
        if modal is None:
            continue
        value = getattr(modal, metric, None)
        if value is not None:
            out.append(float(value))
    return out


def _continuous_stats(
    sandbox: Sequence[ProbeReport],
    real: Sequence[ProbeReport],
    page_types: Sequence[PageType],
    modalities: Sequence[Modality],
    metrics: Sequence[str],
    *,
    space: bool,
) -> tuple[ContinuousStat, ...]:
    rows: list[ContinuousStat] = []
    collect = _collect_space_values if space else _collect_shape_values
    for page_type in page_types:
        for modality in modalities:
            for metric in metrics:
                real_values = collect(real, page_type, modality, metric)
                sandbox_values = collect(sandbox, page_type, modality, metric)
                if not real_values and not sandbox_values:
                    continue
                quartiles = _quartiles(real_values)
                u_p = _mann_whitney(real_values, sandbox_values)
                rows.append(
                    ContinuousStat(
                        page_type=page_type,
                        modality=modality,
                        metric=metric,
                        n_real=len(real_values),
                        n_sandbox=len(sandbox_values),
                        mean_real=_mean(real_values),
                        q1_real=quartiles[0] if quartiles else None,
                        q3_real=quartiles[1] if quartiles else None,
                        median_sandbox=_median(sandbox_values),
                        u_statistic=u_p[0] if u_p else None,
                        p_value=u_p[1] if u_p else None,
                        cliffs_delta=_cliffs_delta(real_values, sandbox_values),
                    )
                )
    return tuple(rows)


# ---------- Slot RBC rollup ------------------------------------------------


_SlotKey = tuple[PageType, str, Modality]
"""Stable identifier for a single per-modality slot judgment."""


def _slot_pass_map(
    report: ProbeReport,
    *,
    family: str,
) -> dict[_SlotKey, bool]:
    """Return ``{slot_key: present}`` for a single report's slot judgments.

    ``family`` selects ``"info_slots"`` (observation) or
    ``"control_slots"`` (action). Missing entries are simply absent —
    callers must distinguish "judged false" from "not judged".
    """
    out: dict[_SlotKey, bool] = {}
    if family == "info_slots":
        block = report.observation.info_slots
    elif family == "control_slots":
        block = report.action.control_slots
    else:  # pragma: no cover - defensive
        msg = f"unknown slot family {family!r}"
        raise ValueError(msg)
    for page_type, slots in block.items():
        for slot_id, modal in slots.items():
            for modality, verdict in modal.items():
                out[(page_type, slot_id, modality)] = verdict.present
    return out


def _all_slot_keys(report_groups: Iterable[Sequence[ProbeReport]], family: str) -> set[_SlotKey]:
    """Union of slot keys judged anywhere across the supplied groups."""
    seen: set[_SlotKey] = set()
    for group in report_groups:
        for report in group:
            seen.update(_slot_pass_map(report, family=family).keys())
    return seen


def _quorum_k(n_real: int) -> int:
    """Spec §8.2 majority quorum: ``⌈n_real / 2 + 1⌉``."""
    if n_real <= 0:
        return 1
    return math.ceil(n_real / 2 + 1)


def _slot_pass_rate(
    reports: Sequence[ProbeReport],
    family: str,
    key: _SlotKey,
) -> float:
    """Fraction of ``reports`` whose verdict marks ``key`` as present.

    Reports without the slot judgment are treated as ``not present`` —
    the rubric is the contract for what *should* exist; absence is
    failure.
    """
    if not reports:
        return 0.0
    passes = 0
    for report in reports:
        passes += int(_slot_pass_map(report, family=family).get(key, False))
    return passes / len(reports)


def _rbc(report: ProbeReport, family: str, baseline: Sequence[_SlotKey]) -> float:
    if not baseline:
        return 0.0
    pass_map = _slot_pass_map(report, family=family)
    passed = sum(1 for key in baseline if pass_map.get(key, False))
    return passed / len(baseline)


def _slot_family_coverage(
    sandbox: Sequence[ProbeReport],
    real: Sequence[ProbeReport],
    *,
    family: str,
    family_label: str,
) -> SlotFamilyCoverage:
    n_real = len(real)
    n_sandbox = len(sandbox)
    keys = sorted(_all_slot_keys((sandbox, real), family))
    quorum = _quorum_k(n_real)
    quorum_rate = quorum / n_real if n_real else 1.1  # never satisfied
    slot_rows: list[SlotPassRate] = []
    baseline: list[_SlotKey] = []
    for key in keys:
        rate = _slot_pass_rate(real, family, key)
        in_base = n_real > 0 and rate >= quorum_rate - 1e-9
        slot_rows.append(
            SlotPassRate(
                page_type=key[0],
                slot_id=key[1],
                modality=key[2],
                pass_rate_real=rate,
                in_baseline=in_base,
            )
        )
        if in_base:
            baseline.append(key)

    rbc_sandbox = {report.target.name: _rbc(report, family, baseline) for report in sandbox}
    mean_rbc_sandbox = _mean(list(rbc_sandbox.values()))

    # Leave-one-out: recompute baseline excluding shop ``r``, then RBC of
    # ``r`` against that reduced baseline.
    rbc_real_loo: dict[str, float] = {}
    for held_out in real:
        others = [r for r in real if r.target.name != held_out.target.name]
        held_quorum = _quorum_k(len(others))
        held_rate = held_quorum / len(others) if others else 1.1
        loo_baseline = [
            key for key in keys if _slot_pass_rate(others, family, key) >= held_rate - 1e-9
        ]
        rbc_real_loo[held_out.target.name] = _rbc(held_out, family, loo_baseline)
    loo_values = list(rbc_real_loo.values())
    return SlotFamilyCoverage(
        family_label=family_label,
        n_real=n_real,
        n_sandbox=n_sandbox,
        quorum_k=quorum,
        baseline_size=len(baseline),
        slots=tuple(slot_rows),
        rbc_per_sandbox=rbc_sandbox,
        mean_rbc_sandbox=mean_rbc_sandbox,
        rbc_real_loo=rbc_real_loo,
        min_rbc_real_loo=min(loo_values) if loo_values else None,
        max_rbc_real_loo=max(loo_values) if loo_values else None,
    )


# ---------- Transition rates ----------------------------------------------


def _transition_keys(reports: Iterable[ProbeReport]) -> set[tuple[PageType, str]]:
    seen: set[tuple[PageType, str]] = set()
    for report in reports:
        for page_type, slots in report.transition.items():
            for slot_id in slots.keys():
                seen.add((page_type, slot_id))
    return seen


def _bit_rates(
    reports: Sequence[ProbeReport],
    page_type: PageType,
    slot_id: str,
) -> tuple[dict[str, float], int]:
    """Return ``({bit: pass_rate}, n_present)`` for one transition.

    Reports that have no record for the (page_type, slot_id) pair are
    excluded from the denominator.
    """
    rows: list[TransitionResult] = []
    for report in reports:
        result = report.transition.get(page_type, {}).get(slot_id)
        if result is not None:
            rows.append(result)
    if not rows:
        return ({bit: 0.0 for bit in _TRANSITION_BITS}, 0)
    rates = {
        bit: sum(1 for r in rows if getattr(r, bit)) / len(rows) for bit in _TRANSITION_BITS
    }
    return (rates, len(rows))


def _transition_rates(
    sandbox: Sequence[ProbeReport],
    real: Sequence[ProbeReport],
) -> tuple[TransitionRates, ...]:
    keys = sorted(_transition_keys((*sandbox, *real)))
    rows: list[TransitionRates] = []
    for page_type, slot_id in keys:
        real_rates, n_real = _bit_rates(real, page_type, slot_id)
        sandbox_rates, n_sandbox = _bit_rates(sandbox, page_type, slot_id)
        rows.append(
            TransitionRates(
                page_type=page_type,
                slot_id=slot_id,
                n_real=n_real,
                n_sandbox=n_sandbox,
                real_rates=real_rates,
                sandbox_rates=sandbox_rates,
            )
        )
    return tuple(rows)


# ---------- Modality-consistency rollup ------------------------------------


def _mc_means(reports: Sequence[ProbeReport]) -> dict[PageType, float]:
    """Per-page-type mean of ``modality_consistency`` across ``reports``."""
    accum: dict[PageType, list[float]] = defaultdict(list)
    for report in reports:
        for page_type, value in report.modality_consistency.items():
            accum[page_type].append(value)
    return {pt: sum(vals) / len(vals) for pt, vals in accum.items() if vals}


# ---------- Public entry point --------------------------------------------


def _ensure_same_rubric(reports: Sequence[ProbeReport]) -> tuple[str, str]:
    """Return ``(rubric_version, rubric_hash)`` shared by every report."""
    if not reports:
        msg = "compare_cohorts: at least one report (sandbox or real) is required"
        raise ValueError(msg)
    versions = {r.rubric_version for r in reports}
    hashes = {r.rubric_hash for r in reports}
    if len(versions) != 1 or len(hashes) != 1:
        msg = (
            f"compare_cohorts: reports use mismatched rubrics "
            f"(versions={sorted(versions)}, hashes={sorted(hashes)})"
        )
        raise ValueError(msg)
    return versions.pop(), hashes.pop()


def compare_cohorts(
    *,
    sandbox: Sequence[ProbeReport],
    real: Sequence[ProbeReport],
) -> BenchComparison:
    """Aggregate sandbox-vs-real fidelity into a single typed comparison.

    Args:
        sandbox: ProbeReports for the sandbox cohort.
        real: ProbeReports for the real cohort.

    Returns:
        :class:`BenchComparison` consumed by
        :mod:`shop_arena.probe.report_writer`.

    Raises:
        ValueError: When the two cohorts together yield no reports, or
            when reports were emitted from differing rubric versions /
            hashes (cohort comparison requires identical rubric).
    """
    rubric_version, rubric_hash = _ensure_same_rubric((*sandbox, *real))

    page_types: tuple[PageType, ...] = ("homepage", "collection", "product", "search", "cart")
    modalities: tuple[Modality, ...] = ("a11y", "screenshot")

    shape_stats = _continuous_stats(
        sandbox, real, page_types, modalities, _SHAPE_METRIC_FIELDS, space=False
    )
    # action.space is a11y-only in v1.0; still pass both modalities — empty
    # screenshot rows are filtered inside _continuous_stats.
    space_stats = _continuous_stats(
        sandbox, real, page_types, modalities, _SPACE_METRIC_FIELDS, space=True
    )

    info_coverage = _slot_family_coverage(
        sandbox, real, family="info_slots", family_label="observation.info_slots"
    )
    control_coverage = _slot_family_coverage(
        sandbox, real, family="control_slots", family_label="action.control_slots"
    )

    transitions = _transition_rates(sandbox, real)

    return BenchComparison(
        rubric_version=rubric_version,
        rubric_hash=rubric_hash,
        n_real=len(real),
        n_sandbox=len(sandbox),
        shape_stats=shape_stats,
        space_stats=space_stats,
        info_slots=info_coverage,
        control_slots=control_coverage,
        transitions=transitions,
        mean_modality_consistency_sandbox=_mc_means(sandbox),
        mean_modality_consistency_real=_mc_means(real),
    )


__all__ = [
    "BenchComparison",
    "ContinuousStat",
    "SlotFamilyCoverage",
    "SlotPassRate",
    "TransitionRates",
    "cliffs_delta_label",
    "compare_cohorts",
]
