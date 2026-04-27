"""Phase 2 data-synthesis steps for the ``shop_gen`` pipeline.

Implements the data-synthesis sub-DAG documented in
``docs/specs/shop_arena/shop_gen.md`` §5.3. Each future submodule owns
one synthesis step (T3.3-T3.11); this package exists so M3 tasks can
land independently. Today only the schema mirrors are populated:

* :mod:`shop_gen.data_synth.schema` — closed pydantic mirrors of the
  ``shop_backend`` v0.1 dataset contract (spec §8.1.1).

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.data_synth.schema import (
    BrandColors,
    Collection,
    Navigation,
    NavigationItem,
    NavigationItemType,
    Page,
    PaymentSettings,
    Policy,
    Product,
    ProductImage,
    ProductOption,
    ProductVariant,
    Store,
    StoreBrand,
)

__all__ = [
    "BrandColors",
    "Collection",
    "Navigation",
    "NavigationItem",
    "NavigationItemType",
    "Page",
    "PaymentSettings",
    "Policy",
    "Product",
    "ProductImage",
    "ProductOption",
    "ProductVariant",
    "Store",
    "StoreBrand",
]
