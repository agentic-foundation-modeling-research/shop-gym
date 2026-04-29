"""Prior-work environment supplement table (T7.5 — spec §5.2 + §5.9).

Renders a paper-supplement table that places ``ProbeReport`` rows for
prior-work environments (Mock Shop, WebShop, WebArena-Shopping) next to
each other for context, *without* feeding them into the per-pair
fidelity rollup. Spec §5.2 + §5.9 explicitly keep these environments
out of the v1 cohort: the headline per-pair claim must not change when
this table is enabled.

This module is a pure function over a tuple of validated
:class:`~shop_probe.report.ProbeReport` rows so the table is fully
deterministic from versioned reports — no manual editing on the path
from JSON to Markdown (T7.5 acceptance check).

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from shop_probe.report import ProbeReport

_MISSING: str = "—"
"""Em-dash used for unmeasured cells. Matches ``tables.py`` convention.

A baseline report run with axis A only (``surface is None``) leaves every
axis-B cell as :data:`_MISSING` so the table still validates."""

_COVERAGE_DECIMALS: int = 3
"""Numeric precision for axis-A coverage cells, matching ``tables.py``."""

_INTERACTABLES_DECIMALS: int = 1
"""Numeric precision for the only float-valued axis-B cell rendered here."""

_HEADER: tuple[str, ...] = (
    "Environment",
    "Coverage core (A)",
    "Coverage modern (A)",
    "Coverage weighted (A)",
    "Distinct templates (B)",
    "Routes crawled (B)",
    "Interactables p95 (B)",
    "Forms total (B)",
)
"""Column labels. Eight columns: label + 3 axis-A numerics + 4 axis-B numerics.

Axis-B columns picked from :class:`~shop_probe.surface.metrics.SurfaceMetrics`
to give reviewers a one-glance sense of the environment's structural
richness (spec §5.4): one count of distinct templates, total routes,
the p95 interactable density, and total form count. The full
:class:`SurfaceMetrics` payload remains available in the on-disk JSON
for any reviewer who wants the rest."""


def render_prior_work_supplement_table(reports: tuple[ProbeReport, ...]) -> str:
    """Render the prior-work supplement table as GitHub-flavored Markdown.

    Spec §5.9 mandates this table sits *alongside* primary results without
    altering per-pair claims. Concretely: the function is pure (no
    cohort/fidelity inputs), takes only baseline ``ProbeReport`` rows,
    and emits a self-contained Markdown table.

    Rows are sorted by :attr:`~shop_probe.targets.Target.label` so the
    rendered table is byte-stable across runs regardless of input order
    (acceptance check: rendered from versioned reports without manual
    editing).

    Args:
        reports: Baseline :class:`ProbeReport` rows for the prior-work
            environments. May be empty — the function still emits a
            valid header + separator pair so the supplement file is
            never silently absent.

    Returns:
        A Markdown string ending with a trailing newline.
    """
    header = "| " + " | ".join(_HEADER) + " |"
    # First column is unaligned (label); axis-A numerics + axis-B numerics
    # are right-aligned. Total separator cells = len(_HEADER).
    separator = "|---|" + "|".join("---:" for _ in _HEADER[1:]) + "|"
    rows: list[str] = [header, separator]
    rows.extend(_render_row(report) for report in sorted(reports, key=_sort_key))
    return "\n".join(rows) + "\n"


def _sort_key(report: ProbeReport) -> str:
    """Sort baseline rows by target name for byte-stable output."""
    return report.target.name


def _render_row(report: ProbeReport) -> str:
    surface = report.surface
    cells: list[str] = [
        report.target.name,
        _fmt_coverage(report.coverage_core),
        _fmt_coverage(report.coverage_modern),
        _fmt_coverage(report.coverage_weighted),
    ]
    if surface is None:
        cells.extend([_MISSING] * 4)
    else:
        cells.extend(
            [
                str(surface.distinct_templates),
                str(surface.routes_crawled),
                f"{surface.interactables_per_template_p95:.{_INTERACTABLES_DECIMALS}f}",
                str(surface.forms_total),
            ]
        )
    return "| " + " | ".join(cells) + " |"


def _fmt_coverage(value: float) -> str:
    """Format an axis-A coverage value (``[0, 1]``) at fixed precision."""
    return f"{value:.{_COVERAGE_DECIMALS}f}"
