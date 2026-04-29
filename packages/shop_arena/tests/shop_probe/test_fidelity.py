"""Tests for `shop_probe.fidelity` (web_probe_patch.md).

Covers:

* :class:`GroupSummary` and :class:`BenchComparison` round-trip and
  ``extra="forbid"``.
* :func:`compute_bench_comparison` over synthetic A+B reports.
* Per-category coverage gap aggregated as ``real - sandbox``.
* Surface ratio per-metric — including parity-on-zero and rejection of
  ``real==0, sandbox>0``.
* Sandbox-in-real-envelope per metric per shop.
* Judge accuracy and indistinguishability gap from per-shop judge calls.
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
    JudgeCall,
    ProbeReport,
)
from shop_probe.surface.metrics import SurfaceMetrics
from shop_probe.targets import Target, TargetLabel

_RUBRIC_HASH: str = "a" * 64
_PROMPT_HASH: str = "b" * 64
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


def _surface(**overrides: float) -> SurfaceMetrics:
    base: dict[str, float] = {
        "distinct_templates": 5,
        "routes_crawled": 50,
        "interactables_per_template_median": 30.0,
        "interactables_per_template_p95": 90.0,
        "forms_total": 4,
        "form_fields_total": 20,
        "catalog_products": 100,
        "catalog_collections": 12,
        "catalog_variants": 250,
        "filter_x_sort_state_space": 64,
        "median_dom_kb_gz": 80.0,
        "accessibility_nodes_per_template_median": 400.0,
    }
    base.update(overrides)
    return SurfaceMetrics.model_validate(base)


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


def _judge_call(predicted: str) -> JudgeCall:
    return JudgeCall(
        predicted_label=predicted,  # type: ignore[arg-type]
        prompt_hash=_PROMPT_HASH,
        response="r",
        latency_ms=10.0,
        cost_usd=0.0,
        model_id="gpt-stub",
    )


def _report(
    *,
    name: str,
    label: TargetLabel,
    coverages: dict[str, float],
    coverage_weighted: float,
    surface: SurfaceMetrics | None,
    judge_calls: tuple[JudgeCall, ...] = (),
) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost:4000", label=label)
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        categories=_categories(coverages),
        coverage_core=coverage_weighted,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=coverage_weighted,
        surface=surface,
        judge_calls=judge_calls,
        rerun_index=1,
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
        surface_metric_means={"distinct_templates": 5.0},
        surface_metric_envelope={"distinct_templates": (4.0, 6.0)},
        judge_accuracy=0.6,
        judge_calls_total=10,
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
            surface_metric_means={"distinct_templates": 6.0},
            surface_metric_envelope={"distinct_templates": (5.0, 7.0)},
            judge_accuracy=0.9,
            judge_calls_total=15,
        ),
        coverage_gap_weighted=0.1,
        coverage_gap_per_axis={"product": 0.1},
        surface_ratio={"distinct_templates": 0.83},
        sandbox_in_real_envelope={"shop_a": {"distinct_templates": True}},
        judge_indistinguishability=0.3,
    )
    assert BenchComparison.model_validate_json(b.model_dump_json()) == b


# --------------------------------------------------------------------------- #
# compute_bench_comparison — coverage / surface arithmetic.
# --------------------------------------------------------------------------- #


def test_compute_bench_comparison_basic_axes_a_and_b() -> None:
    sandbox_reports = (
        _report(
            name="shop_alpha",
            label="sandbox",
            coverages={"product": 0.6, "search": 0.5},
            coverage_weighted=0.55,
            surface=_surface(distinct_templates=4),
        ),
        _report(
            name="shop_beta",
            label="sandbox",
            coverages={"product": 0.8, "search": 0.7},
            coverage_weighted=0.75,
            surface=_surface(distinct_templates=6),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"product": 0.9, "search": 0.8},
            coverage_weighted=0.85,
            surface=_surface(distinct_templates=8),
        ),
        _report(
            name="real_b",
            label="real",
            coverages={"product": 1.0, "search": 0.9},
            coverage_weighted=0.95,
            surface=_surface(distinct_templates=10),
        ),
    )

    comparison = compute_bench_comparison(sandbox_reports, real_reports)

    assert comparison.sandbox.n_shops == 2  # noqa: PLR2004
    assert comparison.real.n_shops == 2  # noqa: PLR2004
    assert comparison.sandbox.coverage_weighted_mean == pytest.approx(0.65)
    assert comparison.real.coverage_weighted_mean == pytest.approx(0.90)
    assert comparison.coverage_gap_weighted == pytest.approx(0.25)
    assert comparison.coverage_gap_per_axis["product"] == pytest.approx(0.25)
    # sandbox/real means: 5/9 for distinct_templates.
    assert comparison.surface_ratio["distinct_templates"] == pytest.approx(5 / 9)
    # Both sandboxes (4, 6) fall outside the real envelope (8, 10) so
    # ``in_real_envelope`` is False for distinct_templates.
    assert comparison.sandbox_in_real_envelope["shop_alpha"]["distinct_templates"] is False
    assert comparison.sandbox_in_real_envelope["shop_beta"]["distinct_templates"] is False
    # Judge calls absent → indistinguishability is None.
    assert comparison.judge_indistinguishability is None
    assert comparison.sandbox.judge_accuracy is None
    assert comparison.real.judge_accuracy is None


def test_compute_bench_comparison_rejects_empty_sandbox() -> None:
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=None,
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
            surface=None,
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
            surface=None,
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=None,
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
            surface=None,
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"search": 0.5},
            coverage_weighted=0.5,
            surface=None,
        ),
    )
    with pytest.raises(ValueError, match="category mismatch"):
        compute_bench_comparison(sandbox_reports, real_reports)


def test_compute_bench_comparison_skips_missing_surface() -> None:
    """Reports with surface=None contribute coverage but not surface aggregates."""
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=None,
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.7},
            coverage_weighted=0.7,
            surface=_surface(),
        ),
    )
    comparison = compute_bench_comparison(sandbox_reports, real_reports)
    # Sandbox group has no surfaces → no surface_metric_means → ratio empty.
    assert comparison.sandbox.surface_metric_means == {}
    assert comparison.surface_ratio == {}
    # The shop with no surface is not present in the envelope dict.
    assert "shop_a" not in comparison.sandbox_in_real_envelope


def test_compute_bench_comparison_surface_ratio_zero_parity() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=_surface(forms_total=0),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=_surface(forms_total=0),
        ),
    )
    comparison = compute_bench_comparison(sandbox_reports, real_reports)
    assert comparison.surface_ratio["forms_total"] == 1.0


def test_compute_bench_comparison_surface_ratio_undefined_when_real_zero() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=_surface(forms_total=4),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=_surface(forms_total=0),
        ),
    )
    with pytest.raises(ValueError, match="ratio is undefined"):
        compute_bench_comparison(sandbox_reports, real_reports)


# --------------------------------------------------------------------------- #
# Judge accuracy + indistinguishability.
# --------------------------------------------------------------------------- #


def test_compute_bench_comparison_judge_accuracy_per_group() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=None,
            judge_calls=(
                _judge_call("sandbox"),
                _judge_call("sandbox"),
                _judge_call("real"),
                _judge_call("abstain"),
            ),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=None,
            judge_calls=(
                _judge_call("real"),
                _judge_call("real"),
            ),
        ),
    )
    comparison = compute_bench_comparison(sandbox_reports, real_reports)
    assert comparison.sandbox.judge_accuracy == pytest.approx(0.5)
    assert comparison.sandbox.judge_calls_total == 4  # noqa: PLR2004
    assert comparison.real.judge_accuracy == pytest.approx(1.0)
    assert comparison.real.judge_calls_total == 2  # noqa: PLR2004
    assert comparison.judge_indistinguishability == pytest.approx(0.5)


def test_compute_bench_comparison_judge_indistinguishability_none_when_one_group_empty() -> None:
    sandbox_reports = (
        _report(
            name="shop_a",
            label="sandbox",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=None,
            judge_calls=(_judge_call("sandbox"),),
        ),
    )
    real_reports = (
        _report(
            name="real_a",
            label="real",
            coverages={"x": 0.5},
            coverage_weighted=0.5,
            surface=None,
        ),
    )
    comparison = compute_bench_comparison(sandbox_reports, real_reports)
    assert comparison.sandbox.judge_accuracy == pytest.approx(1.0)
    assert comparison.real.judge_accuracy is None
    assert comparison.judge_indistinguishability is None
