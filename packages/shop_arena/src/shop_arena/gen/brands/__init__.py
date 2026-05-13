"""Fake-brand allowlist + scanner.

See ``docs/specs/shop_arena/shop_arena.gen.md`` §5.6. The implementation
lives in :mod:`shop_arena.gen.brands.allowlist`; this module just re-exports
the public surface used by the data-synthesis assemble step (T3.11)
and the build-loop ``no_brand_leak`` verifier (T5.4).
"""

from __future__ import annotations

from shop_arena.gen.brands.allowlist import (
    Allowlist,
    Hit,
    is_allowed,
    load_allowlist,
    scan,
)

__all__ = [
    "Allowlist",
    "Hit",
    "is_allowed",
    "load_allowlist",
    "scan",
]
