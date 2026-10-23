"""URL-observable website-structure snapshots and cohort comparison."""

from __future__ import annotations

from shop_arena.env_eval.structure.compare import (
    CompareConfig,
    CompareResult,
    compare_urls,
)
from shop_arena.env_eval.structure.distance import (
    compute_cohort_mean,
    distances_from_mean,
    summarize_distances,
)
from shop_arena.env_eval.structure.schema import (
    StructureSnapshot,
    VarianceReport,
    load_snapshot,
)
from shop_arena.env_eval.structure.snapshot import extract_snapshot

__all__ = [
    "CompareConfig",
    "CompareResult",
    "StructureSnapshot",
    "VarianceReport",
    "compare_urls",
    "compute_cohort_mean",
    "distances_from_mean",
    "extract_snapshot",
    "load_snapshot",
    "summarize_distances",
]
