"""Capabilities schema and fragment merge for ``shop_explore``.

Implements §5.5 of the ShopExplore spec
(``docs/specs/shop_arena/shop_explore.md``): a closed pydantic v2 model
describing the structured features of a storefront, plus a deterministic
deep-merge of per-task fragments emitted by executor iterations under
``artifact/parts/<task_id>.caps.json``.

Public surface (re-exported here so callers keep using
``shop_explore.capabilities.X``):

* :class:`Capabilities` — the v0.1 schema. ``extra="forbid"`` at every
  level so unknown fields raise on validation.
* :class:`Conflict` — record of a leaf overwrite during the deep-merge,
  surfaced through ``manifest.json:capability_conflicts``.
* :class:`CapabilitiesValidationError` — raised when fragments fail to
  parse as JSON or when the merged document fails schema validation.
* :func:`merge_fragments` — read every ``*.caps.json`` under a parts
  directory in sorted filename order, merge into one
  :class:`Capabilities`, return the model and the list of leaf conflicts.

Submodules:

* :mod:`shop_explore.capabilities.schema` — closed pydantic model.
* :mod:`shop_explore.capabilities.merge` — deterministic deep-merge.
"""

from __future__ import annotations

from shop_explore.capabilities.merge import (
    CapabilitiesValidationError,
    Conflict,
    merge_fragments,
)
from shop_explore.capabilities.schema import (
    Capabilities,
    Cart,
    Collection,
    Floating,
    Homepage,
    Product,
    Search,
    ShopMeta,
    SiteShell,
)

__all__ = [
    "Capabilities",
    "CapabilitiesValidationError",
    "Cart",
    "Collection",
    "Conflict",
    "Floating",
    "Homepage",
    "Product",
    "Search",
    "ShopMeta",
    "SiteShell",
    "merge_fragments",
]
