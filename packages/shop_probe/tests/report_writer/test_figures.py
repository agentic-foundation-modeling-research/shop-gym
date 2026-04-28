"""Tests for `shop_probe.report_writer.figures` (T6.2 — spec §8.4 row 2).

Covers:

* SVG envelope: ``render_radar_chart_svg`` returns a self-contained
  SVG document starting with ``<svg ...>`` and ending with ``</svg>\\n``.
* Determinism: the same inputs produce byte-identical output across
  calls (paper figures must be reproducible from versioned reports —
  T6.2 acceptance check).
* Category axis order is alphabetical, independent of input order.
* Real-shop envelope renders as a single ``<path fill-rule="evenodd">``
  with two closed sub-paths (``Z … Z``) — the annulus between
  per-category min and max.
* Sandboxes overlay as one ``<polygon>`` per report, in input order,
  with cycled distinct stroke colors and the target label embedded as
  a stable ``data-label`` attribute.
* Empty ``sandbox_reports`` still renders the envelope.
* ``real_reports=()`` and category-set mismatches raise ``ValueError``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from shop_probe.report import BrowserMeta, CategoryScore, ProbeReport
from shop_probe.report_writer.figures import render_radar_chart_svg
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_RUBRIC_HASH: str = "a" * 64
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


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
    label: str,
    kind: str,
    pair_id: str | None,
    coverages: dict[str, float],
) -> ProbeReport:
    target = Target(
        label=label,
        base_url="http://localhost:4000",
        kind=kind,  # type: ignore[arg-type]
        pair_id=pair_id,
    )
    weighted = sum(coverages.values()) / max(len(coverages), 1)
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        probe_results=(),
        categories=_categories(coverages),
        coverage_core=weighted,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=weighted,
        surface=None,
        judge_calls=(),
        rerun_index=1,
        flake_rate_per_probe={},
    )


def _real(label: str, coverages: dict[str, float]) -> ProbeReport:
    return _report(label=label, kind="real_unpaired", pair_id=None, coverages=coverages)


def _sandbox(
    label: str,
    pair_id: str,
    coverages: dict[str, float],
) -> ProbeReport:
    return _report(label=label, kind="sandbox", pair_id=pair_id, coverages=coverages)


_DEFAULT_REAL_REPORTS = (
    _real("real/a", {"site_shell": 0.9, "cart": 0.8, "product": 0.7}),
    _real("real/b", {"site_shell": 0.7, "cart": 0.6, "product": 0.5}),
    _real("real/c", {"site_shell": 0.8, "cart": 0.7, "product": 0.6}),
)
_DEFAULT_SANDBOX_REPORTS = (
    _sandbox("sandbox/x", "pair_x", {"site_shell": 0.85, "cart": 0.65, "product": 0.55}),
    _sandbox("sandbox/y", "pair_y", {"site_shell": 0.75, "cart": 0.55, "product": 0.45}),
)


# --------------------------------------------------------------------------- #
# SVG envelope.
# --------------------------------------------------------------------------- #


def test_output_is_self_contained_svg_document() -> None:
    out = render_radar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
    )
    assert out.startswith("<svg ")
    assert 'xmlns="http://www.w3.org/2000/svg"' in out
    assert out.endswith("</svg>\n")


def test_output_is_deterministic_across_calls() -> None:
    first = render_radar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
    )
    second = render_radar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
    )
    assert first == second


# --------------------------------------------------------------------------- #
# Category axes.
# --------------------------------------------------------------------------- #


def test_category_labels_appear_in_alphabetical_order() -> None:
    # Insert in non-alphabetical order to make the sort observable.
    real = (_real("real/a", {"product": 0.3, "site_shell": 0.5, "cart": 0.4}),)
    sandbox = (_sandbox("sandbox/x", "pair_x", {"product": 0.2, "site_shell": 0.4, "cart": 0.3}),)
    out = render_radar_chart_svg(real_reports=real, sandbox_reports=sandbox)
    # Pull category labels from the <text> nodes inside the
    # category-labels group.
    block = _slice_group(out, "category-labels")
    labels = re.findall(r">([^<]+)</text>", block)
    assert labels == ["cart", "product", "site_shell"]


# --------------------------------------------------------------------------- #
# Envelope path.
# --------------------------------------------------------------------------- #


def test_envelope_renders_as_evenodd_annulus_path() -> None:
    out = render_radar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
    )
    block = _slice_group(out, "envelope")
    assert 'fill-rule="evenodd"' in block
    # Two closed sub-paths: outer (max) + inner (min).
    path_d = re.search(r'<path d="([^"]+)"', block)
    assert path_d is not None
    assert path_d.group(1).count("M ") == 2  # noqa: PLR2004
    assert path_d.group(1).count("Z") == 2  # noqa: PLR2004


def test_envelope_collapses_to_single_ring_when_only_one_real_report() -> None:
    # min == max for every category, so the annulus degenerates — it
    # must still render two sub-paths (the path schema is stable across
    # M3 pilot single-real and M5 full-cohort runs).
    real = (_real("real/a", {"site_shell": 0.5, "cart": 0.5, "product": 0.5}),)
    out = render_radar_chart_svg(real_reports=real, sandbox_reports=())
    block = _slice_group(out, "envelope")
    assert 'fill-rule="evenodd"' in block
    path_d = re.search(r'<path d="([^"]+)"', block)
    assert path_d is not None
    assert path_d.group(1).count("M ") == 2  # noqa: PLR2004


# --------------------------------------------------------------------------- #
# Sandbox polygons.
# --------------------------------------------------------------------------- #


def test_one_polygon_per_sandbox_in_input_order() -> None:
    out = render_radar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
    )
    polygons = re.findall(r'<g class="sandbox" data-label="([^"]+)">', out)
    assert polygons == ["sandbox/x", "sandbox/y"]


def test_sandbox_polygons_use_distinct_stroke_colors() -> None:
    out = render_radar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=_DEFAULT_SANDBOX_REPORTS,
    )
    sandbox_groups = re.findall(
        r'<g class="sandbox"[^>]*>\s*<polygon[^>]*stroke="([^"]+)"',
        out,
    )
    assert len(sandbox_groups) == 2  # noqa: PLR2004
    assert sandbox_groups[0] != sandbox_groups[1]


def test_empty_sandbox_reports_still_renders_envelope() -> None:
    out = render_radar_chart_svg(
        real_reports=_DEFAULT_REAL_REPORTS,
        sandbox_reports=(),
    )
    assert '<g class="envelope">' in out
    assert '<g class="sandbox"' not in out


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #


def test_empty_real_reports_raises() -> None:
    with pytest.raises(ValueError, match="real_reports must be non-empty"):
        render_radar_chart_svg(real_reports=(), sandbox_reports=_DEFAULT_SANDBOX_REPORTS)


def test_real_report_category_mismatch_raises() -> None:
    real = (
        _real("real/a", {"site_shell": 0.9, "cart": 0.8}),
        _real("real/b", {"site_shell": 0.7, "product": 0.5}),  # cart vs product
    )
    with pytest.raises(ValueError, match="real report 'real/b' categories"):
        render_radar_chart_svg(real_reports=real, sandbox_reports=())


def test_sandbox_report_category_mismatch_raises() -> None:
    real = (_real("real/a", {"site_shell": 0.9, "cart": 0.8}),)
    sandbox = (_sandbox("sandbox/x", "pair_x", {"site_shell": 0.5}),)  # missing cart
    with pytest.raises(ValueError, match="sandbox report 'sandbox/x' categories"):
        render_radar_chart_svg(real_reports=real, sandbox_reports=sandbox)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _slice_group(svg: str, css_class: str) -> str:
    """Return the substring of ``svg`` containing the ``<g class="…">``."""
    match = re.search(
        rf'<g class="{re.escape(css_class)}"[\s\S]*?</g>',
        svg,
    )
    assert match is not None, f"group {css_class!r} not found in svg"
    return match.group(0)
