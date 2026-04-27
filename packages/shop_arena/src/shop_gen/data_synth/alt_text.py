"""``synth_alt_text`` — Phase 2 alt-text synthesis (spec §5.3).

Per-collection LLM-call step that authors ``images_per_product`` short,
plain-descriptive alt-text strings for every product in the catalog.
The step fans out one completion per collection in parallel
(≤ 5 concurrent), validates each response against the closed
:class:`AltTextPayload` schema, asserts coverage and length bounds, and
caches the merged ``{handle: list[str]}`` mapping under
``<out_dir>/.shop_gen/stage_cache/alt_text.json``. Downstream consumers
are :func:`gen_images` (T3.10) and :func:`assemble_data` (T3.11), which
pairs each alt-text string with the matching ``ProductImage.alt``
field on the final ``products.json``.

Step contract (spec §5.7.1):

* ``id``: ``synth_alt_text``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_gen.steps.base.StepInput` referencing
  ``synth_product_details``. The cascade through that step already
  covers the cached skeletons, collections, and the identity payload.
* ``outputs``: ``.shop_gen/stage_cache/alt_text.json``.
* ``depends_on``: ``[synth_product_details]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Final, cast

from pydantic import RootModel, ValidationError

from harness.runtimes import LLMCompleter
from shop_gen.data_synth._synth_helpers import StageSynthError, parse_json_object
from shop_gen.data_synth.collections import CollectionDraft
from shop_gen.data_synth.details import ProductDetail
from shop_gen.data_synth.prompts import load_synth_alt_text_template
from shop_gen.data_synth.skeletons import ProductSkeleton
from shop_gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_alt_text"
_UPSTREAM_ID: Final[str] = "synth_product_details"
_STEP_VERSION: Final[int] = 1

_OUT_ALT_TEXT: Final[Path] = Path(".shop_gen") / "stage_cache" / "alt_text.json"
_IN_DETAILS_MANIFEST: Final[Path] = Path(".shop_gen") / "stage_cache" / "details" / "_manifest.json"
_IN_DETAILS_DIR: Final[Path] = Path(".shop_gen") / "stage_cache" / "details"
_IN_SKELETONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "skeletons.json"
_IN_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"

_LLM_TIMEOUT_S: Final[float] = 120.0
"""Per-collection budget; one LLM call per collection."""

_MAX_WORKERS: Final[int] = 5
"""Parallel ceiling for per-collection LLM calls (spec §5.3 "≤ 5 concurrent")."""

_MIN_ALT_CHARS: Final[int] = 10
"""Lower bound on each alt-text string. Below this most screen readers
choke on truncated phrases (spec §5.3 "alt-text strings")."""

_MAX_ALT_CHARS: Final[int] = 200
"""Upper bound on each alt-text string. Above this most CMS validators
reject the field (Shopify's storefront alt-text limit is 512; we keep
a tighter budget so the prompt encourages concise descriptions)."""


# --------------------------------------------------------------------------- #
# Cached payload shape
# --------------------------------------------------------------------------- #


class AltTextPayload(RootModel[dict[str, list[str]]]):
    """``{handle: [alt, alt, ...]}`` mapping authored by ``synth_alt_text``.

    The terminal :func:`assemble_data` step (T3.11) reads this file and
    pairs each alt-text string with the matching
    :class:`~shop_gen.data_synth.schema.ProductImage` ``alt`` field on
    the final ``products.json``. The mapping is keyed by product
    ``handle`` so it remains stable across collection renames.
    """


# --------------------------------------------------------------------------- #
# Per-collection synthesis function
# --------------------------------------------------------------------------- #


def synth_alt_text_for_collection(
    *,
    collection: CollectionDraft,
    skeletons: list[ProductSkeleton],
    details: list[ProductDetail],
    images_per_product: int,
    completer: LLMCompleter,
) -> dict[str, list[str]]:
    """Synthesize alt-text strings for one collection's products.

    Issues exactly one LLM completion with the merged skeleton + detail
    payload for every product in the collection, parses the response
    into a JSON object, and validates it against
    :class:`AltTextPayload`. The function then enforces:

    * Coverage — every product handle in ``skeletons`` is a key of the
      response (no missing handles, no extra handles).
    * Cardinality — each value list has exactly ``images_per_product``
      strings.
    * Length bounds — every string's length is in
      ``[_MIN_ALT_CHARS, _MAX_ALT_CHARS]``.

    Args:
        collection: The :class:`CollectionDraft` whose products are
            being captioned.
        skeletons: Skeletons assigned to ``collection``. Defines the
            handle set the response must cover.
        details: Product details assigned to ``collection`` (may be a
            subset of ``skeletons`` if any details were dropped by
            :func:`synth_product_details`). Used to enrich the prompt.
        images_per_product: Number of alt-text strings authored per
            product (mirrors :attr:`ShopGenConfig.catalog.images_per_product`).
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).

    Returns:
        ``{handle: [alt_1, alt_2, ...]}`` for every skeleton in
        ``skeletons``.

    Raises:
        StageSynthError: ``skeletons`` is empty, the response cannot be
            parsed, fails the schema, omits a handle, has an unexpected
            length, or includes an out-of-bounds string.
    """
    if not skeletons:
        raise StageSynthError(
            f"{_STEP_ID}: refusing to synthesize alt-text for empty skeleton list "
            f"(collection={collection.handle!r})",
        )
    if images_per_product <= 0:
        raise StageSynthError(
            f"{_STEP_ID}: images_per_product must be positive, got {images_per_product}",
        )
    raw = _run_completion(
        collection=collection,
        skeletons=skeletons,
        details=details,
        images_per_product=images_per_product,
        completer=completer,
    )
    payload = parse_json_object(raw, step_id=_STEP_ID)
    try:
        validated = AltTextPayload.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: response failed AltTextPayload schema validation: {exc}",
        ) from exc
    mapping = validated.root
    expected = {s.handle for s in skeletons}
    missing = expected - mapping.keys()
    if missing:
        raise StageSynthError(
            f"{_STEP_ID}: collection {collection.handle!r} response missing "
            f"alt-text for handles: {sorted(missing)}",
        )
    extra = mapping.keys() - expected
    if extra:
        raise StageSynthError(
            f"{_STEP_ID}: collection {collection.handle!r} response has "
            f"unexpected handles: {sorted(extra)}",
        )
    for handle, alts in mapping.items():
        if len(alts) != images_per_product:
            raise StageSynthError(
                f"{_STEP_ID}: handle {handle!r} has {len(alts)} alt-text "
                f"strings; expected exactly {images_per_product}",
            )
        for index, alt in enumerate(alts):
            if not _MIN_ALT_CHARS <= len(alt) <= _MAX_ALT_CHARS:
                raise StageSynthError(
                    f"{_STEP_ID}: handle {handle!r} alt[{index}] length "
                    f"{len(alt)} outside bounds "
                    f"[{_MIN_ALT_CHARS}, {_MAX_ALT_CHARS}]",
                )
    # Preserve the input skeleton order.
    return {s.handle: mapping[s.handle] for s in skeletons}


def _run_completion(
    *,
    collection: CollectionDraft,
    skeletons: list[ProductSkeleton],
    details: list[ProductDetail],
    images_per_product: int,
    completer: LLMCompleter,
) -> str:
    """Render the per-collection prompt and return the raw LLM response."""
    products = _merge_skeletons_with_details(skeletons=skeletons, details=details)
    prompt = load_synth_alt_text_template().format(
        collection=json.dumps(collection.model_dump(mode="json"), indent=2, sort_keys=True),
        products=json.dumps(products, indent=2, sort_keys=True),
        images_per_product=images_per_product,
        min_chars=_MIN_ALT_CHARS,
        max_chars=_MAX_ALT_CHARS,
    )
    return completer.complete(prompt, timeout=_LLM_TIMEOUT_S)


def _merge_skeletons_with_details(
    *,
    skeletons: list[ProductSkeleton],
    details: list[ProductDetail],
) -> list[dict[str, Any]]:
    """Join skeletons with their matching details for prompt rendering.

    Skeletons without a matching detail still appear in the output (the
    detail step may have dropped them); they carry the skeleton fields
    only and the LLM is still asked to caption them from title alone.
    """
    detail_by_handle = {d.handle: d for d in details}
    merged: list[dict[str, Any]] = []
    for skeleton in skeletons:
        record: dict[str, Any] = {
            "handle": skeleton.handle,
            "title": skeleton.title,
            "price": skeleton.price,
        }
        detail = detail_by_handle.get(skeleton.handle)
        if detail is not None:
            record["product_type"] = detail.product_type
            record["vendor"] = detail.vendor
            record["tags"] = list(detail.tags)
        merged.append(record)
    return merged


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class SynthAltTextStep:
    """Phase 2 ``synth_alt_text`` step (spec §5.3).

    Reads the cached collections, skeletons, and per-collection details,
    fans out one LLM call per collection across a
    ``ThreadPoolExecutor`` (≤ 5 workers), validates each response, and
    writes the merged ``{handle: list[str]}`` mapping to
    ``.shop_gen/stage_cache/alt_text.json``.

    Attributes:
        id: Step id (``synth_alt_text``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` referencing
            ``synth_product_details``.
        outputs: ``.shop_gen/stage_cache/alt_text.json``.
        depends_on: ``[synth_product_details]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the ``synth_product_details`` upstream."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_UPSTREAM_ID)]
        self.outputs: list[Path] = [_OUT_ALT_TEXT]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``alt_text.json`` and cache it under ``.shop_gen/stage_cache/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step issues one LLM call per collection.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: Any of the upstream cached files
                (``collections.json``, ``skeletons.json``,
                ``details/_manifest.json``) is missing.
            StageSynthError: An LLM response is unparseable, a
                collection misses a handle, or any string fails the
                length bounds.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_alt_text requires a runtime with LLMCompleter; got None",
            )
        collections_path = ctx.out_dir / _IN_COLLECTIONS
        if not collections_path.exists():
            raise FileNotFoundError(
                f"cached collections not found at {collections_path}; run synth_collections first",
            )
        skeletons_path = ctx.out_dir / _IN_SKELETONS
        if not skeletons_path.exists():
            raise FileNotFoundError(
                f"cached skeletons not found at {skeletons_path}; "
                "run synth_product_skeletons first",
            )
        manifest_path = ctx.out_dir / _IN_DETAILS_MANIFEST
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"cached details manifest not found at {manifest_path}; "
                "run synth_product_details first",
            )

        collections = _load_collections(collections_path)
        skeletons = _load_skeletons(skeletons_path)
        details_by_collection = _load_details_by_collection(
            manifest_path=manifest_path,
            details_dir=ctx.out_dir / _IN_DETAILS_DIR,
        )
        skeletons_by_collection = _group_by_collection(skeletons, collections=collections)

        images_per_product = ctx.config.catalog.images_per_product

        results: dict[str, dict[str, list[str]]] = {}
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    synth_alt_text_for_collection,
                    collection=collection,
                    skeletons=skeletons_by_collection[collection.handle],
                    details=details_by_collection.get(collection.handle, []),
                    images_per_product=images_per_product,
                    completer=ctx.runtime,
                ): collection.handle
                for collection in collections
            }
            for future in as_completed(futures):
                handle = futures[future]
                # Re-raise the first exception so the runner records FAILED.
                results[handle] = future.result()

        # Merge per-collection mappings into one ``{handle: list[str]}``.
        # Iterate collections in their original order so the on-disk
        # JSON is deterministic across runs.
        merged: dict[str, list[str]] = {}
        for collection in collections:
            merged.update(results[collection.handle])

        out_path = ctx.out_dir / _OUT_ALT_TEXT
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(merged, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _load_collections(path: Path) -> list[CollectionDraft]:
    """Read the cached ``collections.json`` payload as ``list[CollectionDraft]``."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"cached collections at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, list):
        raise StageSynthError(
            f"cached collections at {path} must be a JSON array, got {type(raw).__name__}",
        )
    try:
        return [CollectionDraft.model_validate(entry) for entry in cast("list[Any]", raw)]
    except ValidationError as exc:
        raise StageSynthError(
            f"cached collections at {path} failed CollectionDraft schema validation: {exc}",
        ) from exc


def _load_skeletons(path: Path) -> list[ProductSkeleton]:
    """Read the cached ``skeletons.json`` payload as ``list[ProductSkeleton]``."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"cached skeletons at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, list):
        raise StageSynthError(
            f"cached skeletons at {path} must be a JSON array, got {type(raw).__name__}",
        )
    try:
        return [ProductSkeleton.model_validate(entry) for entry in cast("list[Any]", raw)]
    except ValidationError as exc:
        raise StageSynthError(
            f"cached skeletons at {path} failed ProductSkeleton schema validation: {exc}",
        ) from exc


def _load_details_by_collection(
    *,
    manifest_path: Path,
    details_dir: Path,
) -> dict[str, list[ProductDetail]]:
    """Read the per-collection ``details/<handle>.json`` files via the manifest."""
    try:
        manifest_raw: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"details manifest at {manifest_path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(manifest_raw, dict):
        raise StageSynthError(
            f"details manifest at {manifest_path} must be a JSON object, "
            f"got {type(manifest_raw).__name__}",
        )
    entries_raw = cast("dict[str, Any]", manifest_raw).get("collections")
    if not isinstance(entries_raw, list):
        raise StageSynthError(
            f"details manifest at {manifest_path} missing 'collections' array",
        )
    out: dict[str, list[ProductDetail]] = {}
    for entry in cast("list[Any]", entries_raw):
        if not isinstance(entry, dict):
            raise StageSynthError(
                f"details manifest at {manifest_path} entry must be an object",
            )
        entry_dict = cast("dict[str, Any]", entry)
        handle_raw = entry_dict.get("handle")
        file_raw = entry_dict.get("file")
        if not isinstance(handle_raw, str) or not isinstance(file_raw, str):
            raise StageSynthError(
                f"details manifest at {manifest_path} entry missing 'handle'/'file'",
            )
        details_path = details_dir / file_raw
        if not details_path.exists():
            raise FileNotFoundError(
                f"cached details for collection {handle_raw!r} not found at {details_path}",
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
            out[handle_raw] = [
                ProductDetail.model_validate(item) for item in cast("list[Any]", payload)
            ]
        except ValidationError as exc:
            raise StageSynthError(
                f"cached details at {details_path} failed ProductDetail schema validation: {exc}",
            ) from exc
    return out


def _group_by_collection(
    skeletons: list[ProductSkeleton],
    *,
    collections: list[CollectionDraft],
) -> dict[str, list[ProductSkeleton]]:
    """Bucket skeletons by ``collection_handle``, preserving input order.

    Raises:
        StageSynthError: A skeleton references a collection handle that
            is not present in ``collections``.
    """
    known = {c.handle for c in collections}
    grouped: dict[str, list[ProductSkeleton]] = {c.handle: [] for c in collections}
    for skeleton in skeletons:
        if skeleton.collection_handle not in known:
            raise StageSynthError(
                f"{_STEP_ID}: skeleton {skeleton.handle!r} references unknown "
                f"collection_handle {skeleton.collection_handle!r}",
            )
        grouped[skeleton.collection_handle].append(skeleton)
    return grouped


__all__ = [
    "AltTextPayload",
    "SynthAltTextStep",
    "synth_alt_text_for_collection",
]
