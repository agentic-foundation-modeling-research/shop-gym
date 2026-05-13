"""Phase 2 data-synthesis steps for the ``shop_arena.gen`` pipeline.

Implements the data-synthesis sub-DAG documented in
``docs/specs/shop_arena/shop_arena.gen.md`` §5.3. Each submodule owns one
synthesis step (T3.3-T3.11):

* :mod:`shop_arena.gen.data_synth.schema` — closed pydantic mirrors of the
  ``shop_backend`` v0.1 dataset contract (spec §8.1.1).
* :mod:`shop_arena.gen.data_synth.identity` — ``synth_identity`` step,
  the :class:`Identity` schema, and the deterministic name picker.
* :mod:`shop_arena.gen.data_synth.assemble` — terminal ``assemble_data`` step
  (spec §5.3 + §5.6) that emits the final ``data/*.json`` and runs the
  brand-leak scrub.

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_arena.gen.data_synth._synth_helpers import StageSynthError
from shop_arena.gen.data_synth.alt_text import (
    AltTextPayload,
    SynthAltTextStep,
    synth_alt_text_for_collection,
)
from shop_arena.gen.data_synth.assemble import (
    AssembleDataStep,
    AssembledData,
    BrandLeakError,
    assemble_records,
    scan_for_brand_leaks,
)
from shop_arena.gen.data_synth.collections import (
    CollectionDraft,
    SynthCollectionsStep,
    synth_collections_from_identity,
)
from shop_arena.gen.data_synth.details import (
    ProductDetail,
    SynthProductDetailsStep,
    synth_product_details_for_collection,
)
from shop_arena.gen.data_synth.identity import (
    Identity,
    IdentitySynthError,
    SynthIdentityStep,
    pick_name_from_allowlist,
    synth_identity_from_manual,
)
from shop_arena.gen.data_synth.images import (
    AsyncImageBackend,
    GenImagesStep,
    ImageBackend,
    OpenAIImageBackend,
    PlaceholderBackend,
    get_backend,
)
from shop_arena.gen.data_synth.navigation import (
    SynthNavigationStep,
    synth_navigation_from_collections,
)
from shop_arena.gen.data_synth.pages import SynthPagesStep, synth_pages_from_identity
from shop_arena.gen.data_synth.policies import SynthPoliciesStep, synth_policies_from_identity
from shop_arena.gen.data_synth.schema import (
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
from shop_arena.gen.data_synth.skeletons import (
    ProductSkeleton,
    SynthProductSkeletonsStep,
    synth_product_skeletons_from_collections,
)
from shop_arena.gen.data_synth.store import SynthStoreStep, synth_store_from_identity

__all__ = [
    "AltTextPayload",
    "AssembleDataStep",
    "AssembledData",
    "AsyncImageBackend",
    "BrandColors",
    "BrandLeakError",
    "Collection",
    "CollectionDraft",
    "GenImagesStep",
    "Identity",
    "IdentitySynthError",
    "ImageBackend",
    "Navigation",
    "NavigationItem",
    "NavigationItemType",
    "OpenAIImageBackend",
    "Page",
    "PaymentSettings",
    "PlaceholderBackend",
    "Policy",
    "Product",
    "ProductDetail",
    "ProductImage",
    "ProductOption",
    "ProductSkeleton",
    "ProductVariant",
    "StageSynthError",
    "Store",
    "StoreBrand",
    "SynthAltTextStep",
    "SynthCollectionsStep",
    "SynthIdentityStep",
    "SynthNavigationStep",
    "SynthPagesStep",
    "SynthPoliciesStep",
    "SynthProductDetailsStep",
    "SynthProductSkeletonsStep",
    "SynthStoreStep",
    "assemble_records",
    "get_backend",
    "pick_name_from_allowlist",
    "scan_for_brand_leaks",
    "synth_alt_text_for_collection",
    "synth_collections_from_identity",
    "synth_identity_from_manual",
    "synth_navigation_from_collections",
    "synth_pages_from_identity",
    "synth_policies_from_identity",
    "synth_product_details_for_collection",
    "synth_product_skeletons_from_collections",
    "synth_store_from_identity",
]
