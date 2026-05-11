"""shop_arena.explore: storefront exploration pipeline.

Public surface (per spec ``docs/specs/shop_arena/shop_arena.explore.md`` §8.1).
Submodules (``shop_arena.explore.prefetch``, ``shop_arena.explore.synthesize``,
``shop_arena.explore.capabilities``) remain accessible for the function-level
entry points the spec keeps namespaced (``prefetch.run``,
``synthesize.synthesize``, ``capabilities.merge_fragments``).
"""

from __future__ import annotations

from shop_arena.explore._version import __version__
from shop_arena.explore.capabilities import Capabilities, CapabilitiesValidationError
from shop_arena.explore.config import ExploreConfig, ExploreResult, RuntimeName
from shop_arena.explore.pipeline import explore
from shop_arena.explore.prefetch import ShopUnreachableError
from shop_arena.explore.stats import Stats
from shop_arena.explore.synthesize import SynthesisError

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
