"""Closed pydantic v2 schemas for EnvEval's published per-run documents.

Two JSON documents leave the pipeline per run:

* ``metrics.json`` — the published measurement digest (closed schema).
  Downstream tools (e.g. notebooks) consume it directly.
* ``manifest.json`` — the run-level operations record (config snapshot,
  step ran/reused accounting, prompt/rule/heuristic versions, navigation
  and LLM-call counters).

Both schemas live here to keep their pydantic models and helpers
co-located. Callers should import from
``shop_arena.env_eval.schema.metrics`` / ``…manifest``.
"""

from __future__ import annotations
