"""Tests for `shop_probe.report_writer.surface_chart` (T6.3 — spec §8.4 row 3).

Covers:

* SVG envelope: ``render_surface_bar_chart_svg`` returns a self-contained
  SVG document starting with ``<svg ...>`` and ending with ``</svg>\\n``.
* Determinism: the same inputs produce byte-identical output across
  calls (paper figures must be reproducible from versioned reports —
  T6.3 acceptance check).
* One row per :class:`SurfaceMetrics` field, in declaration order (the
  order surfaced by ``SurfaceMetrics.model_fields``).
* The real-shop envelope renders as a ``<rect class="envelope">`` whose
  per-row width tracks the ``[min, max]`` span across ``real_reports``.
* Sandbox values render as outlined ``<circle class="sandbox">`` markers,
  one per sandbox report, in input order, with cycled distinct stroke
  colors.
* Source values render as filled ``<polygon class="source">`` triangle
  markers, one per source report, in input order, with cycled distinct
  fill colors.
* Empty ``sandbox_reports`` and ``source_reports`` still render the
  envelope.
* ``real_reports=()`` and reports missing surface metrics raise
  ``ValueError``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from shop_probe.report import BrowserMeta, ProbeReport
from shop_probe.report_writer.surface_chart import render_surface_bar_chart_svg
from shop_probe.surface.metrics import SurfaceMetrics
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_RUBRIC_HASH: str = "a" * 64
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

_METRIC_FIELDS: tuple[str, ...] = tuple(SurfaceMetrics.model_fields.keys())


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _surface(scale: float = 1.0) -> SurfaceMetrics:
    """Build a SurfaceMetrics scaled uniformly by ``scale``."""
    return SurfaceMetrics(
        distinct_templates=max(round(4 * scale), 0),
        routes_crawled=max(round(60 * scale), 0),
        interactables_per_template_median=24.0 * scale,
        interactables_per_template_p95=90.0 * scale,
        forms_total=max(round(5 * scale), 0),
        form_fields_total=max(round(18 * scale), 0),
        catalog_products=max(round(80 * scale), 0),
        catalog_collections=max(round(6 * scale), 0),
        catalog_variants=max(round(120 * scale), 0),
        filter_x_sort_state_space=max(round(24 * scale), 0),
        median_dom_kb_gz=32.0 * scale,
        accessibility_nodes_per_template_median=220.0 * scale,
    )


def _report(
    *,
    label: str,
    kind: str,
    pair_id: str | None,
    surface: SurfaceMetrics | None,
) -> ProbeReport:
    target = Target(
        label=label,
        base_url="http://localhost:4000",
        kind=kind,  # type: ignore[arg-type]
        pair_id=pair_id,
    )
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        probe_results=(),
        categories=(),
        coverage_core=0.0,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=0.0,
        surface=surface,
        judge_calls=(),
        rerun_index=1,
        flake_rate_per_probe={},
    )


def _real(label: str, scale: float) -> ProbeReport:
    return _report(label=label, kind="real_unpaired", pair_id=None, surface=_surface(scale))


def _sandbox(label: str, pair_id: str, scale: float) -> ProbeReport:
    return _report(label=label, kind="sandbox", pair_id=pair_id, surface=_surface(scale))


def _source(label: str, pair_id: str, scale: float) -> ProbeReport:
    return _report(label=label, kind="source", pair_id=pair_id, surface=_surface(scale))


_DEFAULT_REAL_REPORTS: Sequence[ProbeReport] = (
    _real("real/a", 0.7),
    _real("real/b", 1.0),
    _real("real/c", 1.4),
)
_DEFAULT_SANDBOX_REPORTS: Sequence[ProbeReport] = (
    _sandbox("sandbox/x", "pair_x", 0.9),
    _sandbox("sandbox/y", "pair_y", 0.6),
)
_DEFAULT_SOURCE_REPORTS: Sequence[ProbeReport] = (
    _source("source/x", "pair_x", 1.1),
    _source("source/y", "pair_y", 0.8),
)


# --------------------------------------------------------------------------- #
# SVG envelope.
# --------------------------------------------------------------------------- #


def test_output_is_self_contained_svg_document() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    assert out.startswith("<svg ")
    assert 'xmlns="http://www.w3.org/2000/svg"' in out
    assert out.endswith("</svg>\n")


def test_output_is_deterministic_across_calls() -> None:
    first = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    second = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    assert first == second


# --------------------------------------------------------------------------- #
# Row layout.
# --------------------------------------------------------------------------- #


def test_one_row_per_surface_metric_in_declaration_order() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    metrics = re.findall(r'<g class="row" data-metric="([^"]+)">', out)
    assert metrics == list(_METRIC_FIELDS)


def test_each_row_renders_a_metric_label() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    for metric in _METRIC_FIELDS:
        assert f">{metric}</text>" in out


# --------------------------------------------------------------------------- #
# Envelope rectangles.
# --------------------------------------------------------------------------- #


def test_envelope_renders_one_rect_per_metric() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    rects = re.findall(r'<rect class="envelope"[^/]*/>', out)
    assert len(rects) == len(_METRIC_FIELDS)


def test_envelope_width_grows_with_real_population_spread() -> None:
    # Tight population ([min, max] near each other).
    tight = (_real("real/a", 0.95), _real("real/b", 1.0), _real("real/c", 1.05))
    # Wide population (3x spread).
    wide = (_real("real/a", 0.5), _real("real/b", 1.0), _real("real/c", 1.5))

    tight_out = render_surface_bar_chart_svg(
        real_reports=tight, sandbox_reports=(), source_reports=()
    )
    wide_out = render_surface_bar_chart_svg(
        real_reports=wide, sandbox_reports=(), source_reports=()
    )

    # Pick a row whose underlying value is comfortably non-zero so the
    # comparison isn't dominated by the degenerate-min-equals-max floor.
    tight_w = _envelope_width(tight_out, "routes_crawled")
    wide_w = _envelope_width(wide_out, "routes_crawled")
    assert wide_w > tight_w


def test_envelope_collapses_to_floor_width_when_min_equals_max() -> None:
    # Single real report → min == max for every metric. The renderer
    # floors the rectangle width at one user unit so the row stays
    # visible (and the legend / scale annotation still render).
    real = (_real("real/only", 1.0),)
    out = render_surface_bar_chart_svg(real_reports=real, sandbox_reports=(), source_reports=())
    width = _envelope_width(out, "routes_crawled")
    assert width == pytest.approx(1.0, abs=1e-3)


# --------------------------------------------------------------------------- #
# Sandbox + source markers.
# --------------------------------------------------------------------------- #


def test_one_sandbox_circle_per_report_per_row() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=(),
    )
    circles = re.findall(r'<circle class="sandbox"[^/]*/>', out)
    assert len(circles) == len(_DEFAULT_SANDBOX_REPORTS) * len(_METRIC_FIELDS)


def test_one_source_triangle_per_report_per_row() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=(),
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    triangles = re.findall(r'<polygon class="source"[^/]*/>', out)
    assert len(triangles) == len(_DEFAULT_SOURCE_REPORTS) * len(_METRIC_FIELDS)


def test_sandbox_markers_use_distinct_stroke_colors() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
        source_reports=(),
    )
    strokes = re.findall(
        r'<circle class="sandbox" data-index="(\d+)"[^/]*stroke="([^"]+)"',
        out,
    )
    assert strokes  # markers rendered
    color_by_index: dict[str, str] = {}
    for index, color in strokes:
        color_by_index.setdefault(index, color)
        assert color_by_index[index] == color  # same input index → same color
    # Two distinct sandbox inputs → two distinct colors.
    assert color_by_index["0"] != color_by_index["1"]


def test_source_triangles_use_distinct_fill_colors() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=(),
        source_reports=_DEFAULT_SOURCE_REPORTS,
    )
    fills = re.findall(
        r'<polygon class="source" data-index="(\d+)"[^/]*fill="([^"]+)"',
        out,
    )
    assert fills
    color_by_index: dict[str, str] = {}
    for index, color in fills:
        color_by_index.setdefault(index, color)
        assert color_by_index[index] == color
    assert color_by_index["0"] != color_by_index["1"]


def test_empty_sandbox_and_source_reports_still_renders_envelope() -> None:
    out = render_surface_bar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=(),
        source_reports=(),
    )
    assert '<rect class="envelope"' in out
    assert '<circle class="sandbox"' not in out
    assert '<polygon class="source"' not in out


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #


def test_empty_real_reports_raises() -> None:
    with pytest.raises(ValueError, match="real_reports must be non-empty"):
        render_surface_bar_chart_svg(
            real_reports=(),
            sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
            source_reports=_DEFAULT_SOURCE_REPORTS,
        )


def test_real_report_without_surface_raises() -> None:
    real = (_report(label="real/no-surface", kind="real_unpaired", pair_id=None, surface=None),)
    with pytest.raises(ValueError, match="real report 'real/no-surface'"):
        render_surface_bar_chart_svg(real_reports=real, sandbox_reports=(), source_reports=())


def test_sandbox_report_without_surface_raises() -> None:
    sandbox = (_report(label="sandbox/no-surface", kind="sandbox", pair_id="pair_x", surface=None),)
    with pytest.raises(ValueError, match="sandbox report 'sandbox/no-surface'"):
        render_surface_bar_chart_svg(
            real_reports=_DEFAULT_REAL_REPORTS,
            sandbox_reports=sandbox,
            source_reports=(),
        )


def test_source_report_without_surface_raises() -> None:
    source = (_report(label="source/no-surface", kind="source", pair_id="pair_x", surface=None),)
    with pytest.raises(ValueError, match="source report 'source/no-surface'"):
        render_surface_bar_chart_svg(
            real_reports=_DEFAULT_REAL_REPORTS,
            sandbox_reports=(),
            source_reports=source,
        )


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _envelope_width(svg: str, metric: str) -> float:
    """Pull the envelope ``<rect width="…">`` for one metric row."""
    pattern = (
        rf'<g class="row" data-metric="{re.escape(metric)}">'
        r"[\s\S]*?"
        r'<rect class="envelope"[^/]*?\swidth="([0-9.]+)"'
    )
    match = re.search(pattern, svg)
    assert match is not None, f"envelope rect for {metric!r} not found"
    return float(match.group(1))
