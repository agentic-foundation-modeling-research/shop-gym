"""Task generators, one module per ShopGuru skill category.

Each public ``generate*`` function has signature::

    generate(shop: Shop, data: dict[str, Any], seed: int = 0, **kwargs) -> list[dict]

and returns a list of bare task dicts without a ``url`` field — the URL is
attached downstream by :func:`shop_guru.emit.emit_tasks`.
"""
from shop_guru.generators import (
    collection_browse,
    collection_filter,
    exact_search,
    find_policy,
    substitute_search,
)

__all__ = [
    "collection_browse",
    "collection_filter",
    "exact_search",
    "find_policy",
    "substitute_search",
]
