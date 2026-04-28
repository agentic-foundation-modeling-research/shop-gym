"""``assemble_data`` — Phase 2 final assembly + brand-leak scrub (spec §5.3 + §5.6).

Terminal data-synthesis step. Reads every cached upstream payload under
``<out_dir>/.shop_gen/stage_cache/`` and ``identity.json``, assigns
deterministic numeric ids (sha256-prefix of handle), joins
skeletons + details + alt-text + image manifest into the final
:class:`~shop_gen.data_synth.schema.Product` records, and emits the
six published files under ``<out_dir>/data/``:

* ``store.json``
* ``products.json``
* ``collections.json``
* ``pages.json``
* ``policies.json``
* ``navigation.json``

After the pydantic-validated payload is built, the orchestrator would
historically run the :mod:`shop_gen.brands.allowlist` scanner over
every string field. **As of v0.1.x that assemble-time scrub is
disabled** (see spec §5.6 "Current status"): the simple
``[A-Z][A-Za-z]+`` tokenizer cannot distinguish brand-shaped tokens
from Title-Cased English plurals, which dominate legitimate
storefront navigation ("Card Readers", "Pin Pads", "Receipt
Printers"). The build-loop ``no_brand_leak`` verifier (§5.5.3) still
runs over ``hydrogen/app/**``. The helpers (:func:`scan_for_brand_leaks`,
:class:`BrandLeakError`, :func:`_walk_strings`, :func:`_step_for_field_path`)
remain in this module so a smarter v0.2 tokenizer can re-enable the
scrub without re-deriving the field-path → upstream-step mapping.

Step contract (spec §5.7.1):

* ``id``: ``assemble_data``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_gen.steps.base.StepInput` per upstream
  Phase 2 step (``synth_identity``, ``synth_store``,
  ``synth_collections``, ``synth_pages``, ``synth_policies``,
  ``synth_product_skeletons``, ``synth_product_details``,
  ``synth_alt_text``, ``gen_images``, ``synth_navigation``).
* ``outputs``: the six ``data/*.json`` files listed above. The
  generated images under ``data/images/`` are owned by
  :class:`~shop_gen.data_synth.images.GenImagesStep` and **not**
  declared here.
* ``depends_on``: same upstream ids as :attr:`inputs`.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

from pydantic import ValidationError

from shop_gen.brands.allowlist import Allowlist, Hit, load_allowlist, scan
from shop_gen.data_synth._synth_helpers import StageSynthError
from shop_gen.data_synth.collections import CollectionDraft
from shop_gen.data_synth.details import ProductDetail
from shop_gen.data_synth.schema import (
    Collection,
    Navigation,
    Page,
    Policy,
    Product,
    ProductImage,
    ProductVariant,
    Store,
)
from shop_gen.data_synth.skeletons import ProductSkeleton
from shop_gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "assemble_data"
_STEP_VERSION: Final[int] = 1

_UPSTREAM_IDENTITY: Final[str] = "synth_identity"
_UPSTREAM_STORE: Final[str] = "synth_store"
_UPSTREAM_COLLECTIONS: Final[str] = "synth_collections"
_UPSTREAM_PAGES: Final[str] = "synth_pages"
_UPSTREAM_POLICIES: Final[str] = "synth_policies"
_UPSTREAM_SKELETONS: Final[str] = "synth_product_skeletons"
_UPSTREAM_DETAILS: Final[str] = "synth_product_details"
_UPSTREAM_ALT_TEXT: Final[str] = "synth_alt_text"
_UPSTREAM_IMAGES: Final[str] = "gen_images"
_UPSTREAM_NAVIGATION: Final[str] = "synth_navigation"

_UPSTREAM_IDS: Final[tuple[str, ...]] = (
    _UPSTREAM_IDENTITY,
    _UPSTREAM_STORE,
    _UPSTREAM_COLLECTIONS,
    _UPSTREAM_PAGES,
    _UPSTREAM_POLICIES,
    _UPSTREAM_SKELETONS,
    _UPSTREAM_DETAILS,
    _UPSTREAM_ALT_TEXT,
    _UPSTREAM_IMAGES,
    _UPSTREAM_NAVIGATION,
)

_DATA_DIR: Final[Path] = Path("data")
_OUT_STORE: Final[Path] = _DATA_DIR / "store.json"
_OUT_PRODUCTS: Final[Path] = _DATA_DIR / "products.json"
_OUT_COLLECTIONS: Final[Path] = _DATA_DIR / "collections.json"
_OUT_PAGES: Final[Path] = _DATA_DIR / "pages.json"
_OUT_POLICIES: Final[Path] = _DATA_DIR / "policies.json"
_OUT_NAVIGATION: Final[Path] = _DATA_DIR / "navigation.json"

_OUT_FILES: Final[tuple[Path, ...]] = (
    _OUT_STORE,
    _OUT_PRODUCTS,
    _OUT_COLLECTIONS,
    _OUT_PAGES,
    _OUT_POLICIES,
    _OUT_NAVIGATION,
)

_CACHE_DIR: Final[Path] = Path(".shop_gen") / "stage_cache"
_IN_IDENTITY: Final[Path] = Path("identity.json")
_IN_STORE: Final[Path] = _CACHE_DIR / "store.json"
_IN_COLLECTIONS: Final[Path] = _CACHE_DIR / "collections.json"
_IN_PAGES: Final[Path] = _CACHE_DIR / "pages.json"
_IN_POLICIES: Final[Path] = _CACHE_DIR / "policies.json"
_IN_SKELETONS: Final[Path] = _CACHE_DIR / "skeletons.json"
_IN_DETAILS_MANIFEST: Final[Path] = _CACHE_DIR / "details" / "_manifest.json"
_IN_DETAILS_DIR: Final[Path] = _CACHE_DIR / "details"
_IN_ALT_TEXT: Final[Path] = _CACHE_DIR / "alt_text.json"
_IN_IMAGES_MANIFEST: Final[Path] = _CACHE_DIR / "images_manifest.json"
_IN_NAVIGATION: Final[Path] = _CACHE_DIR / "navigation.json"

_FIXED_TIMESTAMP: Final[str] = "2024-01-01T00:00:00Z"
"""Deterministic timestamp stamped onto every assembled record.

Spec §5.3 does not constrain the timestamps; a fixed value keeps the
assembled bytes byte-deterministic across re-runs without leaking any
real-world clock state.
"""

_ID_HEX_CHARS: Final[int] = 12
"""Number of leading hex digits of ``sha256(scope + handle)`` used as a numeric id.

48 bits comfortably fits in any 64-bit int while staying well above the
~200-product collision floor (birthday bound ≈ 17M before a collision is
likely).
"""

_FIELD_PATH_TO_STEP: Final[dict[str, str]] = {
    "store": _UPSTREAM_STORE,
    "products": _UPSTREAM_DETAILS,
    "collections": _UPSTREAM_COLLECTIONS,
    "pages": _UPSTREAM_PAGES,
    "policies": _UPSTREAM_POLICIES,
    "navigation": _UPSTREAM_NAVIGATION,
}
"""Top-level field path → upstream step that owns those bytes.

Used by :func:`_step_for_field_path` to decide which upstream record to
rewind on a brand-leak hit. ``products[*]`` falls through to
``synth_product_details`` because :func:`synth_product_skeletons`
already runs the same brand-leak rule on its own titles (spec §5.6) —
a leak that survives both stages must come from the detail-fanout
step's ``description_html`` / ``product_type`` / ``tags`` output.
"""


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class BrandLeakError(StageSynthError):
    """Raised when the allowlist scanner finds a non-allowlisted brand-shaped token.

    Carries the offending field path, the leaked token, and the upstream
    step id whose state was rewound so the caller (or a future
    ``--from`` invocation) can re-synth the right stage.

    Attributes:
        field_path: JSON-pointer-style path inside the assembled
            payload (e.g. ``"products[12].description_html"``).
        token: The non-allowlisted brand-shaped token that was hit.
        upstream_step_id: Step id whose recorded fingerprint was reset
            so the next pipeline run regenerates the offending stage.
    """

    def __init__(
        self,
        *,
        field_path: str,
        token: str,
        upstream_step_id: str,
    ) -> None:
        super().__init__(
            f"{_STEP_ID}: brand leak {token!r} at {field_path}; "
            f"rewound upstream {upstream_step_id!r} for re-synthesis",
        )
        self.field_path: str = field_path
        self.token: str = token
        self.upstream_step_id: str = upstream_step_id


# --------------------------------------------------------------------------- #
# Public assembly function (no I/O)
# --------------------------------------------------------------------------- #


def assemble_records(
    *,
    identity: dict[str, Any],
    store_payload: dict[str, Any],
    collection_drafts: list[CollectionDraft],
    pages_payload: list[dict[str, Any]],
    policies_payload: list[dict[str, Any]],
    skeletons: list[ProductSkeleton],
    details_by_handle: dict[str, ProductDetail],
    alt_text_by_handle: dict[str, list[str]],
    image_manifest: dict[str, Any],
    navigation_payload: dict[str, Any],
) -> AssembledData:
    """Combine every upstream payload into the final pydantic-validated records.

    Pure function — no I/O, no scrub. The caller (the step's ``run``)
    is responsible for reading the cached files, running
    :func:`scan_for_brand_leaks` against the result, and persisting
    the bytes.

    Args:
        identity: Decoded ``identity.json``.
        store_payload: Decoded ``.shop_gen/stage_cache/store.json``.
        collection_drafts: Validated :class:`CollectionDraft` records
            from the cached collections payload.
        pages_payload: Decoded ``.shop_gen/stage_cache/pages.json``
            (list of page records).
        policies_payload: Decoded ``.shop_gen/stage_cache/policies.json``
            (list of policy records).
        skeletons: Validated :class:`ProductSkeleton` records.
        details_by_handle: ``{handle: ProductDetail}`` flattened from
            the per-collection details cache.
        alt_text_by_handle: ``{handle: [alt_1, ...]}`` from
            ``alt_text.json``.
        image_manifest: Decoded
            ``.shop_gen/stage_cache/images_manifest.json``.
        navigation_payload: Decoded
            ``.shop_gen/stage_cache/navigation.json``.

    Returns:
        :class:`AssembledData` carrying every validated record (the
        caller serialises whichever pieces it needs).

    Raises:
        StageSynthError: A skeleton has no matching detail entry, an
            image manifest entry references an unknown product handle,
            or a pydantic validation fails.
    """
    store = _assemble_store(identity=identity, store_payload=store_payload)
    products = _assemble_products(
        skeletons=skeletons,
        details_by_handle=details_by_handle,
        alt_text_by_handle=alt_text_by_handle,
        image_manifest=image_manifest,
    )
    collections = _assemble_collections(
        drafts=collection_drafts,
        skeletons=skeletons,
    )
    pages = _validate_pages(pages_payload)
    policies = _validate_policies(policies_payload)
    navigation = _validate_navigation(navigation_payload)
    return AssembledData(
        store=store,
        products=products,
        collections=collections,
        pages=pages,
        policies=policies,
        navigation=navigation,
    )


class AssembledData:
    """Bundle of validated final records ready for serialisation.

    Attributes:
        store: Validated :class:`Store` for ``data/store.json``.
        products: Validated :class:`Product` list for ``data/products.json``.
        collections: Validated :class:`Collection` list for
            ``data/collections.json``.
        pages: Validated :class:`Page` list for ``data/pages.json``.
        policies: Validated :class:`Policy` list for ``data/policies.json``.
        navigation: Validated :class:`Navigation` for
            ``data/navigation.json``.
    """

    __slots__ = ("collections", "navigation", "pages", "policies", "products", "store")

    def __init__(
        self,
        *,
        store: Store,
        products: list[Product],
        collections: list[Collection],
        pages: list[Page],
        policies: list[Policy],
        navigation: Navigation,
    ) -> None:
        self.store: Store = store
        self.products: list[Product] = products
        self.collections: list[Collection] = collections
        self.pages: list[Page] = pages
        self.policies: list[Policy] = policies
        self.navigation: Navigation = navigation


def scan_for_brand_leaks(
    data: AssembledData,
    *,
    allowlist: Allowlist | None = None,
) -> tuple[str, Hit] | None:
    """Walk every string field of ``data`` and return the first brand leak.

    Args:
        data: Bundle returned by :func:`assemble_records`.
        allowlist: Optional pre-loaded :class:`Allowlist`. Defaults to
            the in-repo ``fake_brands.json`` (cached after first use).

    Returns:
        ``(field_path, hit)`` for the first non-allowlisted
        brand-shaped token encountered (in deterministic
        depth-first JSON order), or ``None`` when the dataset is clean.
    """
    target = allowlist if allowlist is not None else load_allowlist()
    serialised: dict[str, Any] = {
        "store": data.store.model_dump(mode="json"),
        "products": [p.model_dump(mode="json") for p in data.products],
        "collections": [c.model_dump(mode="json") for c in data.collections],
        "pages": [p.model_dump(mode="json") for p in data.pages],
        "policies": [p.model_dump(mode="json") for p in data.policies],
        "navigation": data.navigation.model_dump(mode="json"),
    }
    return _walk_strings(serialised, allowlist=target)


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class AssembleDataStep:
    """Phase 2 ``assemble_data`` step (spec §5.3 + §5.6).

    Reads every cached upstream payload, joins them into the final
    pydantic-validated records, scans for brand leaks, and emits the
    six published ``data/*.json`` files.

    Attributes:
        id: Step id (``assemble_data``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` per upstream Phase 2 step.
        outputs: The six ``data/*.json`` paths.
        depends_on: Same upstream ids as :attr:`inputs`.
        version: Bumped when the assembly behaviour changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to every upstream Phase 2 producer."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=sid) for sid in _UPSTREAM_IDS]
        self.outputs: list[Path] = list(_OUT_FILES)
        self.depends_on: list[str] = list(_UPSTREAM_IDS)
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Assemble the final ``data/*.json`` files.

        The assemble-time brand-leak scrub is currently disabled (see
        the module docstring and spec §5.6 "Current status"); brand
        safety is enforced at build time by the ``no_brand_leak``
        verifier (§5.5.3) over ``hydrogen/app/**``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is unused — the step
                is fully deterministic.

        Raises:
            FileNotFoundError: Any upstream cached file is missing.
            StageSynthError: A cached file is malformed or a skeleton
                has no matching detail / image entry.
        """
        identity = _load_json_object(ctx.out_dir / _IN_IDENTITY, label="identity.json")
        store_payload = _load_json_object(ctx.out_dir / _IN_STORE, label="store cache")
        collection_drafts = _load_collection_drafts(ctx.out_dir / _IN_COLLECTIONS)
        pages_payload = _load_json_array(ctx.out_dir / _IN_PAGES, label="pages cache")
        policies_payload = _load_json_array(ctx.out_dir / _IN_POLICIES, label="policies cache")
        skeletons = _load_skeletons(ctx.out_dir / _IN_SKELETONS)
        details_by_handle = _load_details_by_handle(
            manifest_path=ctx.out_dir / _IN_DETAILS_MANIFEST,
            details_dir=ctx.out_dir / _IN_DETAILS_DIR,
        )
        alt_text_by_handle = _load_alt_text(ctx.out_dir / _IN_ALT_TEXT)
        image_manifest = _load_json_object(
            ctx.out_dir / _IN_IMAGES_MANIFEST,
            label="images manifest",
        )
        navigation_payload = _load_json_object(
            ctx.out_dir / _IN_NAVIGATION,
            label="navigation cache",
        )

        data = assemble_records(
            identity=identity,
            store_payload=store_payload,
            collection_drafts=collection_drafts,
            pages_payload=pages_payload,
            policies_payload=policies_payload,
            skeletons=skeletons,
            details_by_handle=details_by_handle,
            alt_text_by_handle=alt_text_by_handle,
            image_manifest=image_manifest,
            navigation_payload=navigation_payload,
        )
        # Brand-leak scrub disabled — see module docstring + spec §5.6.

        _write_outputs(ctx.out_dir, data)


# --------------------------------------------------------------------------- #
# Assembly internals
# --------------------------------------------------------------------------- #


def _assemble_store(*, identity: dict[str, Any], store_payload: dict[str, Any]) -> Store:
    """Apply the deterministic ``shop_id`` and re-validate the cached store payload."""
    name = store_payload.get("name") or identity.get("name")
    if not isinstance(name, str) or not name:
        raise StageSynthError(
            f"{_STEP_ID}: cannot assign shop_id; store/identity missing 'name'",
        )
    payload = dict(store_payload)
    payload["shop_id"] = _numeric_id("store", name)
    try:
        return Store.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: assembled store failed schema validation: {exc}",
        ) from exc


def _assemble_products(
    *,
    skeletons: list[ProductSkeleton],
    details_by_handle: dict[str, ProductDetail],
    alt_text_by_handle: dict[str, list[str]],
    image_manifest: dict[str, Any],
) -> list[Product]:
    """Join skeletons + details + alt-text + images into validated :class:`Product`\\s."""
    images_by_handle = _images_by_handle_from_manifest(image_manifest)
    seen_handles: set[str] = set()
    products: list[Product] = []
    for position, skeleton in enumerate(skeletons, start=1):
        if skeleton.handle in seen_handles:
            # Cross-collection conflict resolution: suffix the dup
            # handle with its 1-indexed position so the shop_backend's
            # `Query.product(handle)` lookups remain unique. Spec §5.3
            # "cross-collection conflicts are resolved at assembly time".
            handle = f"{skeleton.handle}-{position}"
        else:
            handle = skeleton.handle
        seen_handles.add(handle)

        detail = details_by_handle.get(skeleton.handle)
        if detail is None:
            raise StageSynthError(
                f"{_STEP_ID}: skeleton {skeleton.handle!r} has no matching detail entry",
            )
        alts = alt_text_by_handle.get(skeleton.handle, [])
        manifest_images = images_by_handle.get(skeleton.handle, [])
        images = _build_product_images(
            handle=handle,
            manifest_entries=manifest_images,
            alts=alts,
        )

        try:
            product = Product(
                id=_numeric_id("product", handle),
                title=skeleton.title,
                handle=handle,
                description_html=detail.description_html,
                vendor=detail.vendor,
                product_type=detail.product_type,
                tags=list(detail.tags),
                published_at=_FIXED_TIMESTAMP,
                created_at=_FIXED_TIMESTAMP,
                updated_at=_FIXED_TIMESTAMP,
                options=list(detail.options),
                variants=_build_variants(handle=handle, detail=detail),
                images=images,
            )
        except ValidationError as exc:
            raise StageSynthError(
                f"{_STEP_ID}: assembled product {handle!r} failed schema validation: {exc}",
            ) from exc
        products.append(product)
    return products


def _build_variants(*, handle: str, detail: ProductDetail) -> list[ProductVariant]:
    """Promote the synth-time ``_VariantDraft`` rows to :class:`ProductVariant`\\s."""
    out: list[ProductVariant] = []
    for variant in detail.variants:
        try:
            out.append(
                ProductVariant(
                    id=_numeric_id("variant", f"{handle}|{variant.position}|{variant.title}"),
                    title=variant.title,
                    sku=variant.sku,
                    price=variant.price,
                    compare_at_price=variant.compare_at_price,
                    available=variant.available,
                    option1=variant.option1,
                    option2=variant.option2,
                    option3=variant.option3,
                    position=variant.position,
                    requires_shipping=variant.requires_shipping,
                ),
            )
        except ValidationError as exc:
            raise StageSynthError(
                f"{_STEP_ID}: assembled variant {variant.title!r} on product "
                f"{handle!r} failed schema validation: {exc}",
            ) from exc
    return out


def _build_product_images(
    *,
    handle: str,
    manifest_entries: list[dict[str, Any]],
    alts: list[str],
) -> list[ProductImage]:
    """Pair each image-manifest entry with the matching alt-text string."""
    images: list[ProductImage] = []
    for entry in manifest_entries:
        index = _require_int(entry, "index", label="image manifest entry")
        file_path = _require_str(entry, "file", label="image manifest entry")
        width = _require_int(entry, "width", label="image manifest entry")
        height = _require_int(entry, "height", label="image manifest entry")
        # ``file`` is the workspace-relative path (e.g. ``data/images/foo-0.svg``);
        # the dataset spec stores ``src`` as the leaf so ``shop_backend`` can
        # resolve it under its ``/images/`` route without leaking the workspace
        # layout (spec §8.1.4 + ``shop_backend`` ``rewriteImageUrl``).
        src = Path(file_path).name
        alt = alts[index] if 0 <= index < len(alts) else None
        try:
            images.append(
                ProductImage(
                    id=_numeric_id("image", f"{handle}|{index}"),
                    src=src,
                    alt=alt,
                    width=width,
                    height=height,
                    position=index + 1,
                ),
            )
        except ValidationError as exc:
            raise StageSynthError(
                f"{_STEP_ID}: assembled image for {handle!r}#{index} "
                f"failed schema validation: {exc}",
            ) from exc
    return images


def _assemble_collections(
    *,
    drafts: list[CollectionDraft],
    skeletons: list[ProductSkeleton],
) -> list[Collection]:
    """Promote :class:`CollectionDraft` rows to :class:`Collection` records.

    Populates ``product_handles`` from the skeleton list (preserving the
    skeleton emission order so ``"manual"`` sort order remains stable
    across re-runs).
    """
    handles_by_collection: dict[str, list[str]] = {d.handle: [] for d in drafts}
    for skeleton in skeletons:
        bucket = handles_by_collection.get(skeleton.collection_handle)
        if bucket is None:
            continue
        bucket.append(skeleton.handle)
    out: list[Collection] = []
    for draft in drafts:
        try:
            out.append(
                Collection(
                    id=_numeric_id("collection", draft.handle),
                    title=draft.title,
                    handle=draft.handle,
                    description=draft.description,
                    description_html=f"<p>{draft.description}</p>",
                    image=None,
                    published_at=_FIXED_TIMESTAMP,
                    updated_at=_FIXED_TIMESTAMP,
                    sort_order=draft.sort_order,
                    product_handles=list(handles_by_collection[draft.handle]),
                ),
            )
        except ValidationError as exc:
            raise StageSynthError(
                f"{_STEP_ID}: assembled collection {draft.handle!r} "
                f"failed schema validation: {exc}",
            ) from exc
    return out


def _validate_pages(payload: list[dict[str, Any]]) -> list[Page]:
    """Validate ``payload`` element-wise against :class:`Page`."""
    out: list[Page] = []
    for index, entry in enumerate(payload):
        try:
            out.append(Page.model_validate(entry))
        except ValidationError as exc:
            raise StageSynthError(
                f"{_STEP_ID}: pages[{index}] failed schema validation: {exc}",
            ) from exc
    return out


def _validate_policies(payload: list[dict[str, Any]]) -> list[Policy]:
    """Validate ``payload`` element-wise against :class:`Policy`."""
    out: list[Policy] = []
    for index, entry in enumerate(payload):
        try:
            out.append(Policy.model_validate(entry))
        except ValidationError as exc:
            raise StageSynthError(
                f"{_STEP_ID}: policies[{index}] failed schema validation: {exc}",
            ) from exc
    return out


def _validate_navigation(payload: dict[str, Any]) -> Navigation:
    """Re-validate the cached navigation payload against :class:`Navigation`."""
    try:
        return Navigation.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: navigation cache failed Navigation schema validation: {exc}",
        ) from exc


def _images_by_handle_from_manifest(
    manifest: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Group ``images_manifest.json`` entries by product handle.

    Each bucket is sorted by image ``index`` so ``position`` ends up
    1-indexed and stable across re-runs regardless of the manifest's
    on-disk ordering.
    """
    entries_raw = manifest.get("entries")
    if not isinstance(entries_raw, list):
        raise StageSynthError(
            f"{_STEP_ID}: images manifest missing 'entries' array",
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in cast("list[Any]", entries_raw):
        if not isinstance(raw, dict):
            raise StageSynthError(
                f"{_STEP_ID}: images manifest entry must be an object",
            )
        entry = cast("dict[str, Any]", raw)
        handle = _require_str(entry, "handle", label="image manifest entry")
        grouped.setdefault(handle, []).append(entry)
    for bucket in grouped.values():
        bucket.sort(key=lambda e: int(e["index"]))
    return grouped


# --------------------------------------------------------------------------- #
# Brand-leak scrub
# --------------------------------------------------------------------------- #


def _walk_strings(
    payload: Any,
    *,
    allowlist: Allowlist,
    path: str = "",
) -> tuple[str, Hit] | None:
    """Depth-first walk over ``payload`` returning the first :class:`Hit`."""
    if isinstance(payload, str):
        hits = scan(payload, allowlist=allowlist)
        if hits:
            return path, hits[0]
        return None
    if isinstance(payload, list):
        items = cast("list[Any]", payload)
        for index, item in enumerate(items):
            child = _walk_strings(
                item,
                allowlist=allowlist,
                path=f"{path}[{index}]",
            )
            if child is not None:
                return child
        return None
    if isinstance(payload, dict):
        record = cast("dict[str, Any]", payload)
        for key in sorted(record.keys()):
            child_path = f"{path}.{key}" if path else key
            child = _walk_strings(
                record[key],
                allowlist=allowlist,
                path=child_path,
            )
            if child is not None:
                return child
    return None


def _step_for_field_path(field_path: str) -> str:  # pyright: ignore[reportUnusedFunction]
    """Map a field path onto the upstream step that authored those bytes.

    Falls back to ``synth_product_details`` (the most common synthesis
    surface) when the prefix is unknown so the scanner still rewinds
    *something* useful rather than failing silently.

    Currently no in-module caller — the assemble-time scrub is disabled
    in v0.1.x (spec §5.6 "Current status"). Kept available so a future
    re-enable does not need to re-derive the field-path → upstream-step
    mapping; covered by ``test_step_for_field_path_*`` in
    ``test_assemble.py``.
    """
    head = field_path.split(".", 1)[0].split("[", 1)[0]
    return _FIELD_PATH_TO_STEP.get(head, _UPSTREAM_DETAILS)


# --------------------------------------------------------------------------- #
# Cache loaders
# --------------------------------------------------------------------------- #


def _write_outputs(out_dir: Path, data: AssembledData) -> None:
    """Serialise the assembled records to ``<out_dir>/data/*.json``."""
    data_dir = out_dir / _DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    store_payload = data.store.model_dump(mode="json")
    # ``Store.dataset_version`` is documented as absent in v0.1 datasets
    # (schema.py); pydantic serialises ``None`` as ``null`` which the
    # ``shop_backend`` loader rejects (it treats the field as
    # ``string | undefined``, not nullable). Drop the key when unset so
    # the on-disk JSON matches the cross-package contract.
    if store_payload.get("dataset_version") is None:
        store_payload.pop("dataset_version", None)
    _write_json(out_dir / _OUT_STORE, store_payload)
    _write_json(
        out_dir / _OUT_PRODUCTS,
        [p.model_dump(mode="json") for p in data.products],
    )
    _write_json(
        out_dir / _OUT_COLLECTIONS,
        [c.model_dump(mode="json") for c in data.collections],
    )
    _write_json(
        out_dir / _OUT_PAGES,
        [p.model_dump(mode="json") for p in data.pages],
    )
    _write_json(
        out_dir / _OUT_POLICIES,
        [p.model_dump(mode="json") for p in data.policies],
    )
    _write_json(out_dir / _OUT_NAVIGATION, data.navigation.model_dump(mode="json"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found at {path}")
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(f"{label} at {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise StageSynthError(
            f"{label} at {path} must be a JSON object, got {type(raw).__name__}",
        )
    return cast("dict[str, Any]", raw)


def _load_json_array(path: Path, *, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found at {path}")
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(f"{label} at {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise StageSynthError(
            f"{label} at {path} must be a JSON array, got {type(raw).__name__}",
        )
    entries = cast("list[Any]", raw)
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise StageSynthError(
                f"{label} at {path} entry {index} must be a JSON object",
            )
        out.append(cast("dict[str, Any]", entry))
    return out


def _load_collection_drafts(path: Path) -> list[CollectionDraft]:
    payload = _load_json_array(path, label="collections cache")
    try:
        return [CollectionDraft.model_validate(entry) for entry in payload]
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: cached collections at {path} "
            f"failed CollectionDraft schema validation: {exc}",
        ) from exc


def _load_skeletons(path: Path) -> list[ProductSkeleton]:
    payload = _load_json_array(path, label="skeletons cache")
    try:
        return [ProductSkeleton.model_validate(entry) for entry in payload]
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: cached skeletons at {path} "
            f"failed ProductSkeleton schema validation: {exc}",
        ) from exc


def _load_details_by_handle(
    *,
    manifest_path: Path,
    details_dir: Path,
) -> dict[str, ProductDetail]:
    """Flatten the per-collection ``details/<handle>.json`` files into ``{handle: detail}``.

    Mirrors the loader in :mod:`shop_gen.data_synth.images`; duplicated
    because the surgical-changes rule keeps cross-module helpers
    out-of-scope for this task.
    """
    manifest = _load_json_object(manifest_path, label="details manifest")
    entries_raw = manifest.get("collections")
    if not isinstance(entries_raw, list):
        raise StageSynthError(
            f"{_STEP_ID}: details manifest at {manifest_path} missing 'collections' array",
        )
    out: dict[str, ProductDetail] = {}
    for entry_raw in cast("list[Any]", entries_raw):
        if not isinstance(entry_raw, dict):
            raise StageSynthError(
                f"{_STEP_ID}: details manifest entry must be an object",
            )
        entry = cast("dict[str, Any]", entry_raw)
        file_name = _require_str(entry, "file", label="details manifest entry")
        details_path = details_dir / file_name
        if not details_path.exists():
            raise FileNotFoundError(
                f"cached details file not found at {details_path}",
            )
        try:
            payload: Any = json.loads(details_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StageSynthError(
                f"cached details at {details_path} is not valid JSON: {exc}",
            ) from exc
        if not isinstance(payload, list):
            raise StageSynthError(
                f"cached details at {details_path} must be a JSON array, "
                f"got {type(payload).__name__}",
            )
        try:
            for item in cast("list[Any]", payload):
                detail = ProductDetail.model_validate(item)
                out[detail.handle] = detail
        except ValidationError as exc:
            raise StageSynthError(
                f"cached details at {details_path} failed ProductDetail schema validation: {exc}",
            ) from exc
    return out


def _load_alt_text(path: Path) -> dict[str, list[str]]:
    payload = _load_json_object(path, label="alt-text cache")
    out: dict[str, list[str]] = {}
    for handle, alts in payload.items():
        if not isinstance(alts, list):
            raise StageSynthError(
                f"{_STEP_ID}: alt-text cache entry for {handle!r} must be a list",
            )
        items = cast("list[Any]", alts)
        for index, alt in enumerate(items):
            if not isinstance(alt, str):
                raise StageSynthError(
                    f"{_STEP_ID}: alt-text cache entry {handle!r}[{index}] must be a string",
                )
        out[handle] = [cast("str", alt) for alt in items]
    return out


def _require_str(record: dict[str, Any], key: str, *, label: str) -> str:
    value: Any = record.get(key)
    if not isinstance(value, str) or not value:
        raise StageSynthError(
            f"{_STEP_ID}: {label} missing non-empty string {key!r}",
        )
    return value


def _require_int(record: dict[str, Any], key: str, *, label: str) -> int:
    value: Any = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StageSynthError(
            f"{_STEP_ID}: {label} missing integer {key!r}",
        )
    return value


def _numeric_id(scope: str, key: str) -> int:
    """Return a deterministic non-negative numeric id for ``(scope, key)``.

    Hashes ``scope + "\\0" + key`` with sha256 and takes the leading
    :data:`_ID_HEX_CHARS` hex digits as a base-16 integer. The scope
    prefix prevents accidental collisions across record types (e.g. a
    collection and a product sharing a handle).
    """
    digest = hashlib.sha256(f"{scope}\0{key}".encode()).hexdigest()
    return int(digest[:_ID_HEX_CHARS], 16)


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #


__all__ = [
    "AssembleDataStep",
    "AssembledData",
    "BrandLeakError",
    "assemble_records",
    "scan_for_brand_leaks",
]
