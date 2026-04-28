"""Paper figures (T6.2 — spec §8.4 row 2, §7 M6).

Renders the axis-A radar chart that visualizes per-category coverage:
the real-shop reference envelope shaded as a band, with each sandbox
overlaid as a polygon (spec §8.4 row 2). The figure visually answers
"do sandboxes fall inside the real-shop distribution?".

SVG output is fully deterministic from versioned
:class:`~shop_probe.report.ProbeReport`\\ s — no manual editing on the
path from JSON to figure (T6.2 acceptance check). Calling
:func:`render_radar_chart_svg` twice with the same inputs returns
byte-for-byte identical strings.

The module is import-safe: it performs no I/O at import time, no
matplotlib / cairo dependency, and emits a self-contained SVG document.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from shop_probe.report import ProbeReport

# --------------------------------------------------------------------------- #
# Geometry — pinned so figure output is byte-stable across runs.
# --------------------------------------------------------------------------- #

_SIZE: int = 600
"""Square canvas side, in user units (≈ pixels at 1x zoom)."""

_MARGIN: int = 110
"""Padding around the chart proper, leaving room for category labels."""

_CENTER_X: float = _SIZE / 2.0
_CENTER_Y: float = _SIZE / 2.0

_RADIUS: float = (_SIZE - 2 * _MARGIN) / 2.0
"""Maximum chart radius, corresponding to ``coverage = 1.0``."""

_LABEL_RADIAL_OFFSET: float = 18.0
"""Extra radial distance from the v=1.0 axis tip to the label baseline."""

_GRID_RING_VALUES: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0)
"""Concentric grid-ring coverage values."""

_FLOAT_FMT: str = ".3f"
"""Coordinate precision (three decimals → byte-stable SVG)."""

# --------------------------------------------------------------------------- #
# Style — fixed palette, no theme switching in v1.
# --------------------------------------------------------------------------- #

_GRID_STROKE: str = "#9ca3af"
_GRID_STROKE_OPACITY: float = 0.35
_AXIS_STROKE: str = "#6b7280"
_AXIS_STROKE_OPACITY: float = 0.5

_LABEL_FILL: str = "#111827"
_LABEL_FONT_SIZE: int = 12
_LEGEND_FONT_SIZE: int = 11

_ENVELOPE_FILL: str = "#3b82f6"
_ENVELOPE_FILL_OPACITY: float = 0.18
_ENVELOPE_STROKE: str = "#3b82f6"
_ENVELOPE_STROKE_OPACITY: float = 0.55
_ENVELOPE_LABEL: str = "real-shop envelope"

_SANDBOX_PALETTE: tuple[str, ...] = (
    "#ef4444",  # red
    "#10b981",  # green
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#06b6d4",  # cyan
)
"""Cycled colors for sandbox polygons (assigned by input order)."""

_SANDBOX_FILL_OPACITY: float = 0.0
"""Sandboxes are outline-only so the envelope band stays readable."""

_SANDBOX_STROKE_WIDTH: float = 2.0


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #


def render_radar_chart_svg(
    *,
    real_reports: Sequence[ProbeReport],
    sandbox_reports: Sequence[ProbeReport],
) -> str:
    """Render the axis-A radar chart as a deterministic SVG document.

    The radial axes are the per-category coverage axes, ordered
    alphabetically by category name (deterministic across runs). The
    shaded band is the per-category ``[min, max]`` envelope across
    ``real_reports``. Each sandbox in ``sandbox_reports`` is drawn as
    an outlined polygon labeled by ``target.label``.

    Args:
        real_reports: Real-shop reports that define the envelope. Must
            be non-empty and all share the same set of categories.
            Spec §5.2 specifies six real shops in the v1 cohort.
        sandbox_reports: Sandbox reports overlaid on the chart. May be
            empty (the chart still renders the envelope). Must share
            the same set of categories as ``real_reports``.

    Returns:
        A self-contained SVG string ending with a trailing newline.

    Raises:
        ValueError: ``real_reports`` is empty, or any report disagrees
            with ``real_reports[0]`` on its set of categories.
    """
    if not real_reports:
        msg = (
            "render_radar_chart_svg: real_reports must be non-empty "
            "(the envelope is undefined without a real-shop population)"
        )
        raise ValueError(msg)

    categories = sorted(_categories_of(real_reports[0]))
    expected = set(categories)
    for report in real_reports[1:]:
        actual = set(_categories_of(report))
        if actual != expected:
            msg = (
                f"render_radar_chart_svg: real report {report.target.label!r} "
                f"categories {sorted(actual)} disagree with {categories}"
            )
            raise ValueError(msg)
    for report in sandbox_reports:
        actual = set(_categories_of(report))
        if actual != expected:
            msg = (
                f"render_radar_chart_svg: sandbox report {report.target.label!r} "
                f"categories {sorted(actual)} disagree with {categories}"
            )
            raise ValueError(msg)

    angles = _category_angles(len(categories))
    envelope = _compute_envelope(real_reports, categories)

    layers: list[str] = [
        _svg_open(),
        _grid_rings(),
        _axes(angles),
        _category_labels(categories, angles),
        _envelope_path(envelope, categories, angles),
        *(
            _sandbox_polygon(
                report,
                categories,
                angles,
                _SANDBOX_PALETTE[i % len(_SANDBOX_PALETTE)],
            )
            for i, report in enumerate(sandbox_reports)
        ),
        _legend(sandbox_reports),
        "</svg>",
    ]
    return "\n".join(layers) + "\n"


# --------------------------------------------------------------------------- #
# Pure helpers — no I/O, no mutation.
# --------------------------------------------------------------------------- #


def _categories_of(report: ProbeReport) -> dict[str, float]:
    """Return ``category -> coverage`` for one report."""
    return {c.category: c.coverage for c in report.categories}


def _category_angles(n: int) -> tuple[float, ...]:
    """Per-axis angles, equally spaced, first axis pointing up.

    SVG y-axis grows downward, so "up" is angle ``-π/2``. Subsequent
    axes proceed clockwise (angle increases).
    """
    if n == 0:
        msg = "_category_angles: at least one category is required"
        raise ValueError(msg)
    step = 2.0 * math.pi / n
    return tuple(-math.pi / 2.0 + i * step for i in range(n))


def _compute_envelope(
    real_reports: Sequence[ProbeReport],
    categories: Sequence[str],
) -> dict[str, tuple[float, float]]:
    """Per-category ``(min, max)`` coverage across the real-shop population."""
    out: dict[str, tuple[float, float]] = {}
    for category in categories:
        values = [_categories_of(r)[category] for r in real_reports]
        out[category] = (min(values), max(values))
    return out


def _polar(value: float, angle: float) -> tuple[float, float]:
    """Map ``(coverage, angle)`` to an absolute SVG ``(x, y)``."""
    r = value * _RADIUS
    return (_CENTER_X + r * math.cos(angle), _CENTER_Y + r * math.sin(angle))


def _fmt(value: float) -> str:
    """Format a coordinate component with the pinned precision.

    Negative-zero (``-0.000``) is folded to ``0.000`` so byte-stability
    survives floating-point noise around ``cos(±π/2)``.
    """
    formatted = f"{value:{_FLOAT_FMT}}"
    if formatted == f"-{0.0:{_FLOAT_FMT}}":
        return f"{0.0:{_FLOAT_FMT}}"
    return formatted


def _polygon_points(
    coverages: dict[str, float],
    categories: Sequence[str],
    angles: Sequence[float],
) -> str:
    """``x,y x,y …`` string for an SVG ``<polygon points=…>`` attribute."""
    pts: list[str] = []
    for category, angle in zip(categories, angles, strict=True):
        x, y = _polar(coverages[category], angle)
        pts.append(f"{_fmt(x)},{_fmt(y)}")
    return " ".join(pts)


# --------------------------------------------------------------------------- #
# SVG layer builders.
# --------------------------------------------------------------------------- #


def _svg_open() -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_SIZE} {_SIZE}" '
        f'width="{_SIZE}" height="{_SIZE}" '
        f'role="img" aria-label="Per-category coverage radar chart">'
    )


def _grid_rings() -> str:
    parts: list[str] = ['<g class="grid">']
    for value in _GRID_RING_VALUES:
        r = value * _RADIUS
        parts.append(
            f'<circle cx="{_fmt(_CENTER_X)}" cy="{_fmt(_CENTER_Y)}" '
            f'r="{_fmt(r)}" fill="none" '
            f'stroke="{_GRID_STROKE}" stroke-opacity="{_GRID_STROKE_OPACITY}" '
            f'stroke-width="1"/>'
        )
    parts.append("</g>")
    return "\n".join(parts)


def _axes(angles: Sequence[float]) -> str:
    parts: list[str] = ['<g class="axes">']
    for angle in angles:
        x, y = _polar(1.0, angle)
        parts.append(
            f'<line x1="{_fmt(_CENTER_X)}" y1="{_fmt(_CENTER_Y)}" '
            f'x2="{_fmt(x)}" y2="{_fmt(y)}" '
            f'stroke="{_AXIS_STROKE}" stroke-opacity="{_AXIS_STROKE_OPACITY}" '
            f'stroke-width="1"/>'
        )
    parts.append("</g>")
    return "\n".join(parts)


def _category_labels(
    categories: Sequence[str],
    angles: Sequence[float],
) -> str:
    parts: list[str] = ['<g class="category-labels">']
    label_radius = _RADIUS + _LABEL_RADIAL_OFFSET
    for category, angle in zip(categories, angles, strict=True):
        x = _CENTER_X + label_radius * math.cos(angle)
        y = _CENTER_Y + label_radius * math.sin(angle)
        anchor = _label_text_anchor(angle)
        baseline = _label_baseline(angle)
        parts.append(
            f'<text x="{_fmt(x)}" y="{_fmt(y)}" '
            f'font-size="{_LABEL_FONT_SIZE}" fill="{_LABEL_FILL}" '
            f'text-anchor="{anchor}" dominant-baseline="{baseline}">'
            f"{_xml_escape(category)}</text>"
        )
    parts.append("</g>")
    return "\n".join(parts)


_LABEL_AXIS_BEARING_EPSILON: float = 0.1
"""Cosine/sine threshold below which an axis is treated as vertical /
horizontal for label placement."""


def _label_text_anchor(angle: float) -> str:
    """Pick an SVG ``text-anchor`` based on the axis bearing."""
    cx = math.cos(angle)
    if cx > _LABEL_AXIS_BEARING_EPSILON:
        return "start"
    if cx < -_LABEL_AXIS_BEARING_EPSILON:
        return "end"
    return "middle"


def _label_baseline(angle: float) -> str:
    """Pick an SVG ``dominant-baseline`` based on the axis bearing."""
    cy = math.sin(angle)
    if cy < -_LABEL_AXIS_BEARING_EPSILON:
        return "auto"  # label sits above the axis tip
    if cy > _LABEL_AXIS_BEARING_EPSILON:
        return "hanging"  # label sits below the axis tip
    return "middle"


def _envelope_path(
    envelope: dict[str, tuple[float, float]],
    categories: Sequence[str],
    angles: Sequence[float],
) -> str:
    """SVG ``<path>`` for the annulus between per-category min and max."""
    outer_pts = [_polar(envelope[c][1], a) for c, a in zip(categories, angles, strict=True)]
    inner_pts = [_polar(envelope[c][0], a) for c, a in zip(categories, angles, strict=True)]
    # Two sub-paths + fill-rule="evenodd" → annulus (outer ring minus inner ring).
    d = f"{_path_d(outer_pts)} {_path_d(inner_pts)}"
    return (
        '<g class="envelope">'
        f'<path d="{d}" fill-rule="evenodd" '
        f'fill="{_ENVELOPE_FILL}" fill-opacity="{_ENVELOPE_FILL_OPACITY}" '
        f'stroke="{_ENVELOPE_STROKE}" stroke-opacity="{_ENVELOPE_STROKE_OPACITY}" '
        'stroke-width="1"/>'
        "</g>"
    )


def _path_d(points: Sequence[tuple[float, float]]) -> str:
    """Build a closed SVG path ``d`` attribute from polygon vertices."""
    if not points:
        return ""
    head = points[0]
    cmds = [f"M {_fmt(head[0])} {_fmt(head[1])}"]
    for x, y in points[1:]:
        cmds.append(f"L {_fmt(x)} {_fmt(y)}")
    cmds.append("Z")
    return " ".join(cmds)


def _sandbox_polygon(
    report: ProbeReport,
    categories: Sequence[str],
    angles: Sequence[float],
    color: str,
) -> str:
    coverages = _categories_of(report)
    points = _polygon_points(coverages, categories, angles)
    label = _xml_escape(report.target.label)
    return (
        f'<g class="sandbox" data-label="{label}">'
        f'<polygon points="{points}" '
        f'fill="{color}" fill-opacity="{_SANDBOX_FILL_OPACITY}" '
        f'stroke="{color}" stroke-width="{_SANDBOX_STROKE_WIDTH}"/>'
        "</g>"
    )


def _legend(sandbox_reports: Sequence[ProbeReport]) -> str:
    """Render a legend listing the envelope band and each sandbox."""
    parts: list[str] = ['<g class="legend">']
    x = float(_MARGIN) - 90.0  # left-anchored, just inside the canvas margin.
    y = float(_SIZE - _MARGIN + 50)
    line_height = 18.0
    swatch_size = 12.0

    def _entry(row: int, color: str, fill_opacity: float, label: str) -> list[str]:
        rect_y = y + row * line_height - swatch_size + 2
        text_y = y + row * line_height
        return [
            f'<rect x="{_fmt(x)}" y="{_fmt(rect_y)}" '
            f'width="{_fmt(swatch_size)}" height="{_fmt(swatch_size)}" '
            f'fill="{color}" fill-opacity="{fill_opacity}" '
            f'stroke="{color}" stroke-width="1"/>',
            f'<text x="{_fmt(x + swatch_size + 6.0)}" y="{_fmt(text_y)}" '
            f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
            f'dominant-baseline="middle">{_xml_escape(label)}</text>',
        ]

    parts.extend(_entry(0, _ENVELOPE_FILL, _ENVELOPE_FILL_OPACITY, _ENVELOPE_LABEL))
    for i, report in enumerate(sandbox_reports):
        color = _SANDBOX_PALETTE[i % len(_SANDBOX_PALETTE)]
        parts.extend(_entry(i + 1, color, 0.0, report.target.label))
    parts.append("</g>")
    return "\n".join(parts)


def _xml_escape(text: str) -> str:
    """Minimal XML escape for SVG attribute / text node content."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
