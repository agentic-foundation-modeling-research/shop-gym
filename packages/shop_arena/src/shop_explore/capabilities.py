"""Capabilities schema and fragment merge for ``shop_explore``.

Implements §5.5 of the ShopExplore spec
(``docs/specs/shop_arena/shop_explore.md``): a closed pydantic v2 model
describing the structured features of a storefront, plus a deterministic
deep-merge of per-task fragments emitted by executor iterations under
``artifact/parts/<task_id>.caps.json``.

Public surface:

* :class:`Capabilities` — the v0.1 schema. ``extra="forbid"`` at every
  level so unknown fields raise on validation.
* :class:`Conflict` — record of a leaf overwrite during the deep-merge,
  surfaced through ``manifest.json:capability_conflicts``.
* :class:`CapabilitiesValidationError` — raised when fragments fail to
  parse as JSON or when the merged document fails schema validation.
* :func:`merge_fragments` — read every ``*.caps.json`` under a parts
  directory in sorted filename order, merge into one
  :class:`Capabilities`, return the model and the list of leaf conflicts.

Merge semantics (spec §5.5):

* Dicts merge recursively.
* Lists union, deduplicated, order-preserving (existing items first,
  then new items not already present).
* Scalar leaves overwrite (last writer wins). Non-equal overwrites are
  recorded as :class:`Conflict` entries.

Fragments may be partial — every top-level section and every leaf is
optional. The merged result is validated as a complete
:class:`Capabilities`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CapabilitiesValidationError(ValueError):
    """Raised when a fragment is malformed or the merged document is invalid.

    Wraps both ``json.JSONDecodeError`` (bad fragment file) and
    ``pydantic.ValidationError`` (unknown fields, type mismatch, …) so
    callers have one error class to catch.
    """


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


class Intl(_Section):
    """Internationalization switchers (spec §5.5 ``intl``)."""

    has_locale_switcher: bool | None = None
    has_currency_switcher: bool | None = None


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
    document produced by :func:`merge_fragments` is the same model.
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
    intl: Intl = Field(default_factory=Intl)
    floating: Floating = Field(default_factory=Floating)
    info_pages_present: list[str] = Field(default_factory=list)


class Conflict(BaseModel):
    """One leaf-level overwrite recorded during fragment merge.

    Attributes:
        path: Dotted path of the conflicting leaf, e.g. ``cart.type``.
        previous_value: Value present before the overwrite.
        previous_source: Filename of the fragment that set
            ``previous_value``.
        new_value: Value that overwrote ``previous_value``.
        new_source: Filename of the fragment that set ``new_value``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    previous_value: Any
    previous_source: str
    new_value: Any
    new_source: str


def _hashable_key(value: Any) -> Any:
    """Return a hashable key for list-union dedup.

    Scalars hash directly; dicts / lists are JSON-encoded with sorted
    keys so structurally equal items collapse.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True)


def _seed_sources(value: Any, *, source: str, sources: dict[str, str], path: str) -> None:
    """Record ``source`` for every leaf path inside a freshly-adopted subtree.

    When a new key is added wholesale to the merge target, future merges
    that recurse into the subtree may overwrite individual leaves; we
    need to know which fragment first set them so :class:`Conflict` can
    name a real ``previous_source``.
    """
    if isinstance(value, dict):
        for key, sub in value.items():
            child_path = f"{path}.{key}" if path else key
            _seed_sources(sub, source=source, sources=sources, path=child_path)
        return
    # Lists have no single source (union semantics); only scalar leaves
    # carry an attributable source.
    if isinstance(value, list):
        return
    sources[path] = source


def _deep_merge(
    target: dict[str, Any],
    addition: dict[str, Any],
    *,
    source: str,
    sources: dict[str, str],
    conflicts: list[Conflict],
    path: str = "",
) -> None:
    """Merge ``addition`` into ``target`` in-place per spec §5.5.

    Updates ``sources`` (path → fragment that set the leaf) and appends
    to ``conflicts`` whenever a non-equal scalar leaf is overwritten.
    """
    for key, value in addition.items():
        full_path = f"{path}.{key}" if path else key

        if key not in target:
            target[key] = value
            _seed_sources(value, source=source, sources=sources, path=full_path)
            continue

        existing = target[key]

        if isinstance(existing, dict) and isinstance(value, dict):
            _deep_merge(
                existing,
                value,
                source=source,
                sources=sources,
                conflicts=conflicts,
                path=full_path,
            )
            continue

        if isinstance(existing, list) and isinstance(value, list):
            seen: set[Any] = {_hashable_key(item) for item in existing}
            merged: list[Any] = list(existing)
            for item in value:
                key_for_dedupe = _hashable_key(item)
                if key_for_dedupe not in seen:
                    seen.add(key_for_dedupe)
                    merged.append(item)
            target[key] = merged
            # List union has no single "winner"; do not touch sources.
            continue

        # Scalar leaf (or type-mismatched merge): last writer wins.
        if existing != value:
            conflicts.append(
                Conflict(
                    path=full_path,
                    previous_value=existing,
                    previous_source=sources.get(full_path, "<unknown>"),
                    new_value=value,
                    new_source=source,
                )
            )
        target[key] = value
        sources[full_path] = source


def _load_fragment(path: Path) -> dict[str, Any]:
    """Load one ``*.caps.json`` fragment; raise on bad JSON or non-object."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CapabilitiesValidationError(f"fragment {path.name} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CapabilitiesValidationError(
            f"fragment {path.name} must be a JSON object, got {type(raw).__name__}"
        )
    return raw


def merge_fragments(parts_dir: Path) -> tuple[Capabilities, list[Conflict]]:
    """Merge every ``*.caps.json`` under ``parts_dir`` into one schema.

    Fragments are read in sorted filename order so the merge is
    deterministic. The result is validated as a :class:`Capabilities`;
    schema violations (unknown fields, wrong types) raise
    :class:`CapabilitiesValidationError`.

    An empty (or fragment-less) ``parts_dir`` yields a default
    :class:`Capabilities` and an empty conflict list.

    Args:
        parts_dir: Directory containing ``<task_id>.caps.json`` fragments.

    Returns:
        Tuple of the merged :class:`Capabilities` and the list of
        leaf-level :class:`Conflict` entries recorded during the merge.

    Raises:
        CapabilitiesValidationError: A fragment was malformed JSON, was
            not a JSON object, or the merged document failed schema
            validation.
        FileNotFoundError: ``parts_dir`` does not exist.
    """
    if not parts_dir.exists():
        raise FileNotFoundError(f"parts_dir does not exist: {parts_dir}")
    if not parts_dir.is_dir():
        raise NotADirectoryError(f"parts_dir is not a directory: {parts_dir}")

    merged: dict[str, Any] = {}
    sources: dict[str, str] = {}
    conflicts: list[Conflict] = []

    for fragment_path in sorted(parts_dir.glob("*.caps.json")):
        fragment = _load_fragment(fragment_path)
        _deep_merge(
            merged,
            fragment,
            source=fragment_path.name,
            sources=sources,
            conflicts=conflicts,
        )

    try:
        capabilities = Capabilities.model_validate(merged)
    except ValidationError as exc:
        raise CapabilitiesValidationError(
            f"merged capabilities failed schema validation: {exc}"
        ) from exc

    return capabilities, conflicts
