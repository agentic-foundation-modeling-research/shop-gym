"""Tests for `shop_probe.report_writer.figures` (T6.2 — radar chart)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shop_probe.report import BrowserMeta, CategoryScore, ProbeReport
from shop_probe.report_writer.figures import render_radar_chart_svg
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


def _report(
    name: str,
    label: TargetLabel,
    coverages: dict[str, float],
) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost", label=label)
    weighted = sum(coverages.values()) / max(len(coverages), 1)
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        categories=tuple(
            CategoryScore(category=k, weight_passed=v * 10.0, weight_total=10.0, coverage=v)
            for k, v in coverages.items()
        ),
        coverage_core=weighted,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=weighted,
        rerun_index=1,
    )


def _real(name: str, coverages: dict[str, float]) -> ProbeReport:
    return _report(name, "real", coverages)


def _sandbox(name: str, coverages: dict[str, float]) -> ProbeReport:
    return _report(name, "sandbox", coverages)


def test_render_emits_svg_root_element() -> None:
    cov = {"product": 0.5, "search": 0.7}
    out = render_radar_chart_svg(
        real_reports=(_real("real_a", cov),),
        sandbox_reports=(),
    )
    assert out.startswith("<svg ")
    assert out.endswith("\n")
    assert "real-shop envelope" in out


def test_render_includes_per_category_axes() -> None:
    cov = {"product": 0.5, "search": 0.7, "site_shell": 0.6}
    out = render_radar_chart_svg(
        real_reports=(_real("real_a", cov),),
        sandbox_reports=(),
    )
    for category in cov:
        assert category in out


def test_render_overlays_sandbox_polygons_with_target_name() -> None:
    cov = {"product": 0.5, "search": 0.7}
    sandbox = _sandbox("shop_alpha", cov)
    out = render_radar_chart_svg(
        real_reports=(_real("real_a", cov),),
        sandbox_reports=(sandbox,),
    )
    # Legend uses target.name (web_probe_patch.md).
    assert 'data-label="shop_alpha"' in out


def test_render_is_byte_stable() -> None:
    cov = {"product": 0.5, "search": 0.7}
    args = {
        "real_reports": (_real("real_a", cov),),
        "sandbox_reports": (_sandbox("shop_alpha", cov),),
    }
    assert render_radar_chart_svg(**args) == render_radar_chart_svg(**args)


def test_render_rejects_empty_real_reports() -> None:
    with pytest.raises(ValueError, match="real_reports must be non-empty"):
        render_radar_chart_svg(real_reports=(), sandbox_reports=())


def test_render_rejects_category_mismatch() -> None:
    with pytest.raises(ValueError, match="categories"):
        render_radar_chart_svg(
            real_reports=(
                _real("real_a", {"product": 0.5}),
                _real("real_b", {"search": 0.5}),
            ),
            sandbox_reports=(),
        )


def test_render_rejects_sandbox_with_extra_category() -> None:
    cov = {"product": 0.5}
    with pytest.raises(ValueError, match="categories"):
        render_radar_chart_svg(
            real_reports=(_real("real_a", cov),),
            sandbox_reports=(_sandbox("shop_alpha", {"product": 0.5, "search": 0.5}),),
        )
