"""ShopProbe: structural-fidelity measurement instrument for real storefronts."""

# `__version__` is defined before any submodule imports so that modules
# pulled in transitively (e.g. ``shop_probe.probes._runner``) can read it
# while ``shop_probe`` itself is still being initialised — the alternative
# is a circular import via ``shop_probe.report`` → ``shop_probe.surface``
# → ``shop_probe.probes._runner`` → ``shop_probe``.
__version__ = "0.0.0"

from shop_probe.bench import BenchLoadError, load_bench, load_bench_bytes
from shop_probe.fidelity import (
    BenchComparison,
    GroupSummary,
    compute_bench_comparison,
)
from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    EvidenceKind,
    EvidenceRef,
    JudgeCall,
    JudgePrediction,
    ProbeReport,
    ProbeResult,
)
from shop_probe.stability import (
    FLAKE_RATE_GATE,
    RerunGroupError,
    aggregate_flake_rates,
    consolidate_rerun_group,
    exceeds_flake_gate,
)
from shop_probe.targets import Bench, Target, TargetLabel

__all__ = [
    "FLAKE_RATE_GATE",
    "Bench",
    "BenchComparison",
    "BenchLoadError",
    "BrowserMeta",
    "CategoryScore",
    "EvidenceKind",
    "EvidenceRef",
    "GroupSummary",
    "JudgeCall",
    "JudgePrediction",
    "ProbeReport",
    "ProbeResult",
    "RerunGroupError",
    "Target",
    "TargetLabel",
    "__version__",
    "aggregate_flake_rates",
    "compute_bench_comparison",
    "consolidate_rerun_group",
    "exceeds_flake_gate",
    "load_bench",
    "load_bench_bytes",
]
