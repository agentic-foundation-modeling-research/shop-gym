"""Tests for `shop_probe.report_writer.tables` (web_probe_patch.md)."""

from __future__ import annotations

from datetime import UTC, datetime

from shop_probe.fidelity import BenchComparison, GroupSummary
from shop_probe.report import BrowserMeta, CategoryScore, JudgeCall, ProbeReport
from shop_probe.report_writer.tables import (
    render_group_comparison_table,
    render_per_shop_table,
)
from shop_probe.targets import Target, TargetLabel

_TIMESTAMP = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_RUBRIC_HASH = "a" * 64
_PROMPT_HASH = "b" * 64


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11",
        playwright_version="1.48",
        chromium_version="129",
        user_agent="ShopProbe/0.1",
        viewport=(1280, 800),
        headless=True,
    )


def _summary(label: TargetLabel, accuracy: float | None = None) -> GroupSummary:
    return GroupSummary(
        label=label,
        n_shops=2,
        coverage_weighted_mean=0.7 if label == "sandbox" else 0.85,
        coverage_per_axis_mean={"product": 0.7 if label == "sandbox" else 0.85},
        surface_metric_means={"distinct_templates": 4.0 if label == "sandbox" else 8.0},
        surface_metric_envelope={"distinct_templates": (3.0, 5.0)},
        judge_accuracy=accuracy,
        judge_calls_total=10 if accuracy is not None else 0,
    )


def _comparison(*, with_judge: bool = False) -> BenchComparison:
    return BenchComparison(
        sandbox=_summary("sandbox", 0.6 if with_judge else None),
        real=_summary("real", 0.9 if with_judge else None),
        coverage_gap_weighted=0.15,
        coverage_gap_per_axis={"product": 0.15},
        surface_ratio={"distinct_templates": 0.5},
        sandbox_in_real_envelope={
            "shop_alpha": {"distinct_templates": True},
            "shop_beta": {"distinct_templates": False},
        },
        judge_indistinguishability=0.3 if with_judge else None,
    )


def _report(
    name: str,
    label: TargetLabel,
    *,
    judge_calls: tuple[JudgeCall, ...] = (),
) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost", label=label)
    return ProbeReport(
        target=target,
        rubric_version="v1",
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
        judge_calls=judge_calls,
        rerun_index=1,
    )


def _judge_call(predicted: str) -> JudgeCall:
    return JudgeCall(
        predicted_label=predicted,  # type: ignore[arg-type]
        prompt_hash=_PROMPT_HASH,
        response="r",
        latency_ms=10.0,
        cost_usd=0.0,
        model_id="m",
    )


def test_group_comparison_renders_three_rows() -> None:
    md = render_group_comparison_table(_comparison(with_judge=True))
    lines = md.splitlines()
    assert lines[0].startswith("| Group |")
    assert "sandbox" in lines[2]
    assert "real" in lines[3]
    assert "delta" in lines[4]


def test_group_comparison_renders_judge_columns_when_present() -> None:
    md = render_group_comparison_table(_comparison(with_judge=True))
    assert "0.600" in md  # sandbox accuracy
    assert "0.900" in md  # real accuracy
    assert "0.300" in md  # indistinguishability


def test_group_comparison_renders_em_dash_when_no_judge_calls() -> None:
    md = render_group_comparison_table(_comparison(with_judge=False))
    assert "—" in md


def test_group_comparison_signed_delta_for_coverage_gap() -> None:
    md = render_group_comparison_table(_comparison())
    assert "+0.150" in md


def test_group_comparison_is_byte_stable() -> None:
    comparison = _comparison(with_judge=True)
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


def test_per_shop_table_renders_judge_accuracy() -> None:
    sandbox_reports = (
        _report(
            "shop_alpha",
            "sandbox",
            judge_calls=(_judge_call("sandbox"), _judge_call("real")),
        ),
    )
    real_reports = (_report("real_a", "real"),)
    md = render_per_shop_table(sandbox_reports, real_reports, _comparison())
    # 1 of 2 calls correct → 0.500
    assert "0.500" in md


def test_group_comparison_trailing_newline() -> None:
    out = render_group_comparison_table(_comparison())
    assert out.endswith("\n")
