"""Tests for `shop_probe.report_writer.tables`."""

from __future__ import annotations

from datetime import UTC, datetime

from shop_probe.fidelity import BenchComparison, GroupSummary
from shop_probe.report import BrowserMeta, CategoryScore, ProbeReport
from shop_probe.report_writer.tables import (
    render_group_comparison_table,
    render_per_shop_table,
)
from shop_probe.targets import Target, TargetLabel

_TIMESTAMP = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_RUBRIC_HASH = "a" * 64


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11",
        playwright_version="1.48",
        chromium_version="129",
        user_agent="ShopProbe/0.1",
        viewport=(1280, 800),
        headless=True,
    )


def _summary(label: TargetLabel) -> GroupSummary:
    return GroupSummary(
        label=label,
        n_shops=2,
        coverage_weighted_mean=0.7 if label == "sandbox" else 0.85,
        coverage_per_axis_mean={"product": 0.7 if label == "sandbox" else 0.85},
        scale_metric_means={"catalog_products": 80.0 if label == "sandbox" else 160.0},
        scale_metric_envelope={"catalog_products": (60.0, 100.0)},
    )


def _comparison() -> BenchComparison:
    return BenchComparison(
        sandbox=_summary("sandbox"),
        real=_summary("real"),
        coverage_gap_weighted=0.15,
        coverage_gap_per_axis={"product": 0.15},
        scale_ratio={"catalog_products": 0.5},
        sandbox_in_real_envelope={
            "shop_alpha": {"catalog_products": True},
            "shop_beta": {"catalog_products": False},
        },
    )


def _report(name: str, label: TargetLabel) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost", label=label)
    return ProbeReport(
        target=target,
        rubric_version="v3",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        categories=(
            CategoryScore(category="product", weight_passed=7.0, weight_total=10.0, coverage=0.7),
        ),
        coverage_core=0.7,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=0.7,
    )


def test_group_comparison_renders_three_rows() -> None:
    md = render_group_comparison_table(_comparison())
    lines = md.splitlines()
    assert lines[0].startswith("| Group |")
    assert "sandbox" in lines[2]
    assert "real" in lines[3]
    assert "delta" in lines[4]


def test_group_comparison_signed_delta_for_coverage_gap() -> None:
    md = render_group_comparison_table(_comparison())
    assert "+0.150" in md


def test_group_comparison_is_byte_stable() -> None:
    comparison = _comparison()
    assert render_group_comparison_table(comparison) == render_group_comparison_table(comparison)


def test_per_shop_table_includes_one_row_per_shop() -> None:
    sandbox_reports = (
        _report("shop_alpha", "sandbox"),
        _report("shop_beta", "sandbox"),
    )
    real_reports = (_report("real_a", "real"),)
    md = render_per_shop_table(sandbox_reports, real_reports, _comparison())
    assert "shop_alpha" in md
    assert "shop_beta" in md
    assert "real_a" in md


def test_per_shop_table_envelope_count_format() -> None:
    sandbox_reports = (_report("shop_alpha", "sandbox"),)
    real_reports = (_report("real_a", "real"),)
    md = render_per_shop_table(sandbox_reports, real_reports, _comparison())
    # The envelope cell is `inside/total`. shop_alpha has 1/1.
    assert "1/1" in md


def test_group_comparison_trailing_newline() -> None:
    out = render_group_comparison_table(_comparison())
    assert out.endswith("\n")
