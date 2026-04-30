"""Markdown table rendering from validated ProbeReports."""

from shop_probe.report_writer.tables import (
    render_group_comparison_table,
    render_per_shop_table,
)

__all__ = [
    "render_group_comparison_table",
    "render_per_shop_table",
]
