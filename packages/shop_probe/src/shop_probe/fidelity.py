"""Per-pair and cohort-level fidelity aggregation for ShopProbe.

Implements the typed contract documented in
``docs/specs/shop_arena/web_probe.md`` §5.7. Two closed pydantic models
plus pure helper functions that turn a ``(sandbox, source)`` pair of
:class:`~shop_probe.report.ProbeReport`\\ s — and an optional 6-real-shop
reference population — into the three numbers per pair (coverage gap,
surface ratio, indistinguishability) the paper reports.

The module is import-safe: no I/O, no env reads. Judge-related fields
default to ``None`` until the axis-C plumbing lands in M4 (spec §7 M4).

Aggregation conventions (kept narrow on purpose; see spec §5.7):

* ``coverage_gap[category] = source.coverage - sandbox.coverage`` —
  positive means the source is ahead of the sandbox. Both reports must
  expose the **same** set of categories; mismatch is rejected loudly so
  rubric drift between runs is not silently dropped.
* ``coverage_gap_weighted = source.coverage_weighted - sandbox.coverage_weighted``,
  in ``[-1, 1]``.
* ``surface_ratio[name] = sandbox(name) / source(name)`` over every
  field of :class:`~shop_probe.surface.metrics.SurfaceMetrics`. If both
  sides are zero the ratio is ``1.0`` (parity); if the source is zero
  but the sandbox is positive the ratio is undefined and we raise.
* ``surface_ratio_geomean`` is the geometric mean of the per-metric
  ratios. A single zero-valued ratio collapses the geomean to ``0.0``
  (matches the standard definition).
* ``sandbox_in_real_envelope[name]`` — ``True`` iff the sandbox metric
  falls inside the ``[min, max]`` envelope of ``real_population`` for
  that field. Empty when ``real_population`` is empty (M3 pilot
  scenario; the full envelope ships in M5).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from shop_probe.report import ProbeReport
from shop_probe.surface.metrics import SurfaceMetrics


class PairFidelity(BaseModel):
    """Per-pair fidelity rollup (spec §5.7).

    Three independent numbers per ``(source, sandbox)`` pair —
    :attr:`coverage_gap_weighted` (axis A), :attr:`surface_ratio_geomean`
    (axis B), :attr:`judge_accuracy_experimental` (axis C) — plus the
    per-category / per-metric breakdowns the paper figures consume.

    Per spec §5.7 we deliberately do **not** collapse the three axes
    into a single scalar; reviewers read the breakdown.

    Attributes:
        pair_id: Pair identifier, e.g. ``"pair_hardware"``. Matches the
            ``pair_id`` on both members of the underlying
            :class:`~shop_probe.targets.Pair`.
        coverage_gap: Per-category coverage gap, ``source - sandbox``.
            Positive values mean the source is ahead of the sandbox on
            that category.
        coverage_gap_weighted: Weighted-mean coverage gap across
            categories, ``∈ [-1, 1]``; ``0`` is parity.
        surface_ratio: Per-metric surface ratio, ``sandbox / source``.
            ``1.0`` is parity; defined for all 11 surface metrics.
        surface_ratio_geomean: Geometric mean of :attr:`surface_ratio`
            values, ``≥ 0``. Collapses to ``0`` if any individual
            ratio is ``0``.
        sandbox_in_real_envelope: Per-metric ``True`` iff the sandbox
            value is inside the ``[min, max]`` envelope of the real-shop
            reference population (spec §5.2). Empty until the population
            is supplied (M3 pilot has no envelope yet; M5 closes this).
        judge_accuracy_experimental: Fraction of ``(sandbox, source)``
            judge calls picked correctly. ``None`` until M4.
        judge_n_pairs: Total number of judge calls aggregated.
            ``None`` until M4.
        judge_dropped: Number of calls dropped (swap-inconsistent or
            no-evidence per spec §5.5 step 6 + guardrails). ``None``
            until M4.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str = Field(min_length=1)
    coverage_gap: dict[str, float]
    coverage_gap_weighted: float = Field(ge=-1.0, le=1.0)
    surface_ratio: dict[str, float]
    surface_ratio_geomean: float = Field(ge=0.0)
    sandbox_in_real_envelope: dict[str, bool] = Field(default_factory=dict)
    judge_accuracy_experimental: float | None = Field(default=None, ge=0.0, le=1.0)
    judge_n_pairs: int | None = Field(default=None, ge=0)
    judge_dropped: int | None = Field(default=None, ge=0)


class CohortFidelity(BaseModel):
    """Cohort-level fidelity rollup (spec §5.7).

    Aggregates the per-pair :class:`PairFidelity` rows and adds the
    cohort-level intra-real noise floor (axis C control) plus the
    real-shop reference population envelope (axes A/B).

    Attributes:
        pairs: Per-pair fidelity rows, one entry per
            :class:`~shop_probe.targets.Pair` in the cohort.
        judge_accuracy_control: Intra-real ``(real_a, real_b)`` judge
            accuracy — the noise floor against which experimental
            accuracy is interpreted. ``None`` until M4.
        judge_indistinguishability_gap:
            ``mean(experimental) - control``. ``0`` is the
            indistinguishability target (spec §5.7). ``None`` until M4.
        real_shop_population: Per-metric ``(min, max)`` envelope over
            the real-shop reference population (3 paired sources +
            3 unpaired = 6 shops in v1). Empty when no real population
            was supplied.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pairs: tuple[PairFidelity, ...] = ()
    judge_accuracy_control: float | None = Field(default=None, ge=0.0, le=1.0)
    judge_indistinguishability_gap: float | None = Field(default=None, ge=-1.0, le=1.0)
    real_shop_population: dict[str, tuple[float, float]] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Pure aggregation helpers — operate on validated schema objects only.
# --------------------------------------------------------------------------- #


def compute_pair_fidelity(
    *,
    pair_id: str,
    sandbox_report: ProbeReport,
    source_report: ProbeReport,
    real_population: Sequence[SurfaceMetrics] = (),
) -> PairFidelity:
    """Aggregate one ``(sandbox, source)`` pair into a :class:`PairFidelity`.

    Both reports must be axis A+B runs (i.e. ``surface`` populated) and
    must agree on the pair identity. Judge fields are left ``None`` —
    M4 wires them in.

    Args:
        pair_id: The pair identifier both reports must carry.
        sandbox_report: The sandbox-side :class:`ProbeReport`.
        source_report: The source-side :class:`ProbeReport`.
        real_population: Optional real-shop surface metrics used to
            compute :attr:`PairFidelity.sandbox_in_real_envelope`.
            Empty during the M3 pilot; the full 6-shop envelope ships
            in M5.

    Returns:
        A validated :class:`PairFidelity`.

    Raises:
        ValueError: The reports disagree on pair identity, either side
            is missing surface metrics, the categories don't match, or
            a surface metric has ``source == 0`` but ``sandbox > 0``.
    """
    if sandbox_report.target.kind != "sandbox":
        msg = f"sandbox_report.target.kind must be 'sandbox' (got {sandbox_report.target.kind!r})"
        raise ValueError(msg)
    if source_report.target.kind != "source":
        msg = f"source_report.target.kind must be 'source' (got {source_report.target.kind!r})"
        raise ValueError(msg)
    if sandbox_report.target.pair_id != pair_id:
        msg = (
            f"sandbox_report.target.pair_id must equal pair_id={pair_id!r} "
            f"(got {sandbox_report.target.pair_id!r})"
        )
        raise ValueError(msg)
    if source_report.target.pair_id != pair_id:
        msg = (
            f"source_report.target.pair_id must equal pair_id={pair_id!r} "
            f"(got {source_report.target.pair_id!r})"
        )
        raise ValueError(msg)
    if sandbox_report.surface is None or source_report.surface is None:
        msg = (
            "compute_pair_fidelity requires both reports to have surface "
            "metrics (run with --axes A,B)"
        )
        raise ValueError(msg)

    coverage_gap = _compute_coverage_gap(sandbox_report, source_report)
    coverage_gap_weighted = source_report.coverage_weighted - sandbox_report.coverage_weighted
    surface_ratio = _compute_surface_ratio(
        sandbox_report.surface,
        source_report.surface,
    )
    surface_ratio_geomean = _geomean(surface_ratio.values())
    sandbox_in_real_envelope = (
        _compute_envelope(sandbox_report.surface, real_population) if real_population else {}
    )

    return PairFidelity(
        pair_id=pair_id,
        coverage_gap=coverage_gap,
        coverage_gap_weighted=coverage_gap_weighted,
        surface_ratio=surface_ratio,
        surface_ratio_geomean=surface_ratio_geomean,
        sandbox_in_real_envelope=sandbox_in_real_envelope,
    )


def compute_cohort_fidelity(
    *,
    pairs: Sequence[PairFidelity],
    real_population: Sequence[SurfaceMetrics] = (),
) -> CohortFidelity:
    """Aggregate per-pair fidelity rows into a :class:`CohortFidelity`.

    Computes the per-metric ``(min, max)`` envelope over the real-shop
    reference population. Judge cohort-level fields are left ``None``
    until M4.

    Args:
        pairs: Per-pair fidelity rows, one per
            :class:`~shop_probe.targets.Pair`.
        real_population: Surface metrics for the real-shop reference
            population. Spec §5.2 specifies 6 shops (3 paired sources +
            3 unpaired) in v1; empty is allowed during M3 pilot work.

    Returns:
        A validated :class:`CohortFidelity`.
    """
    real_shop_population: dict[str, tuple[float, float]] = {}
    if real_population:
        for name in SurfaceMetrics.model_fields:
            values = [float(getattr(m, name)) for m in real_population]
            real_shop_population[name] = (min(values), max(values))

    return CohortFidelity(
        pairs=tuple(pairs),
        real_shop_population=real_shop_population,
    )


# --------------------------------------------------------------------------- #
# Internals — kept separate so unit tests can exercise edge cases directly.
# --------------------------------------------------------------------------- #


def _compute_coverage_gap(
    sandbox_report: ProbeReport,
    source_report: ProbeReport,
) -> dict[str, float]:
    """Per-category ``source - sandbox`` coverage gap (spec §5.7)."""
    sandbox_by_cat = {c.category: c.coverage for c in sandbox_report.categories}
    source_by_cat = {c.category: c.coverage for c in source_report.categories}
    if set(sandbox_by_cat) != set(source_by_cat):
        msg = (
            f"coverage_gap: category mismatch — sandbox has "
            f"{sorted(sandbox_by_cat)}, source has {sorted(source_by_cat)}"
        )
        raise ValueError(msg)
    return {
        category: source_by_cat[category] - sandbox_by_cat[category]
        for category in sorted(sandbox_by_cat)
    }


def _compute_surface_ratio(
    sandbox: SurfaceMetrics,
    source: SurfaceMetrics,
) -> dict[str, float]:
    """Per-metric ``sandbox / source`` surface ratio (spec §5.7).

    Both-zero is treated as parity (``1.0``); ``source == 0`` with
    ``sandbox > 0`` is undefined and raises (the resulting ``inf`` would
    not survive JSON round-trip and signals a defective source crawl).
    """
    out: dict[str, float] = {}
    for name in SurfaceMetrics.model_fields:
        sandbox_v = float(getattr(sandbox, name))
        source_v = float(getattr(source, name))
        if source_v == 0.0:
            if sandbox_v == 0.0:
                out[name] = 1.0
            else:
                msg = (
                    f"surface_ratio[{name!r}]: source is 0 but sandbox is "
                    f"{sandbox_v}; ratio is undefined"
                )
                raise ValueError(msg)
        else:
            out[name] = sandbox_v / source_v
    return out


def _compute_envelope(
    sandbox: SurfaceMetrics,
    real_population: Sequence[SurfaceMetrics],
) -> dict[str, bool]:
    """Per-metric ``sandbox in [min, max]`` over the real-shop population."""
    out: dict[str, bool] = {}
    for name in SurfaceMetrics.model_fields:
        values = [float(getattr(m, name)) for m in real_population]
        lo, hi = min(values), max(values)
        sandbox_v = float(getattr(sandbox, name))
        out[name] = lo <= sandbox_v <= hi
    return out


def _geomean(values: Iterable[float]) -> float:
    """Geometric mean over ``values`` (spec §5.7).

    A single ``0`` value collapses the geometric mean to ``0`` per the
    standard definition. Negative values are rejected.
    """
    seq = list(values)
    if not seq:
        msg = "_geomean: cannot compute geometric mean of empty sequence"
        raise ValueError(msg)
    if any(v < 0 for v in seq):
        msg = f"_geomean: negative values are not allowed (got {seq!r})"
        raise ValueError(msg)
    if any(v == 0 for v in seq):
        return 0.0
    return math.exp(sum(math.log(v) for v in seq) / len(seq))
