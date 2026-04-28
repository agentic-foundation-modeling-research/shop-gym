"""Aggregation + paper-figure rendering from versioned ProbeReports."""

from shop_probe.report_writer.figures import render_radar_chart_svg
from shop_probe.report_writer.surface_chart import render_surface_bar_chart_svg
from shop_probe.report_writer.tables import (
    CONTROL_ROW_LABEL,
    render_pair_fidelity_table,
)

__all__ = [
    "CONTROL_ROW_LABEL",
    "render_pair_fidelity_table",
    "render_radar_chart_svg",
    "render_surface_bar_chart_svg",
]
