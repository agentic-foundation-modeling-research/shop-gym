"""Group-level fidelity aggregation for ShopProbe.

Two closed pydantic models plus pure helper functions that turn two flat
populations of :class:`~shop_probe.report.ProbeReport` — sandbox group
and real group — into a single group-vs-group :class:`BenchComparison`.

The module is import-safe: no I/O, no env reads.

Aggregation conventions:

* ``coverage_per_axis_mean`` — arithmetic mean of per-category coverage
  across the group. Both groups must expose the **same** set of
  categories; mismatch is rejected loudly.
* ``coverage_weighted_mean`` — arithmetic mean of
  :attr:`~shop_probe.report.ProbeReport.coverage_weighted` across the
  group.
* ``surface_metric_means[name]`` / ``surface_metric_envelope[name]`` —
  per-metric mean and ``(min, max)`` envelope across the group's
  populated :class:`~shop_probe.surface.metrics.SurfaceMetrics` rows.
* ``coverage_gap_weighted = real.coverage_weighted_mean -
  sandbox.coverage_weighted_mean``.
* ``surface_ratio[name] = sandbox.mean / real.mean`` per metric.
* ``sandbox_in_real_envelope[name][metric]`` — for each sandbox shop,
  whether its per-metric value falls inside the real-group envelope.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from shop_probe.report import ProbeReport
from shop_probe.surface.metrics import SurfaceMetrics
from shop_probe.targets import TargetLabel


class GroupSummary(BaseModel):
    """Per-group rollup over a flat population of reports.

    Attributes:
        label: Group identifier (``"sandbox"`` or ``"real"``).
        n_shops: Number of reports in the group.
        coverage_weighted_mean: Arithmetic mean of
            :attr:`~shop_probe.report.ProbeReport.coverage_weighted`.
        coverage_per_axis_mean: Per-category coverage mean across the
            group.
        surface_metric_means: Per-metric mean across populated
            :class:`SurfaceMetrics` rows.
        surface_metric_envelope: Per-metric ``(min, max)`` envelope
            across populated :class:`SurfaceMetrics` rows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: TargetLabel
    n_shops: int = Field(ge=0)
    coverage_weighted_mean: float = Field(ge=0.0, le=1.0)
    coverage_per_axis_mean: dict[str, float]
    surface_metric_means: dict[str, float]
    surface_metric_envelope: dict[str, tuple[float, float]]


class BenchComparison(BaseModel):
    """Group-vs-group bench comparison.

    Attributes:
        sandbox: Sandbox-group rollup.
        real: Real-group rollup.
        coverage_gap_weighted: ``real.coverage_weighted_mean -
            sandbox.coverage_weighted_mean``.
        coverage_gap_per_axis: Per-category ``real.mean -
            sandbox.mean``.
        surface_ratio: Per-metric ``sandbox.mean / real.mean``.
        sandbox_in_real_envelope: Per-sandbox-name ``metric -> bool``
            describing whether each sandbox metric falls inside the
            real-group envelope.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sandbox: GroupSummary
    real: GroupSummary
    coverage_gap_weighted: float = Field(ge=-1.0, le=1.0)
    coverage_gap_per_axis: dict[str, float]
    surface_ratio: dict[str, float]
    sandbox_in_real_envelope: dict[str, dict[str, bool]]


def compute_bench_comparison(
    sandbox_reports: Sequence[ProbeReport],
    real_reports: Sequence[ProbeReport],
) -> BenchComparison:
    """Aggregate two report populations into a :class:`BenchComparison`.

    Both groups must be non-empty and must agree on the set of category
    names exposed in :attr:`ProbeReport.categories`. Reports without
    ``surface`` populated contribute to coverage but are skipped silently
    for surface aggregates.

    Args:
        sandbox_reports: Reports for sandbox shops. Every entry must
            carry ``target.label == "sandbox"``.
        real_reports: Reports for real shops. Every entry must carry
            ``target.label == "real"``.

    Returns:
        A validated :class:`BenchComparison`.

    Raises:
        ValueError: A group is empty, a target's ``label`` disagrees
            with its group, the two groups expose different category
            sets, or a per-metric ``sandbox / real`` ratio would divide
            by zero with non-zero numerator.
    """
    if not sandbox_reports:
        msg = "compute_bench_comparison: sandbox_reports must be non-empty"
        raise ValueError(msg)
    if not real_reports:
        msg = "compute_bench_comparison: real_reports must be non-empty"
        raise ValueError(msg)

    _check_labels(sandbox_reports, expected="sandbox")
    _check_labels(real_reports, expected="real")

    sandbox_summary = _summarize_group("sandbox", sandbox_reports)
    real_summary = _summarize_group("real", real_reports)

    if set(sandbox_summary.coverage_per_axis_mean) != set(real_summary.coverage_per_axis_mean):
        msg = (
            "compute_bench_comparison: category mismatch — "
            f"sandbox has {sorted(sandbox_summary.coverage_per_axis_mean)}, "
            f"real has {sorted(real_summary.coverage_per_axis_mean)}"
        )
        raise ValueError(msg)

    coverage_gap_per_axis = {
        category: real_summary.coverage_per_axis_mean[category]
        - sandbox_summary.coverage_per_axis_mean[category]
        for category in sorted(sandbox_summary.coverage_per_axis_mean)
    }
    coverage_gap_weighted = (
        real_summary.coverage_weighted_mean - sandbox_summary.coverage_weighted_mean
    )

    surface_ratio = _surface_ratio(
        sandbox_summary.surface_metric_means,
        real_summary.surface_metric_means,
    )
    sandbox_in_real_envelope = _sandbox_in_real_envelope(
        sandbox_reports, real_summary.surface_metric_envelope
    )

    return BenchComparison(
        sandbox=sandbox_summary,
        real=real_summary,
        coverage_gap_weighted=coverage_gap_weighted,
        coverage_gap_per_axis=coverage_gap_per_axis,
        surface_ratio=surface_ratio,
        sandbox_in_real_envelope=sandbox_in_real_envelope,
    )


# --------------------------------------------------------------------------- #
# Internals.
# --------------------------------------------------------------------------- #


def _check_labels(reports: Sequence[ProbeReport], *, expected: TargetLabel) -> None:
    """Reject reports whose ``target.label`` disagrees with the group."""
    for report in reports:
        if report.target.label != expected:
            msg = (
                f"compute_bench_comparison: report for {report.target.name!r} "
                f"has label={report.target.label!r}; expected {expected!r}"
            )
            raise ValueError(msg)


def _summarize_group(label: TargetLabel, reports: Sequence[ProbeReport]) -> GroupSummary:
    """Reduce one group of reports into a :class:`GroupSummary`."""
    n = len(reports)
    coverage_weighted_mean = sum(r.coverage_weighted for r in reports) / n
    coverage_per_axis_mean = _coverage_per_axis_mean(reports)
    surfaces = tuple(r.surface for r in reports if r.surface is not None)
    surface_metric_means, surface_metric_envelope = _surface_aggregates(surfaces)

    return GroupSummary(
        label=label,
        n_shops=n,
        coverage_weighted_mean=coverage_weighted_mean,
        coverage_per_axis_mean=coverage_per_axis_mean,
        surface_metric_means=surface_metric_means,
        surface_metric_envelope=surface_metric_envelope,
    )


def _coverage_per_axis_mean(reports: Sequence[ProbeReport]) -> dict[str, float]:
    """Per-category coverage mean across the group.

    Every report must expose the same category set; mismatch is rejected
    loudly so rubric drift is not silently dropped.
    """
    if not reports:
        return {}
    category_set: set[str] | None = None
    for report in reports:
        cats = {c.category for c in report.categories}
        if category_set is None:
            category_set = cats
            continue
        if cats != category_set:
            msg = (
                "_coverage_per_axis_mean: category mismatch within group — "
                f"{report.target.name!r} has {sorted(cats)}, "
                f"earlier reports had {sorted(category_set)}"
            )
            raise ValueError(msg)
    if category_set is None:
        return {}
    out: dict[str, float] = {}
    for category in sorted(category_set):
        values = [next(c.coverage for c in r.categories if c.category == category) for r in reports]
        out[category] = sum(values) / len(values)
    return out


def _surface_aggregates(
    surfaces: Sequence[SurfaceMetrics],
) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
    """Per-metric mean and ``(min, max)`` envelope over populated rows."""
    means: dict[str, float] = {}
    envelope: dict[str, tuple[float, float]] = {}
    if not surfaces:
        return means, envelope
    for name in SurfaceMetrics.model_fields:
        values = [float(getattr(s, name)) for s in surfaces]
        means[name] = sum(values) / len(values)
        envelope[name] = (min(values), max(values))
    return means, envelope


def _surface_ratio(
    sandbox_means: dict[str, float],
    real_means: dict[str, float],
) -> dict[str, float]:
    """Per-metric ``sandbox / real`` ratio.

    ``real == 0`` with ``sandbox == 0`` is parity (``1.0``); ``real == 0``
    with ``sandbox > 0`` is undefined and raises.
    """
    if not sandbox_means or not real_means:
        return {}
    if set(sandbox_means) != set(real_means):
        msg = (
            "_surface_ratio: metric set mismatch — "
            f"sandbox has {sorted(sandbox_means)}, real has {sorted(real_means)}"
        )
        raise ValueError(msg)
    out: dict[str, float] = {}
    for name in sorted(sandbox_means):
        s = sandbox_means[name]
        r = real_means[name]
        if r == 0.0:
            if s == 0.0:
                out[name] = 1.0
            else:
                msg = (
                    f"surface_ratio[{name!r}]: real mean is 0 but sandbox mean is "
                    f"{s}; ratio is undefined"
                )
                raise ValueError(msg)
        else:
            out[name] = s / r
    return out


def _sandbox_in_real_envelope(
    sandbox_reports: Sequence[ProbeReport],
    real_envelope: dict[str, tuple[float, float]],
) -> dict[str, dict[str, bool]]:
    """For each sandbox shop, whether each metric is inside the real envelope.

    Sandboxes without surface metrics are excluded.
    """
    out: dict[str, dict[str, bool]] = {}
    for report in sandbox_reports:
        if report.surface is None:
            continue
        metrics: dict[str, bool] = {}
        for name, (lo, hi) in real_envelope.items():
            value = float(getattr(report.surface, name))
            metrics[name] = lo <= value <= hi
        out[report.target.name] = metrics
    return out
