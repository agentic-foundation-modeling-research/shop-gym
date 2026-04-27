"""Phase 2 data-synthesis steps for the ``shop_gen`` pipeline.

Implements the data-synthesis sub-DAG documented in
``docs/specs/shop_arena/shop_gen.md`` §5.3. Each submodule owns one
synthesis step (T3.3-T3.11):

* :mod:`shop_gen.data_synth.schema` — closed pydantic mirrors of the
  ``shop_backend`` v0.1 dataset contract (spec §8.1.1).
* :mod:`shop_gen.data_synth.identity` — ``synth_identity`` step,
  the :class:`Identity` schema, and the deterministic name picker.

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.data_synth.identity import (
    Identity,
    IdentitySynthError,
    SynthIdentityStep,
    pick_name_from_allowlist,
    synth_identity_from_manual,
)
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
    "Identity",
    "IdentitySynthError",
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
    "SynthIdentityStep",
    "pick_name_from_allowlist",
    "synth_identity_from_manual",
]
