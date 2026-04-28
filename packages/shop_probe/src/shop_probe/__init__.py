"""ShopProbe: structural-fidelity measurement instrument for Shopify-shaped storefronts."""

from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    EvidenceKind,
    EvidenceRef,
    JudgeCall,
    JudgePick,
    JudgeTruth,
    ProbeReport,
    ProbeResult,
)
from shop_probe.targets import Cohort, Pair, Target, TargetKind

__version__ = "0.0.0"

__all__ = [
    "BrowserMeta",
    "CategoryScore",
    "Cohort",
    "EvidenceKind",
    "EvidenceRef",
    "JudgeCall",
    "JudgePick",
    "JudgeTruth",
    "Pair",
    "ProbeReport",
    "ProbeResult",
    "Target",
    "TargetKind",
    "__version__",
]
