"""Aggregation + paper-figure rendering from versioned ProbeReports."""

from shop_probe.report_writer.figures import render_radar_chart_svg
from shop_probe.report_writer.supplement import render_prior_work_supplement_table
from shop_probe.report_writer.surface_chart import render_surface_bar_chart_svg
from shop_probe.report_writer.tables import (
    CONTROL_ROW_LABEL,
    render_pair_fidelity_table,
)
from shop_probe.report_writer.turing_chart import (
    PairTuringData,
    render_turing_chart_svg,
)

__all__ = [
    "CONTROL_ROW_LABEL",
    "PairTuringData",
    "render_pair_fidelity_table",
    "render_prior_work_supplement_table",
    "render_radar_chart_svg",
    "render_surface_bar_chart_svg",
    "render_turing_chart_svg",
]
