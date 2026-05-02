"""ShopProbe: structural-fidelity measurement instrument for storefronts.

v1.0 organizes the rubric around three families that map to the components
of an agent's MDP — ``observation`` / ``action`` / ``transition`` — keyed
on five canonical page types and (where applicable) two modalities (a11y
tree / screenshot). See ``docs/specs/shop_arena/shop_arena.probe.md``.
"""

from __future__ import annotations

__version__ = "1.0.0"

from shop_arena.probe.bench import BenchLoadError, load_bench, load_bench_bytes
from shop_arena.probe.fidelity import BenchComparison, compare_cohorts
from shop_arena.probe.report import ProbeReport, SlotVerdict, TransitionResult
from shop_arena.probe.rubric import (
    Rubric,
    RubricEntry,
    RubricLoadError,
    load_rubric,
    load_rubric_bytes,
)
from shop_arena.probe.targets import Bench, Target, TargetLabel

__all__ = [
    "Bench",
    "BenchComparison",
    "BenchLoadError",
    "ProbeReport",
    "Rubric",
    "RubricEntry",
    "RubricLoadError",
    "SlotVerdict",
    "Target",
    "TargetLabel",
    "TransitionResult",
    "__version__",
    "compare_cohorts",
    "load_bench",
    "load_bench_bytes",
    "load_rubric",
    "load_rubric_bytes",
]
