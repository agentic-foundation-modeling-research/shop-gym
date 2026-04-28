"""Axis-B surface bar chart (T6.3 — spec §8.4 row 3, §7 M6).

Renders the per-metric range-bar chart that visualizes the surface area
of sandbox + source storefronts against the ``[min, max]`` envelope over
the 6 real shops (spec §8.4 row 3). One row per
:class:`~shop_probe.surface.metrics.SurfaceMetrics` field, with:

* a shaded range bar marking the per-metric ``[min, max]`` over
  ``real_reports``;
* one outlined-circle marker per sandbox value;
* one filled-triangle marker per source value;
* per-row scaling — each metric uses its own ``[0, max]`` x-axis since
  ``catalog_products`` and ``median_dom_kb_gz`` live on incompatible
  numeric scales.

SVG output is fully deterministic from versioned
:class:`~shop_probe.report.ProbeReport`\\ s — paper figures must be
reproducible from the JSON on disk (T6.3 acceptance check). Calling
:func:`render_surface_bar_chart_svg` twice with the same inputs returns
byte-for-byte identical strings.

The module is import-safe: it performs no I/O at import time, no
matplotlib / cairo dependency, and emits a self-contained SVG document.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shop_probe.report import ProbeReport
from shop_probe.surface.metrics import SurfaceMetrics

# --------------------------------------------------------------------------- #
# Geometry — pinned so figure output is byte-stable across runs.
# --------------------------------------------------------------------------- #

_WIDTH: int = 760
"""Canvas width, in user units (≈ pixels at 1x zoom)."""

_LABEL_X: float = 16.0
"""Left margin for metric labels."""

_LABEL_WIDTH: float = 248.0
"""Reserved width for the metric label column."""

_BAR_LEFT: float = _LABEL_X + _LABEL_WIDTH
"""Left edge of the range-bar plot area."""

_BAR_RIGHT_PADDING: float = 96.0
"""Right margin reserved for the per-row max-value annotation."""

_BAR_RIGHT: float = float(_WIDTH) - _BAR_RIGHT_PADDING
"""Right edge of the range-bar plot area."""

_BAR_WIDTH: float = _BAR_RIGHT - _BAR_LEFT
"""Plot-area width per row."""

_HEADER_HEIGHT: float = 32.0
"""Vertical space reserved for the chart title."""

_ROW_HEIGHT: float = 32.0
"""Vertical step between successive metric rows."""

_ROW_TOP_PADDING: float = 8.0
"""Vertical padding before the first metric row."""

_BAR_HEIGHT: float = 14.0
"""Range-bar (rectangle) thickness."""

_LEGEND_HEIGHT: float = 56.0
"""Vertical space reserved for the legend below the rows."""

_AXIS_TICK_LEN: float = 4.0
"""Length of the per-row 0/max baseline ticks."""

_FLOAT_FMT: str = ".3f"
"""Coordinate precision (three decimals → byte-stable SVG)."""

_VALUE_FMT: str = ".3g"
"""Numeric precision for value annotations (significant figures)."""

# --------------------------------------------------------------------------- #
# Style — fixed palette, no theme switching in v1.
# --------------------------------------------------------------------------- #

_LABEL_FILL: str = "#111827"
_LABEL_FONT_SIZE: int = 12
_VALUE_FONT_SIZE: int = 10
_LEGEND_FONT_SIZE: int = 11

_AXIS_STROKE: str = "#9ca3af"
_AXIS_STROKE_OPACITY: float = 0.5

_ENVELOPE_FILL: str = "#3b82f6"
_ENVELOPE_FILL_OPACITY: float = 0.22
_ENVELOPE_STROKE: str = "#3b82f6"
_ENVELOPE_STROKE_OPACITY: float = 0.7
_ENVELOPE_LABEL: str = "real-shop envelope"

_SANDBOX_PALETTE: tuple[str, ...] = (
    "#ef4444",  # red
    "#10b981",  # green
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#06b6d4",  # cyan
)
"""Cycled colors for sandbox + source markers (assigned by input order)."""

_SANDBOX_MARKER_RADIUS: float = 5.0
"""Outlined-circle radius for sandbox markers."""

_SOURCE_MARKER_HALF: float = 5.0
"""Half-side of the equilateral triangle used for source markers."""

# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _RowData:
    """Pre-computed plotting inputs for one metric row."""

    metric: str
    real_min: float
    real_max: float
    sandbox_values: tuple[float, ...]
    source_values: tuple[float, ...]
    scale_max: float


def render_surface_bar_chart_svg(
    *,
    real_reports: Sequence[ProbeReport],
    sandbox_reports: Sequence[ProbeReport],
    source_reports: Sequence[ProbeReport],
) -> str:
    """Render the axis-B surface bar chart as a deterministic SVG document.

    One row per :class:`SurfaceMetrics` field, in declaration order. Each
    row shows the ``[min, max]`` envelope across ``real_reports`` as a
    shaded band, with sandbox values overlaid as outlined circles and
    source values as filled triangles. Per-row scaling means each metric
    uses its own ``[0, scale_max]`` x-axis.

    Args:
        real_reports: Real-shop reports that define the envelope. Must
            be non-empty and each must carry a populated
            :attr:`~shop_probe.report.ProbeReport.surface`. Spec §5.2
            specifies six real shops in the v1 cohort.
        sandbox_reports: Sandbox reports whose values are overlaid as
            circles. May be empty. Each must carry a populated
            ``surface``.
        source_reports: Source reports whose values are overlaid as
            triangles. May be empty. Each must carry a populated
            ``surface``.

    Returns:
        A self-contained SVG string ending with a trailing newline.

    Raises:
        ValueError: ``real_reports`` is empty, or any provided report is
            missing its surface metrics.
    """
    if not real_reports:
        msg = (
            "render_surface_bar_chart_svg: real_reports must be non-empty "
            "(the envelope is undefined without a real-shop population)"
        )
        raise ValueError(msg)

    real_surfaces = _surfaces_of("real", real_reports)
    sandbox_surfaces = _surfaces_of("sandbox", sandbox_reports)
    source_surfaces = _surfaces_of("source", source_reports)

    metrics = tuple(SurfaceMetrics.model_fields.keys())
    rows = tuple(
        _row_data(metric, real_surfaces, sandbox_surfaces, source_surfaces) for metric in metrics
    )

    height = int(_HEADER_HEIGHT + _ROW_TOP_PADDING + _ROW_HEIGHT * len(rows) + _LEGEND_HEIGHT)

    layers: list[str] = [
        _svg_open(height),
        _header(),
        *(_render_row(i, row) for i, row in enumerate(rows)),
        _legend(height, sandbox_reports, source_reports),
        "</svg>",
    ]
    return "\n".join(layers) + "\n"


# --------------------------------------------------------------------------- #
# Pure helpers — no I/O, no mutation.
# --------------------------------------------------------------------------- #


def _surfaces_of(role: str, reports: Sequence[ProbeReport]) -> list[SurfaceMetrics]:
    """Pull ``report.surface`` from every report; raise if any is missing."""
    out: list[SurfaceMetrics] = []
    for report in reports:
        if report.surface is None:
            msg = (
                f"render_surface_bar_chart_svg: {role} report "
                f"{report.target.label!r} is missing surface metrics "
                "(re-run with --axes A,B)"
            )
            raise ValueError(msg)
        out.append(report.surface)
    return out


def _row_data(
    metric: str,
    real_surfaces: Sequence[SurfaceMetrics],
    sandbox_surfaces: Sequence[SurfaceMetrics],
    source_surfaces: Sequence[SurfaceMetrics],
) -> _RowData:
    """Compute envelope + overlay values + per-row scale for one metric."""
    real_values = [float(getattr(s, metric)) for s in real_surfaces]
    sandbox_values = tuple(float(getattr(s, metric)) for s in sandbox_surfaces)
    source_values = tuple(float(getattr(s, metric)) for s in source_surfaces)

    real_min = min(real_values)
    real_max = max(real_values)
    observed_max = max((real_max, *sandbox_values, *source_values))
    # Pad the row a bit so markers at the upper edge stay legible; clamp
    # to 1.0 so all-zero rows still render a visible empty axis.
    scale_max = max(observed_max * 1.1, 1.0)
    return _RowData(
        metric=metric,
        real_min=real_min,
        real_max=real_max,
        sandbox_values=sandbox_values,
        source_values=source_values,
        scale_max=scale_max,
    )


def _value_to_x(value: float, scale_max: float) -> float:
    """Map a per-row metric value to an absolute SVG x coordinate."""
    return _BAR_LEFT + (value / scale_max) * _BAR_WIDTH


def _row_top(index: int) -> float:
    """Top y of the row's plot band."""
    return _HEADER_HEIGHT + _ROW_TOP_PADDING + index * _ROW_HEIGHT


def _row_center(index: int) -> float:
    """Vertical center of the row's range bar."""
    return _row_top(index) + _ROW_HEIGHT / 2.0


def _fmt(value: float) -> str:
    """Format a coordinate component with the pinned precision.

    Negative-zero (``-0.000``) is folded to ``0.000`` so byte-stability
    survives floating-point noise around the y-axis.
    """
    formatted = f"{value:{_FLOAT_FMT}}"
    if formatted == f"-{0.0:{_FLOAT_FMT}}":
        return f"{0.0:{_FLOAT_FMT}}"
    return formatted


def _fmt_value(value: float) -> str:
    """Format a metric value for the per-row max-value annotation."""
    return f"{value:{_VALUE_FMT}}"


def _xml_escape(text: str) -> str:
    """Minimal XML escape for SVG attribute / text node content."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# --------------------------------------------------------------------------- #
# SVG layer builders.
# --------------------------------------------------------------------------- #


def _svg_open(height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_WIDTH} {height}" '
        f'width="{_WIDTH}" height="{height}" '
        f'role="img" aria-label="Per-metric surface bar chart">'
    )


def _header() -> str:
    return (
        f'<g class="header">'
        f'<text x="{_fmt(_LABEL_X)}" y="{_fmt(_HEADER_HEIGHT - 12.0)}" '
        f'font-size="{_LABEL_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'font-weight="bold">'
        f"Surface metrics — sandbox + source vs. real-shop envelope"
        f"</text>"
        f"</g>"
    )


def _render_row(index: int, row: _RowData) -> str:
    parts: list[str] = [f'<g class="row" data-metric="{_xml_escape(row.metric)}">']
    parts.append(_row_label(index, row))
    parts.append(_row_baseline(index, row))
    parts.append(_row_envelope(index, row))
    parts.extend(_row_sandbox_markers(index, row))
    parts.extend(_row_source_markers(index, row))
    parts.append(_row_scale_annotation(index, row))
    parts.append("</g>")
    return "\n".join(parts)


def _row_label(index: int, row: _RowData) -> str:
    y = _row_center(index) + 4.0  # nudge for visual centering
    return (
        f'<text x="{_fmt(_LABEL_X)}" y="{_fmt(y)}" '
        f'font-size="{_LABEL_FONT_SIZE}" fill="{_LABEL_FILL}">'
        f"{_xml_escape(row.metric)}</text>"
    )


def _row_baseline(index: int, row: _RowData) -> str:
    """Horizontal axis line + 0 / scale_max ticks for this row."""
    del row  # ticks share geometry across rows; row arg kept for symmetry.
    y = _row_center(index) + _BAR_HEIGHT / 2.0 + 4.0
    return (
        f'<g class="baseline">'
        f'<line x1="{_fmt(_BAR_LEFT)}" y1="{_fmt(y)}" '
        f'x2="{_fmt(_BAR_RIGHT)}" y2="{_fmt(y)}" '
        f'stroke="{_AXIS_STROKE}" stroke-opacity="{_AXIS_STROKE_OPACITY}" '
        f'stroke-width="1"/>'
        f'<line x1="{_fmt(_BAR_LEFT)}" y1="{_fmt(y)}" '
        f'x2="{_fmt(_BAR_LEFT)}" y2="{_fmt(y + _AXIS_TICK_LEN)}" '
        f'stroke="{_AXIS_STROKE}" stroke-opacity="{_AXIS_STROKE_OPACITY}" '
        f'stroke-width="1"/>'
        f'<line x1="{_fmt(_BAR_RIGHT)}" y1="{_fmt(y)}" '
        f'x2="{_fmt(_BAR_RIGHT)}" y2="{_fmt(y + _AXIS_TICK_LEN)}" '
        f'stroke="{_AXIS_STROKE}" stroke-opacity="{_AXIS_STROKE_OPACITY}" '
        f'stroke-width="1"/>'
        f"</g>"
    )


def _row_envelope(index: int, row: _RowData) -> str:
    """Shaded ``[min, max]`` rectangle for the real-shop envelope."""
    x_min = _value_to_x(row.real_min, row.scale_max)
    x_max = _value_to_x(row.real_max, row.scale_max)
    # Floor at one unit so a degenerate min == max still renders visibly.
    width = max(x_max - x_min, 1.0)
    y = _row_center(index) - _BAR_HEIGHT / 2.0
    return (
        f'<rect class="envelope" '
        f'x="{_fmt(x_min)}" y="{_fmt(y)}" '
        f'width="{_fmt(width)}" height="{_fmt(_BAR_HEIGHT)}" '
        f'fill="{_ENVELOPE_FILL}" fill-opacity="{_ENVELOPE_FILL_OPACITY}" '
        f'stroke="{_ENVELOPE_STROKE}" stroke-opacity="{_ENVELOPE_STROKE_OPACITY}" '
        f'stroke-width="1"/>'
    )


def _row_sandbox_markers(index: int, row: _RowData) -> list[str]:
    """One outlined circle per sandbox value (color cycled by input order)."""
    parts: list[str] = []
    cy = _row_center(index)
    for i, value in enumerate(row.sandbox_values):
        cx = _value_to_x(value, row.scale_max)
        color = _SANDBOX_PALETTE[i % len(_SANDBOX_PALETTE)]
        parts.append(
            f'<circle class="sandbox" data-index="{i}" '
            f'cx="{_fmt(cx)}" cy="{_fmt(cy)}" '
            f'r="{_fmt(_SANDBOX_MARKER_RADIUS)}" '
            f'fill="white" stroke="{color}" stroke-width="2"/>'
        )
    return parts


def _row_source_markers(index: int, row: _RowData) -> list[str]:
    """One filled triangle per source value (color cycled by input order)."""
    parts: list[str] = []
    cy = _row_center(index)
    h = _SOURCE_MARKER_HALF
    for i, value in enumerate(row.source_values):
        cx = _value_to_x(value, row.scale_max)
        color = _SANDBOX_PALETTE[i % len(_SANDBOX_PALETTE)]
        # Equilateral triangle pointing up.
        points = (
            f"{_fmt(cx)},{_fmt(cy - h)} {_fmt(cx - h)},{_fmt(cy + h)} {_fmt(cx + h)},{_fmt(cy + h)}"
        )
        parts.append(
            f'<polygon class="source" data-index="{i}" '
            f'points="{points}" '
            f'fill="{color}" stroke="{color}" stroke-width="1"/>'
        )
    return parts


def _row_scale_annotation(index: int, row: _RowData) -> str:
    """Right-aligned ``max=…`` label printed at the row's right padding."""
    x = _BAR_RIGHT + 6.0
    y = _row_center(index) + 4.0
    return (
        f'<text x="{_fmt(x)}" y="{_fmt(y)}" '
        f'font-size="{_VALUE_FONT_SIZE}" fill="{_LABEL_FILL}">'
        f"max={_xml_escape(_fmt_value(row.scale_max))}</text>"
    )


def _legend(
    height: int,
    sandbox_reports: Sequence[ProbeReport],
    source_reports: Sequence[ProbeReport],
) -> str:
    """Legend strip listing the envelope and per-pair marker colors."""
    parts: list[str] = ['<g class="legend">']
    base_y = float(height) - _LEGEND_HEIGHT + 18.0
    x = _LABEL_X
    swatch = 12.0

    # Envelope swatch.
    parts.append(
        f'<rect x="{_fmt(x)}" y="{_fmt(base_y - swatch + 2.0)}" '
        f'width="{_fmt(swatch)}" height="{_fmt(swatch)}" '
        f'fill="{_ENVELOPE_FILL}" fill-opacity="{_ENVELOPE_FILL_OPACITY}" '
        f'stroke="{_ENVELOPE_STROKE}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{_fmt(x + swatch + 6.0)}" y="{_fmt(base_y)}" '
        f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'dominant-baseline="middle">{_xml_escape(_ENVELOPE_LABEL)}</text>'
    )

    # Sandbox swatches.
    cursor_x = x + 180.0
    for i, report in enumerate(sandbox_reports):
        color = _SANDBOX_PALETTE[i % len(_SANDBOX_PALETTE)]
        cx = cursor_x + 6.0
        cy = base_y - 4.0
        parts.append(
            f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" '
            f'r="{_fmt(_SANDBOX_MARKER_RADIUS)}" '
            f'fill="white" stroke="{color}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{_fmt(cx + 12.0)}" y="{_fmt(base_y)}" '
            f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
            f'dominant-baseline="middle">'
            f"sandbox: {_xml_escape(report.target.label)}</text>"
        )
        base_y += 16.0

    # Source swatches.
    cursor_x = x + 180.0
    for i, report in enumerate(source_reports):
        color = _SANDBOX_PALETTE[i % len(_SANDBOX_PALETTE)]
        cx = cursor_x + 6.0
        cy = base_y - 4.0
        h = _SOURCE_MARKER_HALF
        points = (
            f"{_fmt(cx)},{_fmt(cy - h)} {_fmt(cx - h)},{_fmt(cy + h)} {_fmt(cx + h)},{_fmt(cy + h)}"
        )
        parts.append(
            f'<polygon points="{points}" fill="{color}" stroke="{color}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{_fmt(cx + 12.0)}" y="{_fmt(base_y)}" '
            f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
            f'dominant-baseline="middle">'
            f"source: {_xml_escape(report.target.label)}</text>"
        )
        base_y += 16.0

    parts.append("</g>")
    return "\n".join(parts)
