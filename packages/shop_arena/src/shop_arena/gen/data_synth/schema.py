"""Pydantic mirrors of the SandboxShop dataset schema (v0.1).

Closed-schema (``extra="forbid"``) typed mirrors of the source-of-truth
shape that ``shop_arena.gen`` produces and ``shop_backend`` consumes. The
contract is ``docs/specs/shop_backend/storefront_api.md`` §8.1.1: every
field the GraphQL surface (§5.2) actually serves has a typed mirror
here, and nothing else.

Public surface (mirrors §8.1.1 in declaration order):

* :class:`ProductImage`, :class:`ProductOption`, :class:`ProductVariant`
  — building blocks for :class:`Product`.
* :class:`Product` — entry of ``products.json``.
* :class:`Collection` — entry of ``collections.json``.
* :class:`Page` — entry of ``pages.json``.
* :class:`Policy` — entry of ``policies.json``.
* :class:`NavigationItem` — recursive nav node.
* :class:`Navigation` — root model wrapping the
  ``{menuHandle: NavigationItem[]}`` map at the top of
  ``navigation.json``.
* :class:`PaymentSettings`, :class:`BrandColors`, :class:`StoreBrand`
  — building blocks for :class:`Store`.
* :class:`Store` — single object in ``store.json``.

Down-stream callers (T3.3 onward) instantiate these models from the
JSON the LLM emits, validate, and re-serialize via
``model.model_dump(mode="json")``. The :func:`assemble_data` step
(T3.11) re-validates the assembled ``data/*.json`` against these
models before writing.

The optional dataset files (``blogs.json``, ``inventory.json``,
``metafields.json``) are deliberately **not** mirrored — they are out
of v0.1 synthesis scope per spec §8.1.2.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, RootModel

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

NavigationItemType = Literal["COLLECTION", "PRODUCT", "PAGE", "BLOG", "HTTP"]
"""Closed enum of supported nav-item targets (spec §8.1.1)."""

_CLOSED_FROZEN: Final[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
"""Shared model config: closed schema + value-type immutability.

``extra="forbid"`` is the spec's "closed schema" requirement; ``frozen``
makes every model behave as a value type so callers can pass them
across step boundaries without worrying about accidental mutation.
"""


# --------------------------------------------------------------------------- #
# Product building blocks
# --------------------------------------------------------------------------- #


class ProductImage(BaseModel):
    """One image attached to a :class:`Product` or :class:`Collection`.

    Attributes:
        id: Numeric image id (assigned deterministically by
            :func:`assemble_data`).
        src: Absolute URL or local image path (rewritten by
            ``shop_backend`` to same-origin ``/images/...`` at resolve
            time per spec §8.1.4).
        alt: Alt text or ``None`` if not authored yet.
        width: Pixel width.
        height: Pixel height.
        position: 1-indexed display position within the parent.
    """

    model_config = _CLOSED_FROZEN

    id: int
    src: str
    alt: str | None
    width: int
    height: int
    position: int


class ProductOption(BaseModel):
    """A product option group (e.g. "Size", "Color") on a :class:`Product`.

    Attributes:
        name: Option group name.
        position: 1-indexed position of this option group.
        values: All option values offered for this group.
    """

    model_config = _CLOSED_FROZEN

    name: str
    position: int
    values: list[str]


class ProductVariant(BaseModel):
    """One purchasable variant of a :class:`Product`.

    Attributes:
        id: Numeric variant id (assigned deterministically by
            :func:`assemble_data`).
        title: Variant display title.
        sku: SKU string or ``None``.
        price: Decimal price serialized as a string (spec §8.1.1
            preserves precision by carrying decimals as strings).
        compare_at_price: Strikethrough price as a string, or ``None``.
        available: Whether the variant is purchasable.
        option1: Selected value for the first :class:`ProductOption`,
            or ``None`` if the product has fewer options.
        option2: Selected value for the second option, or ``None``.
        option3: Selected value for the third option, or ``None``.
        position: 1-indexed display position within the product.
        requires_shipping: Whether this variant ships physically.
    """

    model_config = _CLOSED_FROZEN

    id: int
    title: str
    sku: str | None
    price: str
    compare_at_price: str | None
    available: bool
    option1: str | None
    option2: str | None
    option3: str | None
    position: int
    requires_shipping: bool


# --------------------------------------------------------------------------- #
# Top-level dataset records
# --------------------------------------------------------------------------- #


class Product(BaseModel):
    """One product record in ``products.json`` (spec §8.1.1).

    Attributes:
        id: Numeric product id (assigned deterministically by
            :func:`assemble_data`).
        title: Display title.
        handle: URL-safe handle.
        description_html: HTML description.
        vendor: Vendor name. Must be drawn from the fake-brand
            allowlist; enforced post-assembly by the brand-leak scanner
            (T3.11).
        product_type: Product type classification.
        tags: Free-form tags.
        published_at: ISO 8601 timestamp.
        created_at: ISO 8601 timestamp.
        updated_at: ISO 8601 timestamp.
        options: Option groups (typically 1-3 entries).
        variants: Purchasable variants. At least one is expected at
            assembly time, but the schema does not enforce it so
            partially-synthesized data still validates.
        images: Product images. May be empty mid-pipeline.
    """

    model_config = _CLOSED_FROZEN

    id: int
    title: str
    handle: str
    description_html: str
    vendor: str
    product_type: str
    tags: list[str]
    published_at: str
    created_at: str
    updated_at: str
    options: list[ProductOption]
    variants: list[ProductVariant]
    images: list[ProductImage]


class Collection(BaseModel):
    """One collection record in ``collections.json`` (spec §8.1.1).

    Attributes:
        id: Numeric collection id (assigned deterministically by
            :func:`assemble_data`).
        title: Display title.
        handle: URL-safe handle.
        description: Plain-text description, or ``None``.
        description_html: HTML description, or ``None``.
        image: Optional :class:`ProductImage` (the collection's hero).
        published_at: ISO 8601 timestamp, or ``None``.
        updated_at: ISO 8601 timestamp, or ``None``.
        sort_order: Sort-order keyword (e.g. ``"manual"``,
            ``"best-selling"``), or ``None``.
        product_handles: Handles of products that belong to this
            collection. Order is significant for ``"manual"``
            sorting.
    """

    model_config = _CLOSED_FROZEN

    id: int
    title: str
    handle: str
    description: str | None
    description_html: str | None
    image: ProductImage | None
    published_at: str | None
    updated_at: str | None
    sort_order: str | None
    product_handles: list[str]


class Page(BaseModel):
    """One page record in ``pages.json`` (spec §8.1.1).

    Spec §8.1.1 explicitly drops ``published_at`` from the live sample
    because the GraphQL ``Page`` type does not surface it.

    Attributes:
        handle: URL-safe handle.
        title: Display title.
        body_html: HTML body.
    """

    model_config = _CLOSED_FROZEN

    handle: str
    title: str
    body_html: str


class Policy(BaseModel):
    """One policy record in ``policies.json`` (spec §8.1.1).

    Attributes:
        handle: One of the conventional policy handles
            (``privacy-policy``, ``shipping-policy``, ``terms-of-service``,
            ``refund-policy``, ``subscription-policy``). The schema does
            not enumerate them so unknown-but-valid policies still
            validate.
        title: Display title.
        body_html: HTML body.
    """

    model_config = _CLOSED_FROZEN

    handle: str
    title: str
    body_html: str


class NavigationItem(BaseModel):
    """One node in a navigation tree (spec §8.1.1).

    Attributes:
        title: Display label.
        url: Absolute URL or path (e.g. ``/collections/foo``).
        type: Closed-enum target type.
        children: Sub-items. ``[]`` for leaf nodes.
    """

    model_config = _CLOSED_FROZEN

    title: str
    url: str
    type: NavigationItemType
    children: list[NavigationItem]


class Navigation(RootModel[dict[str, list[NavigationItem]]]):
    """Root model for ``navigation.json`` (spec §8.1.1).

    The top of the file is a JSON object keyed by menu handle (e.g.
    ``"main-menu"``, ``"footer"``); each value is the ordered list of
    root :class:`NavigationItem`\\ s under that menu. Modeled as a
    :class:`pydantic.RootModel` because the keys are open-ended (spec
    §8.1.1 names ``main-menu`` and ``footer`` as conventional but does
    not forbid others).
    """


# --------------------------------------------------------------------------- #
# Store building blocks
# --------------------------------------------------------------------------- #


class PaymentSettings(BaseModel):
    """``Store.payment_settings`` (spec §8.1.1).

    Attributes:
        accepted_card_brands: Accepted card brand identifiers (e.g.
            ``"VISA"``, ``"MASTER"``, ``"AMERICAN_EXPRESS"``). The
            schema does not enumerate the set so synthesis can carry
            new brands without a code change.
    """

    model_config = _CLOSED_FROZEN

    accepted_card_brands: list[str]


class BrandColors(BaseModel):
    """``Store.brand.colors`` (spec §8.1.1).

    Attributes:
        primary: Primary brand color (typically a hex like ``"#1f6f43"``).
        secondary: Secondary brand color.
    """

    model_config = _CLOSED_FROZEN

    primary: str
    secondary: str


class StoreBrand(BaseModel):
    """``Store.brand`` (spec §8.1.1).

    Attributes:
        logo_url: Logo URL or ``None`` if no logo is shipped.
        colors: Primary/secondary brand colors.
    """

    model_config = _CLOSED_FROZEN

    logo_url: str | None
    colors: BrandColors


class Store(BaseModel):
    """Single-object payload of ``store.json`` (spec §8.1.1).

    Attributes:
        shop_id: Numeric shop id (assigned deterministically by
            :func:`assemble_data`).
        name: Store display name. Must be drawn from the fake-brand
            allowlist (spec §5.6).
        domain: Storefront domain (e.g. ``"my-shop.example"``).
        description: Free-form store description.
        currency_code: ISO 4217 currency code (``USD``, ``CAD``,
            ``EUR``, ...). The schema does not constrain the set —
            invalid codes are caught downstream by the hosting check
            (Phase 3, T4.2).
        country_code: ISO 3166-1 alpha-2 country code.
        payment_settings: Accepted payment options.
        brand: Brand visuals.
        dataset_version: Optional dataset format tag. Reserved for
            future use; absent in v0.1 datasets unless the caller
            wishes to record one.
    """

    model_config = _CLOSED_FROZEN

    shop_id: int
    name: str
    domain: str
    description: str
    currency_code: str
    country_code: str
    payment_settings: PaymentSettings
    brand: StoreBrand
    dataset_version: str | None = None


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #


__all__ = [
    "BrandColors",
    "Collection",
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
]
