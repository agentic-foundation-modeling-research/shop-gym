"""Tests for `shop_probe.report_writer.turing_chart` (web_probe_patch.md)."""

from __future__ import annotations

import pytest

from shop_probe.fidelity import BenchComparison, GroupSummary
from shop_probe.report_writer.turing_chart import render_turing_chart_svg


def _summary(
    label: str,
    accuracy: float | None,
    *,
    n_shops: int = 2,
    calls: int = 10,
) -> GroupSummary:
    return GroupSummary(
        label=label,  # type: ignore[arg-type]
        n_shops=n_shops,
        coverage_weighted_mean=0.7,
        coverage_per_axis_mean={"product": 0.7},
        surface_metric_means={},
        surface_metric_envelope={},
        judge_accuracy=accuracy,
        judge_calls_total=calls if accuracy is not None else 0,
    )


def _comparison(
    sandbox_acc: float | None = 0.5,
    real_acc: float | None = 0.95,
) -> BenchComparison:
    indistinguishability: float | None = None
    if sandbox_acc is not None and real_acc is not None:
        indistinguishability = abs(real_acc - sandbox_acc)
    return BenchComparison(
        sandbox=_summary("sandbox", sandbox_acc),
        real=_summary("real", real_acc),
        coverage_gap_weighted=0.0,
        coverage_gap_per_axis={},
        surface_ratio={},
        sandbox_in_real_envelope={},
        judge_indistinguishability=indistinguishability,
    )


def test_render_emits_svg_with_two_bars() -> None:
    out = render_turing_chart_svg(_comparison())
    assert out.startswith("<svg ")
    assert out.endswith("\n")
    # Two grouped bars: one labeled sandbox, one labeled real.
    assert 'data-group="sandbox"' in out
    assert 'data-group="real"' in out


def test_render_includes_indistinguishability_gap() -> None:
    out = render_turing_chart_svg(_comparison(0.5, 0.95))
    assert "0.450" in out  # |0.95 - 0.50|


def test_render_includes_chance_rate_reference() -> None:
    out = render_turing_chart_svg(_comparison())
    # The reference line carries data-value="0.500".
    assert 'data-value="0.500"' in out
    assert "chance rate" in out


def test_render_is_byte_stable() -> None:
    comparison = _comparison()
    a = render_turing_chart_svg(comparison)
    b = render_turing_chart_svg(comparison)
    assert a == b


def test_render_rejects_missing_judge_accuracy() -> None:
    with pytest.raises(ValueError, match="both groups must have judge calls"):
        render_turing_chart_svg(_comparison(sandbox_acc=None, real_acc=0.9))


def test_render_legend_reports_n_shops_and_calls() -> None:
    comparison = _comparison(0.5, 0.9)
    out = render_turing_chart_svg(comparison)
    assert "n=2" in out
    assert "calls=10" in out


@pytest.mark.parametrize("acc", [0.0, 0.25, 0.5, 1.0])
def test_render_clamps_value_to_axis(acc: float) -> None:
    out = render_turing_chart_svg(_comparison(acc, acc))
    assert "<svg" in out
