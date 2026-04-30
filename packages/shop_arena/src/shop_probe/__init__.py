"""ShopProbe: structural-fidelity measurement instrument for storefronts."""

# `__version__` is defined before any submodule imports so that modules
# pulled in transitively (e.g. ``shop_probe.probes._runner``) can read it
# while ``shop_probe`` itself is still being initialised.
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
    ProbeReport,
    ProbeResult,
)
from shop_probe.targets import Bench, Target, TargetLabel

__all__ = [
    "Bench",
    "BenchComparison",
    "BenchLoadError",
    "BrowserMeta",
    "CategoryScore",
    "EvidenceKind",
    "EvidenceRef",
    "GroupSummary",
    "ProbeReport",
    "ProbeResult",
    "Target",
    "TargetLabel",
    "__version__",
    "compute_bench_comparison",
    "load_bench",
    "load_bench_bytes",
]
