"""Deterministic analysis statistics for ``shop_explore``.

Implements §5.6 of the ShopExplore spec
(``docs/specs/shop_arena/shop_explore.md``): a pure function over the
prefetched ``products.json`` / ``collections.json`` / ``cart.js`` plus a
merged :class:`~shop_explore.capabilities.Capabilities` document, that
produces the published ``stats.json``. No LLM. No network.

Public surface:

* :class:`PriceStats` — distribution stats for the variant price set.
* :class:`ProductsPerCollection` — distribution stats for the
  per-collection product counts.
* :class:`Stats` — closed v0.1 schema written to ``stats.json``.
* :func:`compute` — read the prefetch + capabilities and produce
  :class:`Stats`.

Spec contract worth calling out explicitly:

* ``products_total`` is the exact count from
  :func:`shop_explore.prefetch.run`'s paginated walk of
  ``/products.json?page=N&limit=250``. There is no truncation flag —
  pagination terminates only on the storefront's last (short) page or
  the safety cap in :mod:`shop_explore.prefetch.runner`.
* ``feature_count`` is derived from ``capabilities``: every truthy bool
  contributes ``1`` and every non-empty list contributes its length.
  Numeric leaves (e.g. ``nav_depth``) are not counted; they surface
  separately via dedicated fields.
* Missing prefetch files (e.g. an early bot-block before the fetch plan
  finished) are treated as empty inputs — the stats still validate as a
  :class:`Stats`. The caller is expected to surface the bot-block via
  ``ShopUnreachableError`` long before reaching this module.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from shop_explore.capabilities import Capabilities


class ProductsPerCollection(BaseModel):
    """Distribution stats for the per-collection product counts.

    Attributes:
        avg: Arithmetic mean of ``products_count`` across non-empty
            collections list. ``0.0`` when there are no collections.
        median: Median ``products_count``. ``0.0`` when there are no
            collections.
        max: Maximum ``products_count``. ``0`` when there are no
            collections.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    avg: float = 0.0
    median: float = 0.0
    max: int = 0


class PriceStats(BaseModel):
    """Distribution stats for variant prices observed in ``products.json``.

    Attributes:
        min: Minimum variant price. ``0.0`` when no variants observed.
        max: Maximum variant price. ``0.0`` when no variants observed.
        median: Median variant price. ``0.0`` when no variants observed.
        currency: ISO currency code, sourced from
            ``capabilities.shop.currency`` if set, else from
            ``prefetch/cart.js``'s ``currency`` field, else ``""``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    min: float = 0.0
    max: float = 0.0
    median: float = 0.0
    currency: str = ""


class Stats(BaseModel):
    """Closed v0.1 schema for ``stats.json`` (spec §5.6).

    See module docstring for derivation rules. Unknown fields raise on
    validation so schema drift is loud.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    products_total: int = 0
    collections_total: int = 0
    products_per_collection: ProductsPerCollection = Field(default_factory=ProductsPerCollection)
    price: PriceStats = Field(default_factory=PriceStats)
    products_with_variants_pct: float = 0.0
    variant_axes_observed: list[str] = Field(default_factory=list)
    navigation_depth_max: int = 0
    homepage_section_count: int = 0
    info_pages_count: int = 0
    feature_count: int = 0


def compute(prefetch_dir: Path, capabilities: Capabilities) -> Stats:
    """Compute :class:`Stats` from prefetch artifacts and merged capabilities.

    Pure function. Reads ``prefetch_dir/products.json``,
    ``prefetch_dir/collections.json``, and ``prefetch_dir/cart.js`` (the
    last only as a fallback for ``price.currency``). Missing files are
    treated as empty inputs — see the module docstring for rationale.

    Args:
        prefetch_dir: ``run_dir/artifact/prefetch/`` populated by
            :func:`shop_explore.prefetch.run`.
        capabilities: The merged capabilities document produced by
            :func:`shop_explore.capabilities.merge_fragments`.

    Returns:
        A :class:`Stats` instance ready to be serialized to
        ``artifact/stats.json``.

    Raises:
        FileNotFoundError: ``prefetch_dir`` does not exist.
        NotADirectoryError: ``prefetch_dir`` exists but is not a
            directory.
        ValueError: A prefetch JSON file is present but malformed
            (cannot be decoded as JSON).
    """
    if not prefetch_dir.exists():
        raise FileNotFoundError(f"prefetch_dir does not exist: {prefetch_dir}")
    if not prefetch_dir.is_dir():
        raise NotADirectoryError(f"prefetch_dir is not a directory: {prefetch_dir}")

    products = _load_array(prefetch_dir / "products.json", "products")
    collections = _load_array(prefetch_dir / "collections.json", "collections")

    return Stats(
        products_total=len(products),
        collections_total=len(collections),
        products_per_collection=_products_per_collection(collections),
        price=_price_stats(products, capabilities, prefetch_dir),
        products_with_variants_pct=_products_with_variants_pct(products),
        variant_axes_observed=_variant_axes_observed(products),
        navigation_depth_max=capabilities.site_shell.nav_depth or 0,
        homepage_section_count=capabilities.homepage.section_count or 0,
        info_pages_count=len(capabilities.info_pages_present),
        feature_count=_feature_count(capabilities),
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _load_json(path: Path) -> Any:
    """Return the parsed JSON document at ``path``, or ``None`` if missing.

    Bad JSON raises :class:`ValueError` (wrapping the underlying
    :class:`json.JSONDecodeError`) so silent corruption never leaks
    through into ``stats.json``.
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc


def _load_array(path: Path, key: str) -> list[dict[str, Any]]:
    """Load a Shopify ajax-API response shaped ``{"<key>": [...]}``.

    Returns the list at ``key``, dropping any non-object entries so the
    downstream helpers can rely on dict access without re-checking each
    item. Missing file or unexpected shape collapses to an empty list.
    """
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return []
    obj = cast(dict[str, Any], raw)
    items = obj.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in cast(list[Any], items) if isinstance(item, dict)]


def _products_per_collection(
    collections: list[dict[str, Any]],
) -> ProductsPerCollection:
    """Aggregate ``products_count`` across collections."""
    counts: list[int] = []
    for collection in collections:
        value = collection.get("products_count")
        if isinstance(value, bool):  # bool is an int subclass; reject explicitly
            continue
        if isinstance(value, int) and value >= 0:
            counts.append(value)
    if not counts:
        return ProductsPerCollection()
    return ProductsPerCollection(
        avg=sum(counts) / len(counts),
        median=float(statistics.median(counts)),
        max=max(counts),
    )


def _price_stats(
    products: list[dict[str, Any]],
    capabilities: Capabilities,
    prefetch_dir: Path,
) -> PriceStats:
    """Aggregate variant prices across products + resolve currency."""
    prices: list[float] = []
    for product in products:
        for variant in _variants(product):
            price = _coerce_price(variant.get("price"))
            if price is not None:
                prices.append(price)

    currency = capabilities.shop.currency or _cart_js_currency(prefetch_dir)
    if not prices:
        return PriceStats(currency=currency)
    return PriceStats(
        min=min(prices),
        max=max(prices),
        median=float(statistics.median(prices)),
        currency=currency,
    )


def _cart_js_currency(prefetch_dir: Path) -> str:
    """Return the ``currency`` field from ``prefetch/cart.js``, else ``""``."""
    raw = _load_json(prefetch_dir / "cart.js")
    if isinstance(raw, dict):
        currency = cast(dict[str, Any], raw).get("currency")
        if isinstance(currency, str):
            return currency
    return ""


def _coerce_price(value: Any) -> float | None:
    """Parse a Shopify price (string or numeric) into a float, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _variants(product: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``variants`` list of a product, defensively typed."""
    raw = product.get("variants")
    if not isinstance(raw, list):
        return []
    return [v for v in cast(list[Any], raw) if isinstance(v, dict)]


def _products_with_variants_pct(products: list[dict[str, Any]]) -> float:
    """Fraction of products that ship with more than one variant.

    Single-variant products are Shopify's no-options default; the
    "has variants" signal we want is ``len(variants) > 1``.
    """
    if not products:
        return 0.0
    with_variants = sum(1 for product in products if len(_variants(product)) > 1)
    return with_variants / len(products)


def _variant_axes_observed(products: list[dict[str, Any]]) -> list[str]:
    """Union of variant option names across products, lower-cased.

    Order is first-encountered (deterministic given the products.json
    order from the prefetch). Names are normalized to lowercase with
    surrounding whitespace stripped.
    """
    seen: dict[str, None] = {}
    for product in products:
        options = product.get("options")
        if not isinstance(options, list):
            continue
        for option in cast(list[Any], options):
            name: str | None = None
            if isinstance(option, str):
                name = option
            elif isinstance(option, dict):
                raw_name = cast(dict[str, Any], option).get("name")
                if isinstance(raw_name, str):
                    name = raw_name
            if name is None:
                continue
            normalized = name.strip().lower()
            if normalized and normalized not in seen:
                seen[normalized] = None
    return list(seen)


def _feature_count(capabilities: Capabilities) -> int:
    """Count truthy bools and non-empty list lengths inside ``capabilities``.

    Numeric and string leaves (e.g. ``version``, ``nav_depth``,
    ``section_count``) are excluded — they surface separately as
    dedicated fields on :class:`Stats`.
    """
    return _count_features(capabilities.model_dump())


def _count_features(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, list):
        return len(cast(list[Any], value))
    if isinstance(value, dict):
        return sum(_count_features(child) for child in cast(dict[str, Any], value).values())
    return 0
