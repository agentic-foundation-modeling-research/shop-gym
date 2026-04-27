"""shop_gen: main SandboxShop generation pipeline.

Ingests a live storefront description and produces a deterministic,
self-contained SandboxShop (catalog, navigation, policies, static assets).
"""

from __future__ import annotations

from shop_gen._version import __version__
from shop_gen.config import ShopGenConfig, ShopGenResult
from shop_gen.pipeline import run

__all__ = [
    "ShopGenConfig",
    "ShopGenResult",
    "__version__",
    "run",
]
