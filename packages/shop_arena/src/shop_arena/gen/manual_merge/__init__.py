"""Phase 1 manual-merge steps for the ``shop_arena.gen`` pipeline.

Implements the multi-seed manual-merge sub-DAG documented in
``docs/specs/shop_arena/shop_arena.gen.md`` §5.2 (and the per-area rules in
§9.2). Each submodule owns one step in the table:

* :mod:`shop_arena.gen.manual_merge.capabilities` — ``merge_capabilities``
  step + the pure :func:`merge_capabilities_seeds` helper.

* :mod:`shop_arena.gen.manual_merge.prose` — ``merge_manual_prose`` step +
  the pure :func:`merge_manual_prose_seeds` helper.

* :mod:`shop_arena.gen.manual_merge.stats` — ``compute_merge_stats`` step +
  the pure :func:`merge_stats_seeds` helper.

* :mod:`shop_arena.gen.manual_merge.manifest` — ``write_merge_manifest``
  step + the :class:`Manifest` / :class:`WriteHistoryEntry` schemas.

* :mod:`shop_arena.gen.manual_merge.copy_seed` — ``copy_seed_manual`` step,
  the single-seed shortcut that bypasses the merge sub-DAG (spec §5.2).

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_arena.gen.manual_merge.capabilities import (
    MergeCapabilitiesStep,
    MergeConflict,
    merge_capabilities_seeds,
)
from shop_arena.gen.manual_merge.copy_seed import CopySeedManualStep
from shop_arena.gen.manual_merge.manifest import (
    Manifest,
    WriteHistoryEntry,
    WriteMergeManifestStep,
)
from shop_arena.gen.manual_merge.prose import (
    MergeManualProseStep,
    merge_manual_prose_seeds,
)
from shop_arena.gen.manual_merge.split import (
    SplitManualPartsStep,
    split_manual_into_parts,
)
from shop_arena.gen.manual_merge.stats import (
    ComputeMergeStatsStep,
    StatsValidationError,
    merge_stats_seeds,
)

__all__ = [
    "ComputeMergeStatsStep",
    "CopySeedManualStep",
    "Manifest",
    "MergeCapabilitiesStep",
    "MergeConflict",
    "MergeManualProseStep",
    "SplitManualPartsStep",
    "StatsValidationError",
    "WriteHistoryEntry",
    "WriteMergeManifestStep",
    "merge_capabilities_seeds",
    "merge_manual_prose_seeds",
    "merge_stats_seeds",
    "split_manual_into_parts",
]
