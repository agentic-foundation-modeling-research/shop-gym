"""shop_explore: storefront exploration pipeline.

Public surface (per spec ``docs/specs/shop_arena/shop_explore.md`` §8.1).
Submodules (``shop_explore.prefetch``, ``shop_explore.synthesize``,
``shop_explore.capabilities``) remain accessible for the function-level
entry points the spec keeps namespaced (``prefetch.run``,
``synthesize.synthesize``, ``capabilities.merge_fragments``).
"""

from __future__ import annotations

from shop_explore._version import __version__
from shop_explore.capabilities import Capabilities, CapabilitiesValidationError
from shop_explore.config import ExploreConfig, ExploreResult, RuntimeName
from shop_explore.pipeline import explore
from shop_explore.prefetch import ShopUnreachableError
from shop_explore.stats import Stats
from shop_explore.synthesize import SynthesisError

__all__ = [
    "Capabilities",
    "CapabilitiesValidationError",
    "ExploreConfig",
    "ExploreResult",
    "RuntimeName",
    "ShopUnreachableError",
    "Stats",
    "SynthesisError",
    "__version__",
    "explore",
]
