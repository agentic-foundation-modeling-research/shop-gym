"""Generator: collection browse (skill ``browse``).

Pick genuinely populated, customer-facing collections from
``collections.json`` and ask the agent to navigate there, choose a product,
and add any variant to cart.
"""
from __future__ import annotations

import random
from typing import Any

from shop_guru.config import Shop
from shop_guru.emit import make_id
from shop_guru.filters import collections_with_min_products


def generate(shop: Shop, data: dict[str, Any], seed: int = 0, count: int = 5) -> list[dict]:
    """Emit up to ``count`` collection-browse tasks for ``shop``."""
    rng = random.Random(seed)
    eligible = collections_with_min_products(data["collections"], min_products=3)
    rng.shuffle(eligible)

    tasks: list[dict] = []
    for idx, collection in enumerate(eligible[:count], start=1):
        title = collection["title"]
        handle = collection["handle"]
        tasks.append({
            "id": make_id(shop.slug, "browse", idx),
            "type": "shopping",
            "intent": (
                f'Navigate to the "{title}" collection on this store. Browse '
                f"the products in this category, select any product, choose a "
                f"variant if available, and add it to cart."
            ),
            "success_criteria": {
                "url_contains": f"/collections/{handle}",
                "type": "collection_browse",
            },
        })
    return tasks
