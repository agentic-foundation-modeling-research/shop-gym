"""Per-pair fidelity table renderer (T6.1 — spec §8.4 row 1, §7 M6).

Renders the headline three-axis fidelity table that anchors the paper:
one row per :class:`~shop_probe.fidelity.PairFidelity` plus a
cohort-level intra-real control row. Each row carries exactly three
numbers per spec §5.7 + §8.4 row 1:

* :attr:`~shop_probe.fidelity.PairFidelity.coverage_gap_weighted` (axis A)
* :attr:`~shop_probe.fidelity.PairFidelity.surface_ratio_geomean` (axis B)
* :attr:`~shop_probe.fidelity.PairFidelity.judge_accuracy_experimental`
  (axis C)

Implemented as a pure function over a validated
:class:`~shop_probe.fidelity.CohortFidelity` so the whole table is
deterministic from versioned reports — no manual editing on the path
from JSON to figure (T6.1 acceptance check).

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from shop_probe.fidelity import CohortFidelity, PairFidelity

CONTROL_ROW_LABEL: str = "intra-real control"
"""Label used for the cohort-level control row (spec §5.7 + §8.4 row 1)."""

_MISSING: str = "—"
"""Em-dash used for unfilled judge cells (axis C lands in M4; spec §7 M4)."""

_FIDELITY_DECIMALS: int = 3
"""Numeric precision for fidelity values, matching ``cli.py`` print fmt."""


def render_pair_fidelity_table(cohort: CohortFidelity) -> str:
    """Render the per-pair fidelity table as GitHub-flavored Markdown.

    Produces one row per :class:`~shop_probe.fidelity.PairFidelity` in
    ``cohort.pairs`` (preserving order), followed by a single
    cohort-level intra-real control row carrying
    :attr:`~shop_probe.fidelity.CohortFidelity.judge_accuracy_control`.
    The control row's axis-A and axis-B cells are intentionally empty
    per spec §8.4 row 1 (the control compares two real shops, so a
    coverage gap or surface ratio against itself is not meaningful).

    Args:
        cohort: Validated cohort-level fidelity rollup. ``cohort.pairs``
            may be empty during M3 pilot work — the resulting table
            still contains the header row and the control row.

    Returns:
        A Markdown string ending with a trailing newline.
    """
    header = (
        "| Pair | Coverage gap (A) | Surface ratio geomean (B) | Judge accuracy experimental (C) |"
    )
    separator = "|---|---:|---:|---:|"
    rows: list[str] = [header, separator]
    rows.extend(_render_pair_row(pair) for pair in cohort.pairs)
    rows.append(_render_control_row(cohort.judge_accuracy_control))
    return "\n".join(rows) + "\n"


def _render_pair_row(pair: PairFidelity) -> str:
    return (
        f"| {pair.pair_id} "
        f"| {_fmt_signed(pair.coverage_gap_weighted)} "
        f"| {_fmt_unsigned(pair.surface_ratio_geomean)} "
        f"| {_fmt_optional(pair.judge_accuracy_experimental)} |"
    )


def _render_control_row(judge_accuracy_control: float | None) -> str:
    return (
        f"| {CONTROL_ROW_LABEL} "
        f"| {_MISSING} "
        f"| {_MISSING} "
        f"| {_fmt_optional(judge_accuracy_control)} |"
    )


def _fmt_signed(value: float) -> str:
    """Format a signed fidelity number (e.g. ``coverage_gap_weighted``).

    Always carries an explicit sign so reviewers can tell at a glance
    which side the gap leans toward (spec §5.7: positive means the
    source is ahead of the sandbox).
    """
    return f"{value:+.{_FIDELITY_DECIMALS}f}"


def _fmt_unsigned(value: float) -> str:
    """Format an unsigned fidelity number (e.g. ``surface_ratio_geomean``)."""
    return f"{value:.{_FIDELITY_DECIMALS}f}"


def _fmt_optional(value: float | None) -> str:
    """Format an optional ``[0, 1]`` fidelity number (e.g. judge accuracy).

    Empty cells render as :data:`_MISSING` so the M3 pilot table — and
    any axis-C-not-yet-run row — stays readable without lying about
    a missing measurement.
    """
    if value is None:
        return _MISSING
    return f"{value:.{_FIDELITY_DECIMALS}f}"
