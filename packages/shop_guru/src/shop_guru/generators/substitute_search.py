"""Generator: substitute product search (skill ``substitute``).

Uses the same source products as :mod:`exact_search` so the two datasets
are paired — only the intent wording differs.
"""
from __future__ import annotations

from typing import Any

from shop_guru.config import Shop
from shop_guru.emit import make_id
from shop_guru.generators import exact_search


def generate(shop: Shop, data: dict[str, Any], seed: int = 0, count: int = 5) -> list[dict]:
    """Emit up to ``count`` substitute-search tasks for ``shop``.

    Each task references the same product as the corresponding
    :mod:`exact_search` task but asks the agent to find a semantically
    similar alternative instead of an exact match.
    """
    base_tasks = exact_search.generate(shop, data, seed=seed, count=count)
    tasks: list[dict] = []
    for idx, exact_task in enumerate(base_tasks, start=1):
        title = _extract_product_title(exact_task["intent"])
        tasks.append({
            "id": make_id(shop.slug, "substitute", idx),
            "type": "shopping",
            "intent": (
                f"Find a product that is similar to {title} and select any "
                f"variant to add to cart."
            ),
            "success_criteria": {
                "url_contains": "/products/",
                "type": "product_substitute",
            },
        })
    return tasks


def _extract_product_title(exact_intent: str) -> str:
    """Recover the product title from an exact-search intent string."""
    marker = "Find the product named "
    end_marker = " and "
    if marker not in exact_intent or end_marker not in exact_intent:
        raise ValueError(f"Cannot extract product title from intent: {exact_intent!r}")
    return exact_intent.split(marker, 1)[1].split(end_marker, 1)[0]
