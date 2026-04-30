"""Group-comparison and per-shop tables.

Two pure functions over validated schemas:

* :func:`render_group_comparison_table` — three-row Markdown table
  (sandbox group / real group / delta) summarising group-vs-group
  fidelity.
* :func:`render_per_shop_table` — one row per shop with per-axis
  coverage breakdown.

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from collections.abc import Sequence

from shop_probe.fidelity import BenchComparison, GroupSummary
from shop_probe.report import ProbeReport

_MISSING: str = "—"
"""Em-dash for cells that don't apply (e.g. envelope row on real shops)."""

_FIDELITY_DECIMALS: int = 3


def render_group_comparison_table(comparison: BenchComparison) -> str:
    """Render the headline group comparison table as GitHub-flavored Markdown.

    Three rows: sandbox-group rollup, real-group rollup, and a
    ``delta = real - sandbox`` row.

    Args:
        comparison: A validated :class:`BenchComparison`.

    Returns:
        A Markdown string ending with a trailing newline.
    """
    header = "| Group | n_shops | Coverage weighted |"
    separator = "|---|---:|---:|"
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
    coverage_core, coverage_modern, in_real_envelope.

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
        "Coverage modern | In real envelope (scale) |"
    )
    separator = "|---|---|---:|---:|---:|---:|"
    rows = [header, separator]
    for report in sandbox_reports:
        envelope_metrics = comparison.sandbox_in_real_envelope.get(report.target.name, {})
        rows.append(_render_shop_row(report, envelope_metrics, is_sandbox=True))
    for report in real_reports:
        rows.append(_render_shop_row(report, {}, is_sandbox=False))
    return "\n".join(rows) + "\n"


def _render_group_row(group: GroupSummary) -> str:
    return (
        f"| {group.label} "
        f"| {group.n_shops} "
        f"| {_fmt_unsigned(group.coverage_weighted_mean)} |"
    )


def _render_delta_row(comparison: BenchComparison) -> str:
    delta_n = comparison.real.n_shops - comparison.sandbox.n_shops
    return (
        f"| delta (real - sandbox) "
        f"| {delta_n:+d} "
        f"| {_fmt_signed(comparison.coverage_gap_weighted)} |"
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
    return (
        f"| {report.target.label} "
        f"| {report.target.name} "
        f"| {_fmt_unsigned(report.coverage_weighted)} "
        f"| {_fmt_unsigned(report.coverage_core)} "
        f"| {_fmt_unsigned(report.coverage_modern)} "
        f"| {envelope_cell} |"
    )


def _fmt_signed(value: float) -> str:
    return f"{value:+.{_FIDELITY_DECIMALS}f}"


def _fmt_unsigned(value: float) -> str:
    return f"{value:.{_FIDELITY_DECIMALS}f}"
