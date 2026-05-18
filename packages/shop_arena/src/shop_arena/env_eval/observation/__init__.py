"""Observation layer: axtree statistics + LLM screenshot rubric.

Submodules land across M1 (``axtree_stats``, ``axtree_text``) and M2
(``rubric``, ``prompt.md``).
"""

from __future__ import annotations

from shop_arena.env_eval.observation.axtree_stats import compute_axtree_stats
from shop_arena.env_eval.observation.axtree_text import render_axtree_text
from shop_arena.env_eval.observation.rubric import (
    RUBRIC_PROMPT_VERSION,
    RUBRIC_RESPONSE_SCHEMA,
    RubricArtifact,
    load_rubric_prompt,
    run_rubric,
    write_rubric_artifact,
)

__all__ = [
    "RUBRIC_PROMPT_VERSION",
    "RUBRIC_RESPONSE_SCHEMA",
    "RubricArtifact",
    "compute_axtree_stats",
    "load_rubric_prompt",
    "render_axtree_text",
    "run_rubric",
    "write_rubric_artifact",
]
