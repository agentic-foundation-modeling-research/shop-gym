"""Closed v0.1 capabilities schema (spec §5.5).

The schema is structured as one outer :class:`Capabilities` model
holding a nested section per UX area (``shop``, ``site_shell``,
``homepage``, …). Every section subclasses :class:`_Section` so that
``extra="forbid"`` is applied uniformly: unknown fields at any level
raise :class:`pydantic.ValidationError`.

All fields are optional. Per-task fragments — which only fill the keys
the task is responsible for — round-trip through this model unchanged;
the merged document produced by
:func:`shop_explore.capabilities.merge.merge_fragments` is the same
:class:`Capabilities` shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Section(BaseModel):
    """Base for nested capability sections — closed, optional fields only."""

    model_config = ConfigDict(extra="forbid")


class ShopMeta(_Section):
    """High-level descriptors for the shop itself (spec §5.5 ``shop``)."""

    descriptor: str | None = None
    category: str | None = None
    currency: str | None = None
    tone: list[str] = Field(default_factory=list)


class SiteShell(_Section):
    """Header / nav / footer shell (spec §5.5 ``site_shell``)."""

    has_announcement_bar: bool | None = None
    header_style: str | None = None
    has_mega_menu: bool | None = None
    nav_depth: int | None = None
    footer_groups: int | None = None


class Homepage(_Section):
    """Homepage layout features (spec §5.5 ``homepage``)."""

    section_types: list[str] = Field(default_factory=list)
    section_count: int | None = None
    has_popup_modal: bool | None = None


class Collection(_Section):
    """Collection / listing page features (spec §5.5 ``collection``)."""

    layout: str | None = None
    columns_desktop: int | None = None
    filters: list[str] = Field(default_factory=list)
    sort: list[str] = Field(default_factory=list)
    pagination: str | None = None


class Product(_Section):
    """Product detail page features (spec §5.5 ``product``)."""

    gallery_style: str | None = None
    variant_selectors: list[str] = Field(default_factory=list)
    has_quantity_selector: bool | None = None
    description_layout: str | None = None
    has_reviews: bool | None = None
    has_recommendations: bool | None = None
    has_personalization: bool | None = None


class Cart(_Section):
    """Cart UX features (spec §5.5 ``cart``)."""

    type: str | None = None
    has_promo_input: bool | None = None
    has_upsells: bool | None = None
    has_shipping_estimate: bool | None = None


class Search(_Section):
    """Search UX features (spec §5.5 ``search``)."""

    trigger: str | None = None
    has_predictive: bool | None = None
    predictive_types: list[str] = Field(default_factory=list)
    results_layout: str | None = None


class Floating(_Section):
    """Floating / overlay widgets (spec §5.5 ``floating``)."""

    has_chat_widget: bool | None = None
    has_age_gate: bool | None = None
    has_cookie_banner: bool | None = None
    has_newsletter_popup: bool | None = None


class Capabilities(BaseModel):
    """Closed v0.1 capabilities schema for a storefront.

    Unknown fields at any level raise ``ValidationError``. All fields
    are optional so per-task fragments — which only fill the keys the
    task is responsible for — round-trip through this model. The merged
    document produced by
    :func:`shop_explore.capabilities.merge.merge_fragments` is the same
    model.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = "0.1"
    shop: ShopMeta = Field(default_factory=ShopMeta)
    site_shell: SiteShell = Field(default_factory=SiteShell)
    homepage: Homepage = Field(default_factory=Homepage)
    collection: Collection = Field(default_factory=Collection)
    product: Product = Field(default_factory=Product)
    cart: Cart = Field(default_factory=Cart)
    search: Search = Field(default_factory=Search)
    floating: Floating = Field(default_factory=Floating)
    info_pages_present: list[str] = Field(default_factory=list)
