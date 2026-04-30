"""Tests for `shop_probe.fidelity`.

Covers:

* :class:`GroupSummary` and :class:`BenchComparison` round-trip and
  ``extra="forbid"``.
* :func:`compute_bench_comparison` over synthetic reports carrying
  :class:`ScaleMetrics`.
* Per-category coverage gap aggregated as ``real - sandbox``.
* Scale ratio per-metric — including parity-on-zero and rejection of
  ``real==0, sandbox>0``.
* Sandbox-in-real-envelope per metric per shop.
* Group label / category mismatch errors.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shop_probe.fidelity import (
    BenchComparison,
    GroupSummary,
    compute_bench_comparison,
)
from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    ProbeReport,
)
from shop_probe.scale.metrics import ScaleMetrics
from shop_probe.targets import Target, TargetLabel

_RUBRIC_HASH: str = "a" * 64
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1",
        viewport=(1280, 800),
        headless=True,
    )


def _scale(**overrides: float | int | None) -> ScaleMetrics:
    base: dict[str, float | int | None] = {
        "median_dom_kb_gz": 80.0,
        "interactables_per_page_median": 30.0,
        "form_fields_per_page_median": 4.0,
        "accessibility_nodes_per_page_median": 400.0,
        "catalog_products": 100,
        "catalog_collections": 12,
    }
    base.update(overrides)
    return ScaleMetrics.model_validate(base)


def _categories(values: dict[str, float]) -> tuple[CategoryScore, ...]:
    return tuple(
        CategoryScore(
            category=name,
            weight_passed=cov * 10.0,
            weight_total=10.0,
            coverage=cov,
        )
        for name, cov in values.items()
    )


def _report(
    *,
    name: str,
    label: TargetLabel,
    coverages: dict[str, float],
    coverage_weighted: float,
    scale: ScaleMetrics | None,
) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost:4000", label=label)
    return ProbeReport(
        target=target,
        rubric_version="v3",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        categories=_categories(coverages),
        coverage_core=coverage_weighted,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=coverage_weighted,
        scale=scale,
    )


# --------------------------------------------------------------------------- #
# Schema round-trip + extra="forbid".
# --------------------------------------------------------------------------- #


def _group_summary() -> GroupSummary:
    return GroupSummary(
        label="sandbox",
        n_shops=2,
        coverage_weighted_mean=0.7,
        coverage_per_axis_mean={"product": 0.7},
        scale_metric_means={"catalog_products": 100.0},
        scale_metric_envelope={"catalog_products": (80.0, 120.0)},
    )


def test_group_summary_round_trip() -> None:
    g = _group_summary()
    assert GroupSummary.model_validate_json(g.model_dump_json()) == g


def test_group_summary_rejects_unknown_field() -> None:
    raw = json.loads(_group_summary().model_dump_json())
    raw["unknown"] = 1
    with pytest.raises(ValidationError, match="unknown"):
        GroupSummary.model_validate(raw)


def test_bench_comparison_round_trip() -> None:
    b = BenchComparison(
        sandbox=_group_summary(),
        real=GroupSummary(
            label="real",
            n_shops=3,
            coverage_weighted_mean=0.8,
            coverage_per_axis_mean={"product": 0.8},
            scale_metric_means={"catalog_products": 150.0},
            scale_metric_envelope={"catalog_products": (120.0, 180.0)},
        ),
        coverage_gap_weighted=0.1,
        coverage_gap_per_axis={"product": 0.1},
        scale_ratio={"catalog_products": 100.0 / 150.0},
        sandbox_in_real_envelope={"shop_a": {"catalog_products": True}},
    )
    assert BenchComparison.model_validate_json(b.model_dump_json()) == b


# --------------------------------------------------------------------------- #
# compute_bench_comparison — coverage / scale arithmetic.
# --------------------------------------------------------------------------- #


def test_compute_bench_comparison_basic_with_scale() -> None:
    sandbox_reports = (
        _report(
            name="shop_alpha",
            label="sandbox",
            coverages={"product": 0.6, "search": 0.5},
            coverage_weighted=0.55,
            scale=_scale(catalog_products=80),
        ),
        _report(
            name="shop_beta",
            label="sandbox",
            coverages={"product": 0.8, "search": 0.7},
            coverage_weighted=0.75,
            scale=_scale(catalog_products=120),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"product": 0.9, "search": 0.8},
            coverage_weighted=0.85,
            scale=_scale(catalog_products=160),
        ),
        _report(
            name="real_b",
            label="real",
            coverages={"product": 1.0, "search": 0.9},
            coverage_weighted=0.95,
            scale=_scale(catalog_products=200),
        ),
    )

    comparison = compute_bench_comparison(sandbox_reports, real_reports)

    assert comparison.sandbox.n_shops == 2  # noqa: PLR2004
    assert comparison.real.n_shops == 2  # noqa: PLR2004
    assert comparison.sandbox.coverage_weighted_mean == pytest.approx(0.65)
    assert comparison.real.coverage_weighted_mean == pytest.approx(0.90)
    assert comparison.coverage_gap_weighted == pytest.approx(0.25)
    assert comparison.coverage_gap_per_axis["product"] == pytest.approx(0.25)
    # sandbox/real means: 100/180 for catalog_products.
    assert comparison.scale_ratio["catalog_products"] == pytest.approx(100.0 / 180.0)
    # Both sandboxes (80, 120) fall outside the real envelope (160, 200).
    assert comparison.sandbox_in_real_envelope["shop_alpha"]["catalog_products"] is False
    assert comparison.sandbox_in_real_envelope["shop_beta"]["catalog_products"] is False


def test_compute_bench_comparison_rejects_empty_sandbox() -> None:
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=None,
        ),
    )
    with pytest.raises(ValueError, match="sandbox_reports must be non-empty"):
        compute_bench_comparison((), real_reports)


def test_compute_bench_comparison_rejects_empty_real() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=None,
        ),
    )
    with pytest.raises(ValueError, match="real_reports must be non-empty"):
        compute_bench_comparison(sandbox_reports, ())


def test_compute_bench_comparison_rejects_mislabeled_target() -> None:
    sandbox_reports = (
        _report(
            name="should_be_sandbox",
            label="real",  # mislabel
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=None,
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=None,
        ),
    )
    with pytest.raises(ValueError, match="expected 'sandbox'"):
        compute_bench_comparison(sandbox_reports, real_reports)


def test_compute_bench_comparison_rejects_category_mismatch() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"product": 0.5},
            coverage_weighted=0.5,
            scale=None,
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"search": 0.5},
            coverage_weighted=0.5,
            scale=None,
        ),
    )
    with pytest.raises(ValueError, match="category mismatch"):
        compute_bench_comparison(sandbox_reports, real_reports)


def test_compute_bench_comparison_skips_missing_scale() -> None:
    """Reports with scale=None contribute coverage but not scale aggregates."""
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=None,
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.7},
            coverage_weighted=0.7,
            scale=_scale(),
        ),
    )
    comparison = compute_bench_comparison(sandbox_reports, real_reports)
    # Sandbox group has no scale rows → no scale_metric_means → ratio empty.
    assert comparison.sandbox.scale_metric_means == {}
    assert comparison.scale_ratio == {}
    # The shop with no scale is not present in the envelope dict.
    assert "shop_a" not in comparison.sandbox_in_real_envelope


def test_compute_bench_comparison_scale_ratio_zero_parity() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=_scale(form_fields_per_page_median=0.0),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=_scale(form_fields_per_page_median=0.0),
        ),
    )
    comparison = compute_bench_comparison(sandbox_reports, real_reports)
    assert comparison.scale_ratio["form_fields_per_page_median"] == 1.0


def test_compute_bench_comparison_scale_ratio_undefined_when_real_zero() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=_scale(form_fields_per_page_median=4.0),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=_scale(form_fields_per_page_median=0.0),
        ),
    )
    with pytest.raises(ValueError, match="ratio is undefined"):
        compute_bench_comparison(sandbox_reports, real_reports)


def test_compute_bench_comparison_handles_partial_scale_fields() -> None:
    """A metric with no samples in the sandbox group is omitted from ratio."""
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=_scale(catalog_products=None, catalog_collections=None),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            scale=_scale(catalog_products=200, catalog_collections=20),
        ),
    )
    comparison = compute_bench_comparison(sandbox_reports, real_reports)
    # Per-page metrics are populated in both groups → ratio present.
    assert "median_dom_kb_gz" in comparison.scale_ratio
    # Catalog metrics absent in sandbox → omitted from ratio.
    assert "catalog_products" not in comparison.scale_ratio
    assert "catalog_collections" not in comparison.scale_ratio
