"""shop_arena.env_eval: deterministic environment evaluation for SandboxShops.

EnvEval probes a shop URL with BrowserGym to produce three layers of
artifacts — observation (axtree statistics + LLM-categorized screenshots),
action (BrowserGym ``HighLevelActionSet`` vocabulary + role/action
heuristic), and transition (structural BFS + stateful in-page actions) —
plus a closed-schema ``metrics.json`` digest.

Public surface (spec §5.10 + impl plan M0):

* :data:`__version__` — package version (M0).
* :mod:`errors` and its error classes — failure vocabulary.
* ``evaluate``, ``EvalConfig``, ``EvalResult`` — single-shop evaluation.
* ``compare_urls``, ``CompareConfig``, ``CompareResult`` — URL-cohort
  structural variance measurement.

As each milestone lands, its names are added to :data:`__all__` below
alongside a top-level ``from … import …`` so callers can do
``from shop_arena.env_eval import evaluate`` per spec §5.9.
"""

from __future__ import annotations

from shop_arena.env_eval import errors
from shop_arena.env_eval._version import __version__
from shop_arena.env_eval.config import EvalConfig, EvalResult
from shop_arena.env_eval.errors import (
    EnvEvalError,
    MetricsValidationError,
    PageDiscoveryError,
    ResumeError,
    ShopUnreachableError,
    StructureComparisonError,
)
from shop_arena.env_eval.pipeline import evaluate
from shop_arena.env_eval.structure import CompareConfig, CompareResult, compare_urls
from shop_arena.env_eval.visualize import render_graph_html

__all__ = [
    "CompareConfig",
    "CompareResult",
    "EnvEvalError",
    "EvalConfig",
    "EvalResult",
    "MetricsValidationError",
    "PageDiscoveryError",
    "ResumeError",
    "ShopUnreachableError",
    "StructureComparisonError",
    "__version__",
    "compare_urls",
    "errors",
    "evaluate",
    "render_graph_html",
]
