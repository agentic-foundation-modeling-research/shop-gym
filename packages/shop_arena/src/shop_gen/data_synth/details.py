"""``synth_product_details`` — Phase 2 product-detail synthesis (spec §5.3).

Per-collection LLM-call step that fills in the catalog skeletons emitted by
:func:`synth_product_skeletons` with rich detail — variants, options,
``description_html``, ``vendor`` (drawn from the fake-brand allowlist), and
``tags``. The step issues one LLM completion per collection (parallel with
≤ 5 concurrent workers), pydantic-validates each returned detail at the
boundary, and re-prompts a single time on any rejection. Drops that survive
both attempts contribute to a global rejection counter; if more than 5% of
the catalog's skeletons are dropped the step fails (spec §5.3 "Schema
strictness vs. LLM drift").

The validated details are cached as JSON arrays under
``<out_dir>/.shop_gen/stage_cache/details/<collection_handle>.json`` and a
sibling manifest at ``.shop_gen/stage_cache/details/_manifest.json``
records which collection files were written so the runner can detect
missing outputs without enumerating the collection list itself.

Step contract (spec §5.7.1):

* ``id``: ``synth_product_details``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_gen.steps.base.StepInput` referencing
  ``synth_product_skeletons``. The cascade through that step already
  covers ``synth_collections`` and the upstream identity / manual files.
* ``outputs``: ``.shop_gen/stage_cache/details/_manifest.json``.
* ``depends_on``: ``[synth_product_skeletons]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from harness.runtimes import LLMCompleter
from shop_gen.brands.allowlist import Allowlist, load_allowlist
from shop_gen.data_synth._synth_helpers import StageSynthError, parse_json_array
from shop_gen.data_synth.collections import CollectionDraft
from shop_gen.data_synth.prompts import load_synth_product_details_template
from shop_gen.data_synth.schema import ProductOption
from shop_gen.data_synth.skeletons import ProductSkeleton
from shop_gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_product_details"
_UPSTREAM_ID: Final[str] = "synth_product_skeletons"
_STEP_VERSION: Final[int] = 1

_OUT_DETAILS_DIR: Final[Path] = Path(".shop_gen") / "stage_cache" / "details"
_OUT_MANIFEST: Final[Path] = _OUT_DETAILS_DIR / "_manifest.json"
_IN_SKELETONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "skeletons.json"
_IN_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"
_IN_IDENTITY: Final[Path] = Path("identity.json")

_LLM_TIMEOUT_S: Final[float] = 120.0
"""Per-collection budget; one LLM call per collection."""

_MAX_WORKERS: Final[int] = 5
"""Parallel ceiling for per-collection LLM calls (spec §5.3 "≤ 5 concurrent")."""

_MAX_REJECTION_RATE: Final[float] = 0.05
"""Global rejection rate above which the step fails (spec §5.3 ">5% rejection rate")."""

_MAX_RETRIES: Final[int] = 1
"""One re-prompt allowed per rejected row (spec §5.3)."""

_TEXT_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Za-z]+")
"""Same capitalized-run regex the §5.6 scanner uses."""


# --------------------------------------------------------------------------- #
# Cached payload shape (synthesis-time, not the final Product schema)
# --------------------------------------------------------------------------- #


class _VariantDraft(BaseModel):
    """``ProductVariant`` minus ``id`` (assigned by :func:`assemble_data`).

    Mirrors :class:`~shop_gen.data_synth.schema.ProductVariant` so the LLM
    output can be validated with the same field types without having to
    invent a placeholder integer id at synthesis time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

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


class ProductDetail(BaseModel):
    """One product's detail payload as emitted by ``synth_product_details``.

    Carries the fields the per-collection LLM call authors. The terminal
    :func:`assemble_data` step (T3.11) joins this with the matching
    :class:`~shop_gen.data_synth.skeletons.ProductSkeleton` (title,
    handle, price hint, collection assignment) and the timestamps to
    produce the final :class:`~shop_gen.data_synth.schema.Product`.

    Attributes:
        handle: URL-safe slug. Must equal the matching skeleton's
            ``handle`` exactly so :func:`assemble_data` can pair them.
        description_html: HTML description (``<p>`` / ``<ul>`` / ``<li>``
            only). Plain-descriptive — must not contain any allowlisted
            brand token; enforced post-validation.
        vendor: Vendor name. Must match an allowlist token exactly
            (case-sensitive); enforced post-validation.
        product_type: Plain-descriptive product-type classification
            (e.g. ``"jacket"``). Must not contain any allowlisted brand
            token; enforced post-validation.
        tags: Free-form tags. Must not contain any allowlisted brand
            token; enforced post-validation.
        options: Option groups (1-3 entries). Mirrors
            :class:`~shop_gen.data_synth.schema.ProductOption`.
        variants: Purchasable variants. Mirrors
            :class:`~shop_gen.data_synth.schema.ProductVariant` minus the
            ``id`` field, which :func:`assemble_data` assigns.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle: str
    description_html: str
    vendor: str
    product_type: str
    tags: list[str]
    options: list[ProductOption]
    variants: list[_VariantDraft]


# --------------------------------------------------------------------------- #
# Per-collection synthesis function
# --------------------------------------------------------------------------- #


def synth_product_details_for_collection(
    *,
    identity: dict[str, Any],
    collection: CollectionDraft,
    skeletons: list[ProductSkeleton],
    completer: LLMCompleter,
    allowlist: Allowlist | None = None,
) -> tuple[list[ProductDetail], int]:
    """Synthesize details for one collection's product skeletons.

    Issues one LLM completion with all of the collection's skeletons, parses
    the response into a JSON array, validates each entry against
    :class:`ProductDetail`, and re-prompts once with the rejected handles.
    Details whose ``vendor`` / ``description_html`` / ``product_type`` / any
    ``tags`` element fails the allowlist post-pass are also collected as
    rejects. After the retry, surviving rejects are dropped and the count
    is reported back to the caller for the global ``>5%`` accounting.

    Args:
        identity: Decoded ``identity.json`` document (read-only context
            for the prompt).
        collection: The :class:`CollectionDraft` whose skeletons are
            being filled in.
        skeletons: The skeletons assigned to ``collection``.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).
        allowlist: Optional pre-loaded :class:`Allowlist`. Defaults to the
            in-repo ``fake_brands.json`` (cached after first use).

    Returns:
        Tuple ``(details, dropped_count)``: ``details`` is the validated
        list (length ≤ ``len(skeletons)``); ``dropped_count`` is the
        number of skeletons that failed both attempts.

    Raises:
        StageSynthError: ``skeletons`` is empty, the LLM response cannot
            be parsed as a JSON array, or the response is empty after
            stripping fences.
    """
    if not skeletons:
        raise StageSynthError(
            f"{_STEP_ID}: refusing to synthesize details for empty skeleton list "
            f"(collection={collection.handle!r})",
        )
    target_allowlist = allowlist if allowlist is not None else load_allowlist()

    accepted: dict[str, ProductDetail] = {}
    pending = list(skeletons)
    for attempt in range(_MAX_RETRIES + 1):
        if not pending:
            break
        raw = _run_completion(
            identity=identity,
            collection=collection,
            skeletons=pending,
            completer=completer,
            allowlist=target_allowlist,
        )
        details = _parse_details_payload(raw, expected_handles=[s.handle for s in pending])
        next_pending: list[ProductSkeleton] = []
        for skeleton in pending:
            detail = details.get(skeleton.handle)
            if detail is None:
                next_pending.append(skeleton)
                continue
            try:
                _assert_no_allowlist_token_in_text_fields(detail, allowlist=target_allowlist)
                _assert_vendor_in_allowlist(detail, allowlist=target_allowlist)
                _assert_variants_match_options(detail)
            except StageSynthError:
                if attempt < _MAX_RETRIES:
                    next_pending.append(skeleton)
                    continue
                # Final attempt: drop silently; the caller aggregates.
                continue
            accepted[skeleton.handle] = detail
        pending = next_pending

    # Preserve the input skeleton order in the returned list.
    ordered: list[ProductDetail] = [accepted[s.handle] for s in skeletons if s.handle in accepted]
    dropped = len(skeletons) - len(ordered)
    return ordered, dropped


def _run_completion(
    *,
    identity: dict[str, Any],
    collection: CollectionDraft,
    skeletons: list[ProductSkeleton],
    completer: LLMCompleter,
    allowlist: Allowlist,
) -> str:
    """Render the per-collection prompt and return the raw LLM response."""
    prompt = load_synth_product_details_template().format(
        identity=json.dumps(identity, indent=2, sort_keys=True),
        collection=json.dumps(collection.model_dump(mode="json"), indent=2, sort_keys=True),
        skeletons=json.dumps(
            [s.model_dump(mode="json") for s in skeletons],
            indent=2,
            sort_keys=True,
        ),
        product_count=len(skeletons),
        allowlist=json.dumps(sorted(allowlist.brands)),
    )
    return completer.complete(prompt, timeout=_LLM_TIMEOUT_S)


def _parse_details_payload(
    raw: str,
    *,
    expected_handles: list[str],
) -> dict[str, ProductDetail]:
    """Parse the LLM response into ``{handle: ProductDetail}``.

    Schema-failing rows are silently dropped from the returned mapping;
    the caller treats them as rejects and re-prompts once. The function
    only raises when the whole response is unparseable (empty, not JSON,
    or not a top-level array) — those are step-fatal.
    """
    payload = parse_json_array(raw, step_id=_STEP_ID)
    if not payload:
        raise StageSynthError(f"{_STEP_ID}: LLM emitted an empty details array")
    expected = set(expected_handles)
    out: dict[str, ProductDetail] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        handle = cast("dict[str, Any]", entry).get("handle")
        if not isinstance(handle, str) or handle not in expected:
            continue
        try:
            detail = ProductDetail.model_validate(entry)
        except ValidationError:
            continue
        out[handle] = detail
    return out


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class SynthProductDetailsStep:
    """Phase 2 ``synth_product_details`` step (spec §5.3).

    Reads the cached ``CollectionDraft`` list, the cached ``ProductSkeleton``
    list, and ``identity.json``; fans out one LLM call per collection across
    a ``ThreadPoolExecutor`` (≤ 5 workers); writes one
    ``.shop_gen/stage_cache/details/<collection>.json`` per collection plus a
    ``_manifest.json`` sentinel. Fails when more than 5% of the catalog's
    skeletons fail validation across both attempts.

    Attributes:
        id: Step id (``synth_product_details``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` referencing
            ``synth_product_skeletons``.
        outputs: ``.shop_gen/stage_cache/details/_manifest.json``. The
            per-collection JSON files are siblings of the manifest;
            declaring only the manifest as the staleness sentinel keeps
            the step's :attr:`outputs` list independent of the
            collection set.
        depends_on: ``[synth_product_skeletons]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the ``synth_product_skeletons`` upstream."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_UPSTREAM_ID)]
        self.outputs: list[Path] = [_OUT_MANIFEST]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize the per-collection ``details/`` cache.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step issues one LLM call per collection.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: Any of the upstream cached files
                (``identity.json``, ``collections.json``,
                ``skeletons.json``) is missing.
            StageSynthError: An LLM response is unparseable, or the
                global rejection rate exceeds 5%.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_product_details requires a runtime with LLMCompleter; got None",
            )
        identity_path = ctx.out_dir / _IN_IDENTITY
        if not identity_path.exists():
            raise FileNotFoundError(
                f"identity.json not found at {identity_path}; run synth_identity first",
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

        identity = _load_json_object(identity_path, label="identity.json")
        collections = _load_collections(collections_path)
        skeletons = _load_skeletons(skeletons_path)
        skeletons_by_collection = _group_by_collection(skeletons, collections=collections)

        details_dir = ctx.out_dir / _OUT_DETAILS_DIR
        details_dir.mkdir(parents=True, exist_ok=True)

        total = len(skeletons)
        results: dict[str, tuple[list[ProductDetail], int]] = {}
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    synth_product_details_for_collection,
                    identity=identity,
                    collection=collection,
                    skeletons=skeletons_by_collection[collection.handle],
                    completer=ctx.runtime,
                ): collection.handle
                for collection in collections
            }
            for future in as_completed(futures):
                handle = futures[future]
                # Re-raise the first exception so the runner records FAILED.
                results[handle] = future.result()

        total_dropped = sum(dropped for _, dropped in results.values())
        if total > 0 and total_dropped / total > _MAX_REJECTION_RATE:
            raise StageSynthError(
                f"{_STEP_ID}: rejection rate {total_dropped}/{total} exceeds "
                f"{_MAX_REJECTION_RATE:.0%} budget",
            )

        manifest: dict[str, Any] = {"collections": []}
        for collection in collections:
            details, dropped = results[collection.handle]
            file_path = details_dir / f"{collection.handle}.json"
            file_path.write_text(
                json.dumps(
                    [d.model_dump(mode="json") for d in details],
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest["collections"].append(
                {
                    "handle": collection.handle,
                    "file": file_path.name,
                    "details_count": len(details),
                    "dropped_count": dropped,
                },
            )
        manifest["total_products"] = total
        manifest["total_dropped"] = total_dropped

        manifest_path = ctx.out_dir / _OUT_MANIFEST
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """Read ``path`` as a JSON object for prompt rendering."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"{label} at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise StageSynthError(
            f"{label} at {path} must be a JSON object, got {type(raw).__name__}",
        )
    return cast("dict[str, Any]", raw)


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


def _assert_vendor_in_allowlist(detail: ProductDetail, *, allowlist: Allowlist) -> None:
    """Reject details whose ``vendor`` is not an allowlisted brand."""
    if not allowlist.is_allowed(detail.vendor):
        raise StageSynthError(
            f"{_STEP_ID}: detail {detail.handle!r} vendor {detail.vendor!r} "
            f"is not in the fake-brand allowlist",
        )


def _assert_no_allowlist_token_in_text_fields(
    detail: ProductDetail,
    *,
    allowlist: Allowlist,
) -> None:
    """Reject brand-shaped tokens in any plain-descriptive text field.

    The ``vendor`` field is exempt — it carries the allowlist token by
    design — but ``description_html``, ``product_type``, and ``tags`` are
    plain-descriptive (spec §5.6) and must not contain any allowlisted
    brand token.
    """
    fields: Iterable[tuple[str, str]] = [
        ("description_html", detail.description_html),
        ("product_type", detail.product_type),
    ]
    for field_name, value in fields:
        for match in _TEXT_TOKEN_RE.finditer(value):
            token = match.group(0)
            if allowlist.is_allowed(token):
                raise StageSynthError(
                    f"{_STEP_ID}: detail {detail.handle!r} {field_name} "
                    f"contains allowlisted brand token {token!r}; "
                    "plain-descriptive fields must be brand-free",
                )
    for tag in detail.tags:
        for match in _TEXT_TOKEN_RE.finditer(tag):
            token = match.group(0)
            if allowlist.is_allowed(token):
                raise StageSynthError(
                    f"{_STEP_ID}: detail {detail.handle!r} tag "
                    f"contains allowlisted brand token {token!r}; "
                    "plain-descriptive fields must be brand-free",
                )


def _assert_variants_match_options(detail: ProductDetail) -> None:
    """Reject variants whose ``optionN`` value is not in the matching option group."""
    options = detail.options
    for variant in detail.variants:
        for index, option_value in enumerate(
            (variant.option1, variant.option2, variant.option3),
            start=1,
        ):
            if index <= len(options):
                allowed_values = options[index - 1].values
                if option_value is None or option_value not in allowed_values:
                    raise StageSynthError(
                        f"{_STEP_ID}: detail {detail.handle!r} variant "
                        f"{variant.title!r} option{index}={option_value!r} "
                        f"is not one of {sorted(allowed_values)!r}",
                    )
            elif option_value is not None:
                raise StageSynthError(
                    f"{_STEP_ID}: detail {detail.handle!r} variant "
                    f"{variant.title!r} sets option{index}={option_value!r} "
                    f"but the product has only {len(options)} option groups",
                )


# Variant draft is a pydantic forward-referenced field on ``ProductDetail``;
# expose the type only as part of the explicit public surface.
__all__ = [
    "ProductDetail",
    "SynthProductDetailsStep",
    "synth_product_details_for_collection",
]
