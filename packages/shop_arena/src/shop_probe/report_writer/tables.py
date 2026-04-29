"""Group-comparison and per-shop tables (``web_probe_patch.md``).

Two pure functions over validated schemas:

* :func:`render_group_comparison_table` — three-row Markdown table
  (sandbox group / real group / delta) emitted by ``shop-probe report``
  as the headline group-vs-group fidelity number.
* :func:`render_per_shop_table` — one row per shop with the columns
  reserved for stage-3 inspection (``label``, ``name``,
  ``coverage_weighted``, plus per-axis breakdown and judge accuracy).

Implemented as pure functions over already-validated objects so the
output is deterministic from versioned reports — no manual editing on
the path from JSON to figure.

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from collections.abc import Sequence

from shop_probe.fidelity import BenchComparison, GroupSummary
from shop_probe.report import ProbeReport

_MISSING: str = "—"
"""Em-dash used for unfilled cells (e.g. judge cells before axis-C runs)."""

_FIDELITY_DECIMALS: int = 3
"""Numeric precision for fidelity values."""


def render_group_comparison_table(comparison: BenchComparison) -> str:
    """Render the headline group comparison table as GitHub-flavored Markdown.

    Three rows: the sandbox group rollup, the real group rollup, and a
    ``delta = real - sandbox`` row. Columns:

    * ``Group`` — group label or ``delta``.
    * ``n_shops`` — group size.
    * ``Coverage weighted`` — group-mean coverage_weighted.
    * ``Surface metric ratio`` — geometric mean? No — single column not
      meaningful per-metric, so we report a count of metrics where the
      sandbox falls inside the real envelope (delta row only).
    * ``Judge accuracy`` — group-level judge accuracy (or em-dash).

    The exact columns are kept narrow on purpose: the rich per-metric
    breakdown lives on :class:`BenchComparison` itself for figure code
    that needs it, and on :func:`render_per_shop_table` for stage-3
    inspection.

    Args:
        comparison: A validated :class:`BenchComparison`.

    Returns:
        A Markdown string ending with a trailing newline.
    """
    header = "| Group | n_shops | Coverage weighted | Judge accuracy |"
    separator = "|---|---:|---:|---:|"
    rows = [
        header,
        separator,
        _render_group_row(comparison.sandbox),
        _render_group_row(comparison.real),
        _render_delta_row(comparison),
    ]
    return "\n".join(rows) + "\n"


def render_per_shop_table(
    sandbox_reports: Sequence[ProbeReport],
    real_reports: Sequence[ProbeReport],
    comparison: BenchComparison,
) -> str:
    """Render a per-shop inspection table as GitHub-flavored Markdown.

    One row per shop in stable order (sandboxes first, then reals; both
    in input order). Columns: label, name, coverage_weighted,
    coverage_core, coverage_modern, in_real_envelope (count of metrics
    inside the real envelope, or em-dash for real shops), judge_accuracy
    (per-shop fraction).

    Args:
        sandbox_reports: Sandbox-group reports.
        real_reports: Real-group reports.
        comparison: The parent :class:`BenchComparison`. Used only to
            look up :attr:`BenchComparison.sandbox_in_real_envelope`.

    Returns:
        A Markdown string ending with a trailing newline.
    """
    header = (
        "| Label | Name | Coverage weighted | Coverage core | "
        "Coverage modern | In real envelope | Judge accuracy |"
    )
    separator = "|---|---|---:|---:|---:|---:|---:|"
    rows = [header, separator]
    for report in sandbox_reports:
        envelope_metrics = comparison.sandbox_in_real_envelope.get(report.target.name, {})
        rows.append(_render_shop_row(report, envelope_metrics, is_sandbox=True))
    for report in real_reports:
        rows.append(_render_shop_row(report, {}, is_sandbox=False))
    return "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- #
# Internals.
# --------------------------------------------------------------------------- #


def _render_group_row(group: GroupSummary) -> str:
    return (
        f"| {group.label} "
        f"| {group.n_shops} "
        f"| {_fmt_unsigned(group.coverage_weighted_mean)} "
        f"| {_fmt_optional(group.judge_accuracy)} |"
    )


def _render_delta_row(comparison: BenchComparison) -> str:
    delta_n = comparison.real.n_shops - comparison.sandbox.n_shops
    delta_judge: str
    if comparison.judge_indistinguishability is None:
        delta_judge = _MISSING
    else:
        delta_judge = _fmt_unsigned(comparison.judge_indistinguishability)
    return (
        f"| delta (real - sandbox) "
        f"| {delta_n:+d} "
        f"| {_fmt_signed(comparison.coverage_gap_weighted)} "
        f"| {delta_judge} |"
    )


def _render_shop_row(
    report: ProbeReport,
    envelope_metrics: dict[str, bool],
    *,
    is_sandbox: bool,
) -> str:
    if is_sandbox:
        if envelope_metrics:
            inside = sum(1 for v in envelope_metrics.values() if v)
            envelope_cell = f"{inside}/{len(envelope_metrics)}"
        else:
            envelope_cell = _MISSING
    else:
        envelope_cell = _MISSING
    judge_accuracy = _per_shop_judge_accuracy(report)
    return (
        f"| {report.target.label} "
        f"| {report.target.name} "
        f"| {_fmt_unsigned(report.coverage_weighted)} "
        f"| {_fmt_unsigned(report.coverage_core)} "
        f"| {_fmt_unsigned(report.coverage_modern)} "
        f"| {envelope_cell} "
        f"| {_fmt_optional(judge_accuracy)} |"
    )


def _per_shop_judge_accuracy(report: ProbeReport) -> float | None:
    """Per-shop judge accuracy (fraction predicting target.label correctly)."""
    if not report.judge_calls:
        return None
    correct = sum(1 for c in report.judge_calls if c.predicted_label == report.target.label)
    return correct / len(report.judge_calls)


def _fmt_signed(value: float) -> str:
    return f"{value:+.{_FIDELITY_DECIMALS}f}"


def _fmt_unsigned(value: float) -> str:
    return f"{value:.{_FIDELITY_DECIMALS}f}"


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return _MISSING
    return f"{value:.{_FIDELITY_DECIMALS}f}"
