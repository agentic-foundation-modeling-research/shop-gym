"""Axis-C Turing chart (T6.4 — spec §8.4 row 4, §7 M6).

Renders the per-pair pairwise-judge accuracy chart that anchors the
indistinguishability claim. One row per ``(sandbox, source)`` pair plus
a cohort-level intra-real control row, each with:

* the per-pair / control point estimate of judge accuracy in ``[0, 1]``
  (fraction of calls whose ``judge_pick == truth`` after dropping the
  swap-inconsistent and no-evidence calls per spec §5.5 guardrails);
* a horizontal 95% bootstrap confidence interval drawn as an error bar
  with capped endpoints;
* a right-edge annotation reporting ``acc=…`` plus ``Δ=…`` against the
  control accuracy (pair rows only).

Two reference markings make the spec §5.7 claim
``|experimental - control| ≤ ε`` legible at a glance:

* a vertical dashed line at ``acc = 0.5`` (the naive
  "indistinguishable" target);
* a shaded vertical band ``[control - ε, control + ε]`` across every
  row — pairs whose CI overlaps the band are within the noise floor.

SVG output is fully deterministic from the input
:class:`~shop_probe.report.JudgeCall` populations + the ``bootstrap_seed``
— paper figures must be reproducible from the JSON on disk (T6.4
acceptance check). Calling :func:`render_turing_chart_svg` twice with the
same inputs returns byte-for-byte identical strings.

The module is import-safe: it performs no I/O at import time, no
matplotlib / cairo dependency, and emits a self-contained SVG document.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from shop_probe.report import JudgeCall

# --------------------------------------------------------------------------- #
# Public input types.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PairTuringData:
    """One pair's judge-call population for the Turing chart.

    The wrapper is needed because :class:`~shop_probe.report.JudgeCall`
    does not carry a ``pair_id`` — calls are stored under each paired
    :class:`~shop_probe.report.ProbeReport` and the caller knows which
    :class:`~shop_probe.targets.Pair` they belong to.

    Attributes:
        pair_id: Pair identifier shown on the row label
            (e.g. ``"pair_1"``).
        judge_calls: Every judge call recorded for the pair, including
            swap-inconsistent and no-evidence calls. The renderer
            applies the spec §5.5 guardrails internally so the same
            inputs the report stored on disk drive the figure.
    """

    pair_id: str
    judge_calls: tuple[JudgeCall, ...]


# --------------------------------------------------------------------------- #
# Geometry — pinned so figure output is byte-stable across runs.
# --------------------------------------------------------------------------- #

_WIDTH: int = 760
"""Canvas width, in user units (≈ pixels at 1x zoom)."""

_LABEL_X: float = 16.0
"""Left margin for row labels."""

_LABEL_WIDTH: float = 196.0
"""Reserved width for the row-label column."""

_PLOT_LEFT: float = _LABEL_X + _LABEL_WIDTH
"""Left edge of the plot (x = 0.0) area."""

_PLOT_RIGHT_PADDING: float = 188.0
"""Right margin reserved for per-row value + Δ annotations."""

_PLOT_RIGHT: float = float(_WIDTH) - _PLOT_RIGHT_PADDING
"""Right edge of the plot (x = 1.0) area."""

_PLOT_WIDTH: float = _PLOT_RIGHT - _PLOT_LEFT
"""Plot-area width (x ∈ [0, 1] is mapped onto this span)."""

_HEADER_HEIGHT: float = 36.0
"""Vertical space reserved for the chart title."""

_ROW_HEIGHT: float = 30.0
"""Vertical step between successive rows."""

_ROW_TOP_PADDING: float = 8.0
"""Vertical padding before the first row."""

_AXIS_HEIGHT: float = 36.0
"""Vertical space reserved for the bottom x-axis."""

_LEGEND_HEIGHT: float = 56.0
"""Vertical space reserved for the legend strip below the axis."""

_ERROR_CAP_HALF: float = 4.0
"""Half-height of the error-bar end caps."""

_MARKER_RADIUS: float = 4.5
"""Filled-circle radius for point-estimate markers."""

_FLOAT_FMT: str = ".3f"
"""Coordinate precision (three decimals → byte-stable SVG)."""

_VALUE_FMT: str = ".3f"
"""Numeric precision for value annotations."""

# Bootstrap percentile for the 95% CI.
_CI_LOW: float = 0.025
_CI_HIGH: float = 0.975

# Axis ticks at quartiles + endpoints.
_AXIS_TICKS: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)

# --------------------------------------------------------------------------- #
# Style — fixed palette, no theme switching in v1.
# --------------------------------------------------------------------------- #

_LABEL_FILL: str = "#111827"
_LABEL_FONT_SIZE: int = 12
_VALUE_FONT_SIZE: int = 10
_LEGEND_FONT_SIZE: int = 11
_HEADER_FONT_SIZE: int = 13

_AXIS_STROKE: str = "#9ca3af"
_AXIS_STROKE_OPACITY: float = 0.7

_REFERENCE_STROKE: str = "#6b7280"
"""Color of the ``acc = 0.5`` naive-target reference line."""

_CONTROL_STROKE: str = "#0ea5e9"
"""Color of the control reference line + the ε-band edges."""

_CONTROL_FILL: str = "#0ea5e9"
_CONTROL_FILL_OPACITY: float = 0.15
"""Color + opacity of the shaded ``[control - ε, control + ε]`` band."""

_CONTROL_LABEL: str = "intra-real control"
"""Row label for the cohort-level control row (matches tables)."""

_CONTROL_MARKER: str = "#0369a1"
"""Stroke + fill color of the control row's point-estimate marker."""

_PAIR_PALETTE: tuple[str, ...] = (
    "#ef4444",  # red
    "#10b981",  # green
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#06b6d4",  # cyan
)
"""Cycled colors for pair markers (assigned by input order)."""

# --------------------------------------------------------------------------- #
# Internal row representation — one per pair + the control row.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _RowData:
    """Pre-computed plotting inputs for one chart row."""

    label: str
    color: str
    accuracy: float
    ci_low: float
    ci_high: float
    n_kept: int
    n_dropped: int
    is_control: bool


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #


def render_turing_chart_svg(
    *,
    pairs: Sequence[PairTuringData],
    control_calls: Sequence[JudgeCall],
    epsilon: float = 0.1,
    bootstrap_iters: int = 1000,
    bootstrap_seed: int = 0,
) -> str:
    """Render the axis-C Turing chart as a deterministic SVG document.

    For every pair plus the cohort-level intra-real control population we
    drop the swap-inconsistent and no-evidence calls per spec §5.5
    guardrails, compute the point-estimate accuracy on the survivors,
    then bootstrap a 95% CI.

    The chart shades a vertical ``[control - ε, control + ε]`` band so
    the spec §5.7 claim ``|experimental - control| ≤ ε`` is visible
    immediately: pair point-estimates inside the band are within the
    noise floor.

    Args:
        pairs: One :class:`PairTuringData` per ``(sandbox, source)`` pair.
            Must be non-empty; each ``pair_id`` must be unique.
        control_calls: Intra-real control judge calls aggregated across
            the cohort. Must contain at least one swap-consistent
            evidence-cited call after spec §5.5 filtering — the chart's
            ε-band is centered on the control accuracy and undefined
            without it.
        epsilon: Half-width of the indistinguishability band, in
            ``(0, 1)``. v1 uses the spec §5.7 default of ``0.1``.
        bootstrap_iters: Number of bootstrap resamples per row. Must be
            ``≥ 1``. Defaults to ``1000`` per spec §8.4 row 4.
        bootstrap_seed: PRNG seed for the bootstrap resampler. The same
            ``(inputs, seed)`` always renders byte-identical SVG.

    Returns:
        A self-contained SVG string ending with a trailing newline.

    Raises:
        ValueError: ``pairs`` is empty, ``epsilon`` is out of range,
            ``bootstrap_iters < 1``, any pair has no surviving calls
            after the §5.5 guardrail filter, or two pairs share a
            ``pair_id``.
    """
    if not pairs:
        msg = (
            "render_turing_chart_svg: pairs must be non-empty "
            "(the Turing chart needs at least one experimental pair)"
        )
        raise ValueError(msg)
    if not 0.0 < epsilon < 1.0:
        msg = f"render_turing_chart_svg: epsilon must be in (0, 1) (got {epsilon!r})"
        raise ValueError(msg)
    if bootstrap_iters < 1:
        msg = f"render_turing_chart_svg: bootstrap_iters must be ≥ 1 (got {bootstrap_iters!r})"
        raise ValueError(msg)

    seen_ids: set[str] = set()
    for pair in pairs:
        if pair.pair_id in seen_ids:
            msg = f"render_turing_chart_svg: duplicate pair_id {pair.pair_id!r} in pairs"
            raise ValueError(msg)
        seen_ids.add(pair.pair_id)

    rng = random.Random(bootstrap_seed)
    pair_rows = tuple(_row_from_pair(pair, i, rng, bootstrap_iters) for i, pair in enumerate(pairs))
    control_row = _row_from_control(control_calls, rng, bootstrap_iters)

    rows = (*pair_rows, control_row)
    height = int(
        _HEADER_HEIGHT + _ROW_TOP_PADDING + _ROW_HEIGHT * len(rows) + _AXIS_HEIGHT + _LEGEND_HEIGHT
    )

    layers: list[str] = [
        _svg_open(height),
        _header(),
        _epsilon_band(rows, control_row, epsilon),
        _reference_line(0.5, _REFERENCE_STROKE, dashed=True, n_rows=len(rows)),
        _reference_line(control_row.accuracy, _CONTROL_STROKE, dashed=False, n_rows=len(rows)),
        *(_render_row(i, row, control_row.accuracy, epsilon) for i, row in enumerate(rows)),
        _x_axis(len(rows)),
        _legend(height, epsilon),
        "</svg>",
    ]
    return "\n".join(layers) + "\n"


# --------------------------------------------------------------------------- #
# Pure helpers — accuracy + bootstrap math.
# --------------------------------------------------------------------------- #


def _filter_calls(calls: Sequence[JudgeCall]) -> tuple[list[bool], int]:
    """Apply spec §5.5 guardrails and return ``(correct_flags, n_dropped)``.

    Drops swap-inconsistent calls (spec §5.5 step 6) and calls without
    evidence citation (spec §5.5 guardrails). Of the survivors,
    ``judge_pick == truth`` is the per-call correctness flag.
    """
    correct: list[bool] = []
    n_dropped = 0
    for call in calls:
        if not call.swap_consistent or not call.evidence_cited:
            n_dropped += 1
            continue
        correct.append(call.judge_pick == call.truth)
    return correct, n_dropped


def _bootstrap_ci(
    correct: Sequence[bool],
    rng: random.Random,
    iters: int,
) -> tuple[float, float]:
    """Bootstrap-resampled 95% CI for the fraction of ``True`` flags.

    Standard percentile bootstrap: resample ``len(correct)`` flags with
    replacement ``iters`` times, compute the fraction true on each
    resample, and return ``(2.5%-tile, 97.5%-tile)`` via linear
    interpolation between sorted samples.
    """
    n = len(correct)
    if n == 0:
        msg = "_bootstrap_ci: cannot bootstrap an empty sample"
        raise ValueError(msg)
    samples: list[float] = []
    for _ in range(iters):
        hits = sum(1 for _ in range(n) if correct[rng.randrange(n)])
        samples.append(hits / n)
    samples.sort()
    return _percentile(samples, _CI_LOW), _percentile(samples, _CI_HIGH)


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated ``q``-percentile of a pre-sorted sequence."""
    if not sorted_values:
        msg = "_percentile: empty sequence"
        raise ValueError(msg)
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_values):
        return sorted_values[-1]
    return sorted_values[lo] + frac * (sorted_values[lo + 1] - sorted_values[lo])


def _row_from_pair(
    pair: PairTuringData,
    index: int,
    rng: random.Random,
    bootstrap_iters: int,
) -> _RowData:
    correct, n_dropped = _filter_calls(pair.judge_calls)
    if not correct:
        msg = (
            f"render_turing_chart_svg: pair {pair.pair_id!r} has no "
            "surviving judge calls after dropping swap-inconsistent + "
            "no-evidence (spec §5.5 guardrails); accuracy is undefined"
        )
        raise ValueError(msg)
    accuracy = sum(1 for c in correct if c) / len(correct)
    ci_low, ci_high = _bootstrap_ci(correct, rng, bootstrap_iters)
    color = _PAIR_PALETTE[index % len(_PAIR_PALETTE)]
    return _RowData(
        label=pair.pair_id,
        color=color,
        accuracy=accuracy,
        ci_low=ci_low,
        ci_high=ci_high,
        n_kept=len(correct),
        n_dropped=n_dropped,
        is_control=False,
    )


def _row_from_control(
    calls: Sequence[JudgeCall],
    rng: random.Random,
    bootstrap_iters: int,
) -> _RowData:
    correct, n_dropped = _filter_calls(calls)
    if not correct:
        msg = (
            "render_turing_chart_svg: control_calls has no surviving "
            "judge calls after dropping swap-inconsistent + no-evidence "
            "(spec §5.5 guardrails); the ε-band is undefined without "
            "a control accuracy"
        )
        raise ValueError(msg)
    accuracy = sum(1 for c in correct if c) / len(correct)
    ci_low, ci_high = _bootstrap_ci(correct, rng, bootstrap_iters)
    return _RowData(
        label=_CONTROL_LABEL,
        color=_CONTROL_MARKER,
        accuracy=accuracy,
        ci_low=ci_low,
        ci_high=ci_high,
        n_kept=len(correct),
        n_dropped=n_dropped,
        is_control=True,
    )


# --------------------------------------------------------------------------- #
# SVG geometry helpers.
# --------------------------------------------------------------------------- #


def _value_to_x(value: float) -> float:
    """Map ``acc ∈ [0, 1]`` to an absolute SVG x coordinate."""
    return _PLOT_LEFT + max(0.0, min(1.0, value)) * _PLOT_WIDTH


def _row_top(index: int) -> float:
    return _HEADER_HEIGHT + _ROW_TOP_PADDING + index * _ROW_HEIGHT


def _row_center(index: int) -> float:
    return _row_top(index) + _ROW_HEIGHT / 2.0


def _rows_top() -> float:
    """Top y of the first row band (= top of the reference-line strip)."""
    return _HEADER_HEIGHT + _ROW_TOP_PADDING


def _rows_bottom(n_rows: int) -> float:
    """Bottom y of the last row band (= bottom of the reference-line strip)."""
    return _rows_top() + n_rows * _ROW_HEIGHT


def _fmt(value: float) -> str:
    """Format a coordinate component with the pinned precision."""
    formatted = f"{value:{_FLOAT_FMT}}"
    if formatted == f"-{0.0:{_FLOAT_FMT}}":
        return f"{0.0:{_FLOAT_FMT}}"
    return formatted


def _fmt_value(value: float) -> str:
    """Format a metric value for the right-edge annotation."""
    return f"{value:{_VALUE_FMT}}"


def _fmt_signed(value: float) -> str:
    """Format ``Δ = pair - control`` with an explicit sign."""
    return f"{value:+{_VALUE_FMT}}"


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
        f'role="img" aria-label="Pairwise-judge Turing chart">'
    )


def _header() -> str:
    return (
        f'<g class="header">'
        f'<text x="{_fmt(_LABEL_X)}" y="{_fmt(_HEADER_HEIGHT - 14.0)}" '
        f'font-size="{_HEADER_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'font-weight="bold">'
        f"Pairwise-judge accuracy — experimental pairs vs. intra-real control"
        f"</text>"
        f"</g>"
    )


def _epsilon_band(
    rows: Sequence[_RowData],
    control_row: _RowData,
    epsilon: float,
) -> str:
    """Shaded vertical ``[control - ε, control + ε]`` band across all rows."""
    x_lo = _value_to_x(control_row.accuracy - epsilon)
    x_hi = _value_to_x(control_row.accuracy + epsilon)
    width = x_hi - x_lo
    y = _rows_top()
    height = _rows_bottom(len(rows)) - y
    return (
        f'<g class="epsilon-band" data-epsilon="{_fmt_value(epsilon)}">'
        f'<rect x="{_fmt(x_lo)}" y="{_fmt(y)}" '
        f'width="{_fmt(width)}" height="{_fmt(height)}" '
        f'fill="{_CONTROL_FILL}" fill-opacity="{_CONTROL_FILL_OPACITY}" '
        f'stroke="none"/>'
        f"</g>"
    )


def _reference_line(
    value: float,
    stroke: str,
    *,
    dashed: bool,
    n_rows: int,
) -> str:
    """Vertical reference line at ``value`` spanning the rows band."""
    x = _value_to_x(value)
    y1 = _rows_top()
    y2 = _rows_bottom(n_rows)
    dash_attr = ' stroke-dasharray="4 3"' if dashed else ""
    css_class = "reference-naive" if dashed else "reference-control"
    return (
        f'<g class="{css_class}" data-value="{_fmt_value(value)}">'
        f'<line x1="{_fmt(x)}" y1="{_fmt(y1)}" '
        f'x2="{_fmt(x)}" y2="{_fmt(y2)}" '
        f'stroke="{stroke}" stroke-opacity="0.8" stroke-width="1"{dash_attr}/>'
        f"</g>"
    )


def _render_row(
    index: int,
    row: _RowData,
    control_accuracy: float,
    epsilon: float,
) -> str:
    parts: list[str] = [
        f'<g class="row" data-label="{_xml_escape(row.label)}" '
        f'data-control="{str(row.is_control).lower()}">'
    ]
    parts.append(_row_label(index, row))
    parts.append(_row_error_bar(index, row))
    parts.append(_row_marker(index, row))
    parts.append(_row_value_annotation(index, row, control_accuracy, epsilon))
    parts.append("</g>")
    return "\n".join(parts)


def _row_label(index: int, row: _RowData) -> str:
    y = _row_center(index) + 4.0  # nudge for visual centering.
    return (
        f'<text x="{_fmt(_LABEL_X)}" y="{_fmt(y)}" '
        f'font-size="{_LABEL_FONT_SIZE}" fill="{_LABEL_FILL}">'
        f"{_xml_escape(row.label)}</text>"
    )


def _row_error_bar(index: int, row: _RowData) -> str:
    """Capped horizontal line between ``ci_low`` and ``ci_high``."""
    cy = _row_center(index)
    x_lo = _value_to_x(row.ci_low)
    x_hi = _value_to_x(row.ci_high)
    cap_top = cy - _ERROR_CAP_HALF
    cap_bot = cy + _ERROR_CAP_HALF
    return (
        f'<g class="error-bar" stroke="{row.color}" '
        f'stroke-opacity="0.85" stroke-width="1.5" fill="none">'
        f'<line x1="{_fmt(x_lo)}" y1="{_fmt(cy)}" '
        f'x2="{_fmt(x_hi)}" y2="{_fmt(cy)}"/>'
        f'<line x1="{_fmt(x_lo)}" y1="{_fmt(cap_top)}" '
        f'x2="{_fmt(x_lo)}" y2="{_fmt(cap_bot)}"/>'
        f'<line x1="{_fmt(x_hi)}" y1="{_fmt(cap_top)}" '
        f'x2="{_fmt(x_hi)}" y2="{_fmt(cap_bot)}"/>'
        f"</g>"
    )


def _row_marker(index: int, row: _RowData) -> str:
    """Filled-circle point estimate marker."""
    cx = _value_to_x(row.accuracy)
    cy = _row_center(index)
    return (
        f'<circle class="marker" cx="{_fmt(cx)}" cy="{_fmt(cy)}" '
        f'r="{_fmt(_MARKER_RADIUS)}" '
        f'fill="{row.color}" stroke="{row.color}" stroke-width="1"/>'
    )


def _row_value_annotation(
    index: int,
    row: _RowData,
    control_accuracy: float,
    epsilon: float,
) -> str:
    """Right-aligned ``acc=… [lo, hi]`` plus ``Δ=…`` annotation."""
    x = _PLOT_RIGHT + 6.0
    y = _row_center(index) + 4.0
    text = f"acc={_fmt_value(row.accuracy)} [{_fmt_value(row.ci_low)}, {_fmt_value(row.ci_high)}]"
    if not row.is_control:
        delta = row.accuracy - control_accuracy
        within = abs(delta) <= epsilon
        marker = "✓" if within else "✗"
        text = f"{text}  Δ={_fmt_signed(delta)} {marker}"
    return (
        f'<text x="{_fmt(x)}" y="{_fmt(y)}" '
        f'font-size="{_VALUE_FONT_SIZE}" fill="{_LABEL_FILL}">'
        f"{_xml_escape(text)}</text>"
    )


def _x_axis(n_rows: int) -> str:
    """Bottom x-axis with a baseline + tick marks at the canonical quartiles."""
    y = _rows_bottom(n_rows) + 6.0
    parts: list[str] = ['<g class="x-axis">']
    parts.append(
        f'<line x1="{_fmt(_PLOT_LEFT)}" y1="{_fmt(y)}" '
        f'x2="{_fmt(_PLOT_RIGHT)}" y2="{_fmt(y)}" '
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


def _legend(height: int, epsilon: float) -> str:
    """Legend strip describing the band, reference lines, and markers."""
    base_y = float(height) - _LEGEND_HEIGHT + 18.0
    x = _LABEL_X
    swatch = 12.0
    parts: list[str] = ['<g class="legend">']

    # ε-band swatch.
    parts.append(
        f'<rect x="{_fmt(x)}" y="{_fmt(base_y - swatch + 2.0)}" '
        f'width="{_fmt(swatch)}" height="{_fmt(swatch)}" '
        f'fill="{_CONTROL_FILL}" fill-opacity="{_CONTROL_FILL_OPACITY}" '
        f'stroke="{_CONTROL_STROKE}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{_fmt(x + swatch + 6.0)}" y="{_fmt(base_y)}" '
        f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'dominant-baseline="middle">'
        f"ε-band (control ± {_fmt_value(epsilon)})</text>"
    )

    # Naive 0.5 reference.
    cursor_x = x + 220.0
    parts.append(
        f'<line x1="{_fmt(cursor_x)}" y1="{_fmt(base_y - 4.0)}" '
        f'x2="{_fmt(cursor_x + swatch)}" y2="{_fmt(base_y - 4.0)}" '
        f'stroke="{_REFERENCE_STROKE}" stroke-opacity="0.8" '
        f'stroke-width="1" stroke-dasharray="4 3"/>'
    )
    parts.append(
        f'<text x="{_fmt(cursor_x + swatch + 6.0)}" y="{_fmt(base_y)}" '
        f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'dominant-baseline="middle">naive target (acc=0.500)</text>'
    )

    # Pair marker.
    cursor_x = x + 420.0
    parts.append(
        f'<circle cx="{_fmt(cursor_x + 6.0)}" cy="{_fmt(base_y - 4.0)}" '
        f'r="{_fmt(_MARKER_RADIUS)}" '
        f'fill="{_PAIR_PALETTE[0]}" stroke="{_PAIR_PALETTE[0]}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{_fmt(cursor_x + swatch + 6.0)}" y="{_fmt(base_y)}" '
        f'font-size="{_LEGEND_FONT_SIZE}" fill="{_LABEL_FILL}" '
        f'dominant-baseline="middle">pair ± 95% bootstrap CI</text>'
    )

    parts.append("</g>")
    return "\n".join(parts)
