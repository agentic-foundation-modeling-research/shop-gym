"""Generator: collection filter (skill ``filter``).

Pair a populated collection with a realistic filter dimension drawn from
**that collection's own products** (not from shop-wide stats), so the chosen
``(dim, value)`` is always realizable on the storefront.

Why per-collection
------------------
Shop-wide ``stats.option_patterns`` aggregates option dimensions across the
entire catalog. A shop can have ``Color`` as its top dimension overall while
a specific collection (e.g. ``Cat Litter``) has zero products with a
``Color`` option. Earlier versions of this generator paired collections with
shop-wide dimensions by RNG-shuffle index, producing tasks that were
literally impossible — the agent could not find the named filter on the
collection page, regardless of skill.

This implementation builds a **per-collection** option index from the
collection's own products (variant ``options``, ``vendor``, ``product_type``)
and only emits a task when there exists a ``(dim, value)`` pair where at
least one product in the collection actually has that value.

Universal-safe defaults
-----------------------
``Vendor`` (often surfaced as "Brand" in storefront UIs) and ``ProductType``
("Type") are the dimensions every storefront filter UI knows how to
render, because they're top-level product fields rather than variant
options. We include them as fallbacks so that even shops with hardcoded
filter UIs yield feasible tasks.

The intent explicitly allows "no products match the filter" as a success
condition because some dimension values in a collection only match a
fraction of the products — exercising the filter UI itself is the skill
under test.
"""
from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from shop_guru.config import Shop
from shop_guru.emit import make_id
from shop_guru.filters import collections_with_min_products

# Variant-option dimensions we prefer when they're present and feasible
# in the collection. Order matters: earlier entries are tried first.
PRIORITY_DIMENSIONS: tuple[str, ...] = (
    "Color",
    "Size",
    "Format",
    "Material",
    "Style",
    "Design",
)

# Universal-safe fallbacks: top-level product fields that storefront filter
# UIs almost always surface. ``Vendor`` first because it's exposed by
# every shop we've audited, while  ``ProductType`` is occasionally absent
# from the rendered filter UI even when the data exists. 
# We try priority variant dims first so tasks are
# diverse, then fall back to these to maximize feasibility.
UNIVERSAL_DIMENSIONS: tuple[str, ...] = ("Vendor", "ProductType")

SKIP_DIMENSION_NAMES: frozenset[str] = frozenset({"title", "default", ""})

# How dimension keys appear in agent-facing intents. Variant-option dims
# use their raw product-data names (e.g. "Color"). The two universal dims
# get human-readable aliases that match what storefronts typically render.
DIMENSION_DISPLAY: dict[str, str] = {
    "ProductType": "Type",
    "Vendor": "Brand",
}


def generate(shop: Shop, data: dict[str, Any], seed: int = 0, count: int = 3) -> list[dict]:
    """Emit up to ``count`` collection-filter tasks for ``shop``.

    For each candidate collection, we pick the highest-priority dimension
    that has at least one product in the collection with a non-empty value.
    Collections where no feasible ``(dim, value)`` exists are skipped.

    The generator is deterministic for a given ``seed``: the collection
    iteration order is RNG-shuffled, but dimension/value selection within
    a collection is purely based on priority + value sort order.
    """
    rng = random.Random(seed + 1)
    products_by_handle = _index_products_by_handle(data.get("products") or [])
    candidates = collections_with_min_products(data.get("collections") or [], min_products=5)
    rng.shuffle(candidates)

    tasks: list[dict] = []
    for collection in candidates:
        if len(tasks) >= count:
            break
        choice = _pick_dimension_value(collection, products_by_handle)
        if choice is None:
            continue
        dim_key, value = choice
        tasks.append(_make_task(shop, collection, dim_key, value, len(tasks) + 1))
    return tasks


def _make_task(
    shop: Shop, collection: dict, dim_key: str, value: str, idx: int
) -> dict:
    title = collection["title"]
    handle = collection["handle"]
    display_name = DIMENSION_DISPLAY.get(dim_key, dim_key)
    return {
        "id": make_id(shop.slug, "filter", idx),
        "type": "shopping",
        "intent": (
            f'Navigate to the "{title}" collection on this store. Find '
            f"and use the {display_name} filter (e.g. {value}) to select "
            f"an option. If products are shown after filtering, select "
            f"any variant of a product and add it to cart. It is ok if "
            f"no products match the filter; using filter correctly means "
            f"the navigation task is completed successfully."
        ),
        "success_criteria": {
            "url_contains": f"/collections/{handle}",
            "type": "navigation",
        },
    }


def _pick_dimension_value(
    collection: dict, products_by_handle: dict[str, dict]
) -> tuple[str, str] | None:
    """Return the highest-priority (dim, value) feasible in this collection.

    Returns ``None`` when no priority or universal dimension has at least
    one product in the collection with a non-empty value.
    """
    index = _build_collection_option_index(collection, products_by_handle)
    if not index:
        return None

    for dim in PRIORITY_DIMENSIONS:
        if dim in SKIP_DIMENSION_NAMES:
            continue
        value = _first_value(index.get(dim))
        if value is not None:
            return dim, value

    for dim in UNIVERSAL_DIMENSIONS:
        value = _first_value(index.get(dim))
        if value is not None:
            return dim, value

    return None


def _build_collection_option_index(
    collection: dict, products_by_handle: dict[str, dict]
) -> dict[str, list[str]]:
    """Return ``{dim_name: [values]}`` for products in this collection.

    Pulls from variant ``options[].values``, plus the synthetic
    ``Vendor``/``ProductType`` dimensions derived from top-level product
    fields. Values are sorted for determinism.
    """
    by_dim: dict[str, set[str]] = defaultdict(set)
    handles: Iterable[str] = collection.get("product_handles") or []
    for handle in handles:
        product = products_by_handle.get(handle)
        if not product:
            continue
        vendor = product.get("vendor")
        if vendor:
            by_dim["Vendor"].add(vendor)
        ptype = product.get("product_type") or product.get("productType")
        if ptype:
            by_dim["ProductType"].add(ptype)
        for opt in product.get("options") or []:
            name = (opt.get("name") or "").strip()
            if not name or name.lower() in SKIP_DIMENSION_NAMES:
                continue
            for raw_value in opt.get("values") or []:
                value = (raw_value or "").strip()
                if value and value.lower() not in SKIP_DIMENSION_NAMES:
                    by_dim[name].add(value)
    return {dim: sorted(values) for dim, values in by_dim.items() if values}


def _first_value(values: list[str] | None) -> str | None:
    """Pick a deterministic representative value from a sorted list.

    Sorted-asc order keeps tasks reproducible across regenerations and
    avoids picking the literal string ``"Default Title"`` which is filtered
    out by ``_build_collection_option_index`` already.
    """
    if not values:
        return None
    return values[0]


def _index_products_by_handle(products: list[dict]) -> dict[str, dict]:
    return {p["handle"]: p for p in products if p.get("handle")}
