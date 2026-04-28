"""ShopProbe: structural-fidelity measurement instrument for Shopify-shaped storefronts."""

# `__version__` is defined before any submodule imports so that modules
# pulled in transitively (e.g. ``shop_probe.probes._runner``) can read it
# while ``shop_probe`` itself is still being initialised — the alternative
# is a circular import via ``shop_probe.report`` → ``shop_probe.surface``
# → ``shop_probe.probes._runner`` → ``shop_probe``.
__version__ = "0.0.0"

from shop_probe.cohort import CohortLoadError, load_cohort, load_cohort_bytes
from shop_probe.fidelity import (
    CohortFidelity,
    PairFidelity,
    compute_cohort_fidelity,
    compute_pair_fidelity,
)
from shop_probe.report import (
    LIKERT_DIMENSIONS,
    BrowserMeta,
    CategoryScore,
    EvidenceKind,
    EvidenceRef,
    JudgeCall,
    JudgePick,
    JudgeTruth,
    LikertCall,
    LikertDimension,
    LikertDistribution,
    ProbeReport,
    ProbeResult,
    aggregate_likert_distributions,
)
from shop_probe.targets import Cohort, Pair, Target, TargetKind

__all__ = [
    "LIKERT_DIMENSIONS",
    "BrowserMeta",
    "CategoryScore",
    "Cohort",
    "CohortFidelity",
    "CohortLoadError",
    "EvidenceKind",
    "EvidenceRef",
    "JudgeCall",
    "JudgePick",
    "JudgeTruth",
    "LikertCall",
    "LikertDimension",
    "LikertDistribution",
    "Pair",
    "PairFidelity",
    "ProbeReport",
    "ProbeResult",
    "Target",
    "TargetKind",
    "__version__",
    "aggregate_likert_distributions",
    "compute_cohort_fidelity",
    "compute_pair_fidelity",
    "load_cohort",
    "load_cohort_bytes",
]
