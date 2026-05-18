"""Post-measurement visualizers for EnvEval run artifacts.

Submodules render on-disk artifacts produced by ``evaluate`` into
human-friendly views. Each renderer is pure: it reads its inputs from
the run directory, performs no live browser or LLM work, and writes a
self-contained output (typically HTML) that can be opened without
installing extra tooling.

Current renderers:

* :func:`render_graph_html` — interactive view of
  ``<run_dir>/transition/graph.json`` (BFS + stateful nodes/edges).
"""

from __future__ import annotations

from shop_arena.env_eval.visualize.transition_graph import render_graph_html

__all__ = ["render_graph_html"]
