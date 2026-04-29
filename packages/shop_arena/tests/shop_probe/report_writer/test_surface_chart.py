"""Tests for `shop_probe.report_writer.surface_chart` (web_probe_patch.md)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shop_probe.report import BrowserMeta, CategoryScore, ProbeReport
from shop_probe.report_writer.surface_chart import render_surface_bar_chart_svg
from shop_probe.surface.metrics import SurfaceMetrics
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


def _surface(scale: float = 1.0) -> SurfaceMetrics:
    return SurfaceMetrics.model_validate(
        {
            "distinct_templates": int(5 * scale),
            "routes_crawled": int(50 * scale),
            "interactables_per_template_median": 30.0 * scale,
            "interactables_per_template_p95": 90.0 * scale,
            "forms_total": int(4 * scale),
            "form_fields_total": int(20 * scale),
            "catalog_products": int(100 * scale),
            "catalog_collections": int(12 * scale),
            "catalog_variants": int(250 * scale),
            "filter_x_sort_state_space": int(64 * scale),
            "median_dom_kb_gz": 80.0 * scale,
            "accessibility_nodes_per_template_median": 400.0 * scale,
        }
    )


def _report(name: str, label: TargetLabel, *, surface: SurfaceMetrics | None = None) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost", label=label)
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        categories=(
            CategoryScore(category="product", weight_passed=10.0, weight_total=10.0, coverage=1.0),
        ),
        coverage_core=1.0,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=1.0,
        surface=surface,
        rerun_index=1,
    )


def _real(name: str, scale: float = 1.0) -> ProbeReport:
    return _report(name, "real", surface=_surface(scale))


def _sandbox(name: str, scale: float = 1.0) -> ProbeReport:
    return _report(name, "sandbox", surface=_surface(scale))


_DEFAULT_REAL = (_real("real_a", 1.0), _real("real_b", 1.5), _real("real_c", 2.0))


def test_render_emits_svg_root_element() -> None:
    out = render_surface_bar_chart_svg(real_reports=_DEFAULT_REAL, sandbox_reports=())
    assert out.startswith("<svg ")
    assert out.endswith("\n")


def test_render_includes_envelope_and_legend() -> None:
    out = render_surface_bar_chart_svg(real_reports=_DEFAULT_REAL, sandbox_reports=())
    assert "real-shop envelope" in out
    assert 'class="envelope"' in out


def test_render_overlays_sandbox_circles() -> None:
    sandboxes = (_sandbox("shop_alpha", 1.2), _sandbox("shop_beta", 1.4))
    out = render_surface_bar_chart_svg(real_reports=_DEFAULT_REAL, sandbox_reports=sandboxes)
    # Two circles per metric — at minimum, each sandbox shows up by name in the legend.
    assert "shop_alpha" in out
    assert "shop_beta" in out


def test_render_is_byte_stable() -> None:
    sandboxes = (_sandbox("shop_alpha", 1.2),)
    a = render_surface_bar_chart_svg(real_reports=_DEFAULT_REAL, sandbox_reports=sandboxes)
    b = render_surface_bar_chart_svg(real_reports=_DEFAULT_REAL, sandbox_reports=sandboxes)
    assert a == b


def test_render_rejects_empty_real() -> None:
    with pytest.raises(ValueError, match="real_reports must be non-empty"):
        render_surface_bar_chart_svg(real_reports=(), sandbox_reports=())


def test_render_rejects_real_without_surface() -> None:
    bad = _report("real_a", "real", surface=None)
    with pytest.raises(ValueError, match="missing surface metrics"):
        render_surface_bar_chart_svg(real_reports=(bad,), sandbox_reports=())


def test_render_rejects_sandbox_without_surface() -> None:
    bad = _report("shop_a", "sandbox", surface=None)
    with pytest.raises(ValueError, match="missing surface metrics"):
        render_surface_bar_chart_svg(real_reports=_DEFAULT_REAL, sandbox_reports=(bad,))


def test_render_with_empty_sandbox_still_renders() -> None:
    out = render_surface_bar_chart_svg(real_reports=_DEFAULT_REAL, sandbox_reports=())
    assert "<svg" in out
    # Sandbox legend is empty but envelope swatch is always present.
    assert "real-shop envelope" in out
