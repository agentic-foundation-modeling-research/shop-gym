"""Axis-C Turing chart (web_probe_patch.md).

Renders a deterministic SVG bar chart visualising group-level judge
accuracy. Two bars side-by-side:

* ``sandbox`` — fraction of judge calls on sandbox-group reports whose
  ``predicted_label == "sandbox"``.
* ``real`` — fraction of judge calls on real-group reports whose
  ``predicted_label == "real"``.

A horizontal annotation line marks the indistinguishability gap
``|real - sandbox|`` — closer to ``0`` means the judge cannot tell the
two groups apart.

A vertical reference line at ``acc = 0.5`` marks the chance-rate target
for context.

SVG output is fully deterministic from the input :class:`BenchComparison`
— no manual editing on the path from JSON to figure.

The module is import-safe: it performs no I/O at import time, no
matplotlib / cairo dependency, and emits a self-contained SVG document.
"""

from __future__ import annotations

from shop_probe.fidelity import BenchComparison

# --------------------------------------------------------------------------- #
# Geometry — pinned so figure output is byte-stable across runs.
# --------------------------------------------------------------------------- #

_WIDTH: int = 640
_HEIGHT: int = 320

_LABEL_X: float = 16.0
_HEADER_HEIGHT: float = 36.0
_LEGEND_HEIGHT: float = 56.0

_AXIS_LEFT: float = 120.0
_AXIS_RIGHT_PADDING: float = 96.0
_AXIS_RIGHT: float = float(_WIDTH) - _AXIS_RIGHT_PADDING

_AXIS_TOP: float = _HEADER_HEIGHT + 20.0
_AXIS_BOTTOM: float = float(_HEIGHT) - _LEGEND_HEIGHT - 20.0
_AXIS_HEIGHT: float = _AXIS_BOTTOM - _AXIS_TOP

_BAR_HEIGHT: float = 24.0
_BAR_GAP: float = 14.0

_FLOAT_FMT: str = ".3f"
_VALUE_FMT: str = ".3f"

# --------------------------------------------------------------------------- #
# Style — fixed palette.
# --------------------------------------------------------------------------- #

_LABEL_FILL: str = "#111827"
_LABEL_FONT_SIZE: int = 12
_VALUE_FONT_SIZE: int = 11
_HEADER_FONT_SIZE: int = 13
_LEGEND_FONT_SIZE: int = 11

_AXIS_STROKE: str = "#9ca3af"
_AXIS_STROKE_OPACITY: float = 0.7

_REFERENCE_STROKE: str = "#6b7280"
"""Color of the ``acc = 0.5`` chance-rate reference line."""

_SANDBOX_FILL: str = "#ef4444"
"""Bar color for the sandbox group."""

_REAL_FILL: str = "#3b82f6"
"""Bar color for the real group."""

_GAP_STROKE: str = "#0ea5e9"
"""Color of the ``|real - sandbox|`` gap annotation."""

_AXIS_TICKS: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)


def render_turing_chart_svg(comparison: BenchComparison) -> str:
    """Render the axis-C Turing chart as a deterministic SVG document.

    Args:
        comparison: A validated :class:`BenchComparison` carrying group
            judge accuracies and the indistinguishability gap.

    Returns:
        A self-contained SVG string ending with a trailing newline.

    Raises:
        ValueError: Either group lacks judge calls (the chart is
            undefined without both group accuracies).
    """
    sandbox_acc = comparison.sandbox.judge_accuracy
    real_acc = comparison.real.judge_accuracy
    if sandbox_acc is None or real_acc is None:
        msg = (
            "render_turing_chart_svg: both groups must have judge calls "
            f"(sandbox judge_calls_total={comparison.sandbox.judge_calls_total}, "
            f"real judge_calls_total={comparison.real.judge_calls_total})"
        )
        raise ValueError(msg)

    layers: list[str] = [
        _svg_open(),
        _header(),
        _x_axis(),
        _reference_line(0.5),
        _bar(0, "sandbox", sandbox_acc, _SANDBOX_FILL),
        _bar(1, "real", real_acc, _REAL_FILL),
        _gap_annotation(comparison.judge_indistinguishability),
        _legend(comparison),
        "</svg>",
    ]
    return "\n".join(layers) + "\n"


# --------------------------------------------------------------------------- #
# SVG helpers.
# --------------------------------------------------------------------------- #


def _value_to_x(value: float) -> float:
    """Map ``acc ∈ [0, 1]`` to an absolute SVG x coordinate."""
    return _AXIS_LEFT + max(0.0, min(1.0, value)) * (_AXIS_RIGHT - _AXIS_LEFT)


def _bar_top(index: int) -> float:
    """Top y of bar ``index`` (0 = sandbox, 1 = real)."""
    rows_total_height = 2 * _BAR_HEIGHT + _BAR_GAP
    rows_top = _AXIS_TOP + (_AXIS_HEIGHT - rows_total_height) / 2.0
    return rows_top + index * (_BAR_HEIGHT + _BAR_GAP)


def _bar_center(index: int) -> float:
    return _bar_top(index) + _BAR_HEIGHT / 2.0


def _fmt(value: float) -> str:
    formatted = f"{value:{_FLOAT_FMT}}"
    if formatted == f"-{0.0:{_FLOAT_FMT}}":
        return f"{0.0:{_FLOAT_FMT}}"
    return formatted


def _fmt_value(value: float) -> str:
    return f"{value:{_VALUE_FMT}}"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _svg_open() -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_WIDTH} {_HEIGHT}" '
        f'width="{_WIDTH}" height="{_HEIGHT}" '
        f'role="img" aria-label="Group-level judge accuracy chart">'
    )


def _header() -> str:
    return (
        f'<g class="header">'
        f'<text x="{_fmt(_LABEL_X)}" y="{_fmt(_HEADER_HEIGHT - 14.0)}" '
        f'font-size="{_HEADER_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'font-weight="bold">'
        f"Judge accuracy — sandbox group vs. real group"
        f"</text>"
        f"</g>"
    )


def _x_axis() -> str:
    parts: list[str] = ['<g class="x-axis">']
    y = _AXIS_BOTTOM + 4.0
    parts.append(
        f'<line x1="{_fmt(_AXIS_LEFT)}" y1="{_fmt(y)}" '
        f'x2="{_fmt(_AXIS_RIGHT)}" y2="{_fmt(y)}" '
        f'stroke="{_AXIS_STROKE}" stroke-opacity="{_AXIS_STROKE_OPACITY}" '
        f'stroke-width="1"/>'
    )
    for tick in _AXIS_TICKS:
        x = _value_to_x(tick)
        parts.append(
            f'<line x1="{_fmt(x)}" y1="{_fmt(y)}" '
            f'x2="{_fmt(x)}" y2="{_fmt(y + 4.0)}" '
            f'stroke="{_AXIS_STROKE}" stroke-opacity="{_AXIS_STROKE_OPACITY}" '
            f'stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{_fmt(x)}" y="{_fmt(y + 18.0)}" '
            f'font-size="{_VALUE_FONT_SIZE}" fill="{_LABEL_FILL}" '
            f'text-anchor="middle">{_fmt_value(tick)}</text>'
        )
    parts.append("</g>")
    return "\n".join(parts)


def _reference_line(value: float) -> str:
    x = _value_to_x(value)
    return (
        f'<g class="reference" data-value="{_fmt_value(value)}">'
        f'<line x1="{_fmt(x)}" y1="{_fmt(_AXIS_TOP)}" '
        f'x2="{_fmt(x)}" y2="{_fmt(_AXIS_BOTTOM)}" '
        f'stroke="{_REFERENCE_STROKE}" stroke-opacity="0.8" '
        f'stroke-width="1" stroke-dasharray="4 3"/>'
        f"</g>"
    )


def _bar(index: int, label: str, accuracy: float, color: str) -> str:
    """One filled bar for a group."""
    x_lo = _AXIS_LEFT
    x_hi = _value_to_x(accuracy)
    width = max(x_hi - x_lo, 0.0)
    y = _bar_top(index)
    label_y = _bar_center(index) + 4.0
    annotation_x = x_hi + 6.0
    return (
        f'<g class="bar" data-group="{_xml_escape(label)}">'
        f'<text x="{_fmt(_LABEL_X)}" y="{_fmt(label_y)}" '
        f'font-size="{_LABEL_FONT_SIZE}" fill="{_LABEL_FILL}">'
        f"{_xml_escape(label)}</text>"
        f'<rect x="{_fmt(x_lo)}" y="{_fmt(y)}" '
        f'width="{_fmt(width)}" height="{_fmt(_BAR_HEIGHT)}" '
        f'fill="{color}" fill-opacity="0.7" '
        f'stroke="{color}" stroke-width="1"/>'
        f'<text x="{_fmt(annotation_x)}" y="{_fmt(label_y)}" '
        f'font-size="{_VALUE_FONT_SIZE}" fill="{_LABEL_FILL}">'
        f"acc={_fmt_value(accuracy)}</text>"
        f"</g>"
    )


def _gap_annotation(gap: float | None) -> str:
    """Centered annotation reporting ``|real - sandbox|``."""
    text = "|real - sandbox| = \u2014" if gap is None else f"|real - sandbox| = {_fmt_value(gap)}"
    x = _LABEL_X
    y = _AXIS_BOTTOM - 6.0
    return (
        f'<g class="gap">'
        f'<text x="{_fmt(x)}" y="{_fmt(y)}" '
        f'font-size="{_VALUE_FONT_SIZE}" fill="{_GAP_STROKE}" '
        f'font-weight="bold">{_xml_escape(text)}</text>'
        f"</g>"
    )


def _legend(comparison: BenchComparison) -> str:
    """Legend strip describing the bars and the chance-rate reference."""
    parts: list[str] = ['<g class="legend">']
    base_y = float(_HEIGHT) - _LEGEND_HEIGHT + 18.0
    x = _LABEL_X
    swatch = 12.0

    # Sandbox swatch.
    parts.append(
        f'<rect x="{_fmt(x)}" y="{_fmt(base_y - swatch + 2.0)}" '
        f'width="{_fmt(swatch)}" height="{_fmt(swatch)}" '
        f'fill="{_SANDBOX_FILL}" fill-opacity="0.7" '
        f'stroke="{_SANDBOX_FILL}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{_fmt(x + swatch + 6.0)}" y="{_fmt(base_y)}" '
        f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'dominant-baseline="middle">'
        f"sandbox group (n={comparison.sandbox.n_shops}, "
        f"calls={comparison.sandbox.judge_calls_total})</text>"
    )

    # Real swatch.
    cursor_x = x + 240.0
    parts.append(
        f'<rect x="{_fmt(cursor_x)}" y="{_fmt(base_y - swatch + 2.0)}" '
        f'width="{_fmt(swatch)}" height="{_fmt(swatch)}" '
        f'fill="{_REAL_FILL}" fill-opacity="0.7" '
        f'stroke="{_REAL_FILL}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{_fmt(cursor_x + swatch + 6.0)}" y="{_fmt(base_y)}" '
        f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'dominant-baseline="middle">'
        f"real group (n={comparison.real.n_shops}, "
        f"calls={comparison.real.judge_calls_total})</text>"
    )

    # Chance-rate reference.
    base_y += 18.0
    parts.append(
        f'<line x1="{_fmt(x)}" y1="{_fmt(base_y - 4.0)}" '
        f'x2="{_fmt(x + swatch)}" y2="{_fmt(base_y - 4.0)}" '
        f'stroke="{_REFERENCE_STROKE}" stroke-opacity="0.8" '
        f'stroke-width="1" stroke-dasharray="4 3"/>'
    )
    parts.append(
        f'<text x="{_fmt(x + swatch + 6.0)}" y="{_fmt(base_y)}" '
        f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'dominant-baseline="middle">chance rate (acc=0.500)</text>'
    )

    parts.append("</g>")
    return "\n".join(parts)
