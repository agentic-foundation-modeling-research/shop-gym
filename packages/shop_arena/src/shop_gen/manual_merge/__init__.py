"""Phase 1 manual-merge steps for the ``shop_gen`` pipeline.

Implements the multi-seed manual-merge sub-DAG documented in
``docs/specs/shop_arena/shop_gen.md`` §5.2 (and the per-area rules in
§9.2). Each submodule owns one step in the table:

* :mod:`shop_gen.manual_merge.capabilities` — ``merge_capabilities``
  step + the pure :func:`merge_capabilities_seeds` helper.

* :mod:`shop_gen.manual_merge.prose` — ``merge_manual_prose`` step +
  the pure :func:`merge_manual_prose_seeds` helper.

Future submodules (T2.3-T2.6) will add the deterministic stats
recompute, manifest write, and the single-seed copy shortcut.

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.manual_merge.capabilities import (
    MergeCapabilitiesStep,
    MergeConflict,
    merge_capabilities_seeds,
)
from shop_gen.manual_merge.prose import (
    MergeManualProseStep,
    merge_manual_prose_seeds,
)

__all__ = [
    "MergeCapabilitiesStep",
    "MergeConflict",
    "MergeManualProseStep",
    "merge_capabilities_seeds",
    "merge_manual_prose_seeds",
]
