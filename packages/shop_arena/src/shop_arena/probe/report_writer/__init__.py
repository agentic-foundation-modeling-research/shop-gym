"""Markdown rollup writers for the cohort comparison.

Each writer turns one slice of :class:`shop_arena.probe.fidelity.BenchComparison`
into the corresponding ``*_fidelity.md`` figure listed in spec §5.5.
The writers are pure functions (string ↔ string); the CLI is what writes
to disk.
"""

from __future__ import annotations

from shop_arena.probe.report_writer.tables import (
    render_action_fidelity,
    render_observation_fidelity,
    render_summary,
    render_transition_fidelity,
    write_figures,
)

__all__ = [
    "render_action_fidelity",
    "render_observation_fidelity",
    "render_summary",
    "render_transition_fidelity",
    "write_figures",
]
