"""Generator: find-policy tasks (skills ``shipping`` and ``returns``).

Inspects the extracted ``pages.json`` dump for pages whose title or handle
looks like a shipping/returns policy. Emits one task per shop for each kind.

Both ``/pages/<handle>`` and the default ``/policies/<name>`` routes
are included as URL hints so the LLM judge has multiple valid targets.
"""
from __future__ import annotations

from typing import Any

from shop_guru.config import Shop
from shop_guru.emit import make_id
from shop_guru.filters import pages_matching

SHIPPING_KEYWORDS: tuple[str, ...] = ("shipping", "delivery", "ship")
RETURNS_KEYWORDS: tuple[str, ...] = ("refund", "return", "exchange")

_FALLBACK_PATHS: dict[str, str] = {
    "shipping": "/policies/shipping-policy",
    "returns": "/policies/refund-policy",
}


def generate_shipping(shop: Shop, data: dict[str, Any], seed: int = 0) -> list[dict]:
    """One shipping-policy lookup task per shop."""
    return _generate(shop, data, "shipping", SHIPPING_KEYWORDS)


def generate_returns(shop: Shop, data: dict[str, Any], seed: int = 0) -> list[dict]:
    """One returns/refund-policy lookup task per shop."""
    return _generate(shop, data, "returns", RETURNS_KEYWORDS)


def _generate(
    shop: Shop,
    data: dict[str, Any],
    kind: str,
    keywords: tuple[str, ...],
) -> list[dict]:
    matched = pages_matching(data["pages"], keywords)
    hints: list[str] = [f"/pages/{m['handle']}" for m in matched]
    fallback = _FALLBACK_PATHS[kind]
    if fallback not in hints:
        hints.append(fallback)

    task = {
        "id": make_id(shop.slug, kind, 1),
        "type": "navigation",
        "intent": _intent_for(kind),
        "success_criteria": {
            "url_contains": hints[0],
            "type": "page_navigation",
        },
    }
    if len(hints) > 1:
        task["url_contains_alt"] = hints[1:]
    return [task]


def _intent_for(kind: str) -> str:
    if kind == "shipping":
        return (
            "Find the shipping policy page on this store. Look for shipping "
            "information in the footer, menu, or any navigation links. Read "
            "the shipping policy details, then leave the site."
        )
    return (
        "Find the returns and refund policy page on this store. Look for "
        "return policy information in the footer, menu, or any navigation "
        "links. Read the refund policy details, then leave the site."
    )
