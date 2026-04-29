"""Aggregation + paper-figure rendering from versioned ProbeReports."""

from shop_probe.report_writer.figures import render_radar_chart_svg
from shop_probe.report_writer.supplement import render_prior_work_supplement_table
from shop_probe.report_writer.surface_chart import render_surface_bar_chart_svg
from shop_probe.report_writer.tables import (
    render_group_comparison_table,
    render_per_shop_table,
)
from shop_probe.report_writer.turing_chart import render_turing_chart_svg

__all__ = [
    "render_group_comparison_table",
    "render_per_shop_table",
    "render_prior_work_supplement_table",
    "render_radar_chart_svg",
    "render_surface_bar_chart_svg",
    "render_turing_chart_svg",
]
