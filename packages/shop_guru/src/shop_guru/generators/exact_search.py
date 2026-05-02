"""Generator: exact product search (skill ``exact``).

Sample a diverse set of product titles from ``products.json`` and ask the
agent to find each one by name and add any variant to cart.
"""
from __future__ import annotations

import random
from typing import Any

from shop_guru.config import Shop
from shop_guru.emit import make_id


def generate(shop: Shop, data: dict[str, Any], seed: int = 0, count: int = 5) -> list[dict]:
    """Emit up to ``count`` exact-search tasks for ``shop``.

    Selection favors cross-category diversity: each distinct ``product_type``
    is used at most once in the first pass. If the diversity filter leaves us
    short of ``count``, a second pass tops up with the remaining (already
    shuffled) candidates.
    """
    rng = random.Random(seed)
    candidates = [p for p in data["products"] if _is_task_candidate(p)]
    rng.shuffle(candidates)

    picked: list[dict] = []
    picked_ids: set = set()
    seen_types: set[str] = set()

    for product in candidates:
        if len(picked) >= count:
            break
        ptype = (product.get("product_type") or "").lower().strip()
        if ptype and ptype in seen_types:
            continue
        picked.append(product)
        picked_ids.add(product.get("id", id(product)))
        if ptype:
            seen_types.add(ptype)

    if len(picked) < count:
        for product in candidates:
            if len(picked) >= count:
                break
            key = product.get("id", id(product))
            if key in picked_ids:
                continue
            picked.append(product)
            picked_ids.add(key)

    tasks: list[dict] = []
    for idx, product in enumerate(picked, start=1):
        title = product["title"]
        handle = product["handle"]
        tasks.append({
            "id": make_id(shop.slug, "exact", idx),
            "type": "shopping",
            "intent": (
                f"Find the product named {title} and select any variant "
                f"to add to cart."
            ),
            "success_criteria": {
                "url_contains": f"/products/{handle}",
                "type": "product_search",
            },
        })
    return tasks


def _is_task_candidate(product: dict) -> bool:
    """True if the product is a reasonable target for a search task.

    Excludes gift cards, inactive products, and products without any
    available variant (since the agent would be asked to add-to-cart
    something permanently out of stock).
    """
    title = product.get("title") or ""
    if not title or len(title) < 4 or len(title) > 120:
        return False
    if product.get("is_gift_card"):
        return False
    status = product.get("status")
    if status is not None and status != "active":
        return False
    variants = product.get("variants") or []
    return any(v.get("available") for v in variants)
