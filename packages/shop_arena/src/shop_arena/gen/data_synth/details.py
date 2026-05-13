"""``synth_product_details`` — Phase 2 product-detail synthesis (spec §5.3).

Per-collection LLM-call step that fills in the catalog skeletons emitted by
:func:`synth_product_skeletons` with rich detail — variants, options,
``description_html``, ``vendor`` (drawn from the fake-brand allowlist), and
``tags``. Collections run in parallel (≤ 5 concurrent workers); within a
collection the skeleton list is split into chunks of at most
:data:`_MAX_SKELETONS_PER_CALL` so each LLM completion's output stays well
below the model's effective output-token budget (spec §5.3 originally
specified one call per collection — see :data:`_MAX_SKELETONS_PER_CALL`
for the deviation rationale). Each chunk's response is
pydantic-validated at the boundary; both per-row validation rejects
and whole-response parse failures (e.g. truncated JSON) consume the
same one re-prompt budget. Drops that survive both attempts contribute
to a global rejection counter; if more than 5% of the catalog's
skeletons are dropped the step fails (spec §5.3 "Schema strictness vs.
LLM drift").

The validated details are cached as JSON arrays under
``<out_dir>/.shop_gen/stage_cache/details/<collection_handle>.json`` and a
sibling manifest at ``.shop_gen/stage_cache/details/_manifest.json``
records which collection files were written so the runner can detect
missing outputs without enumerating the collection list itself.

Step contract (spec §5.7.1):

* ``id``: ``synth_product_details``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_arena.gen.steps.base.StepInput` referencing
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
from shop_arena.gen.brands.allowlist import Allowlist, load_allowlist
from shop_arena.gen.data_synth._synth_helpers import StageSynthError, parse_json_array
from shop_arena.gen.data_synth.collections import CollectionDraft
from shop_arena.gen.data_synth.prompts import load_synth_product_details_template
from shop_arena.gen.data_synth.schema import ProductOption
from shop_arena.gen.data_synth.skeletons import ProductSkeleton
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_product_details"
_UPSTREAM_ID: Final[str] = "synth_product_skeletons"
_STEP_VERSION: Final[int] = 1

_OUT_DETAILS_DIR: Final[Path] = Path(".shop_gen") / "stage_cache" / "details"
_OUT_MANIFEST: Final[Path] = _OUT_DETAILS_DIR / "_manifest.json"
_IN_SKELETONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "skeletons.json"
_IN_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"
_IN_IDENTITY: Final[Path] = Path("identity.json")

_LLM_TIMEOUT_S: Final[float] = 360.0
"""Per-LLM-call wall-clock budget; multiple calls may run for one collection."""

_MAX_WORKERS: Final[int] = 5
"""Parallel ceiling for per-collection LLM calls (spec §5.3 "≤ 5 concurrent")."""

_MAX_REJECTION_RATE: Final[float] = 0.05
"""Global rejection rate above which the step fails (spec §5.3 ">5% rejection rate")."""

_MAX_RETRIES: Final[int] = 1
"""One re-prompt allowed per rejected row (spec §5.3)."""

_MAX_SKELETONS_PER_CALL: Final[int] = 10
"""Upper bound on skeletons sent in a single LLM call.

Spec §5.3 originally prescribed "one LLM call per collection". With the
v0.1 default of ``products_per_collection=20`` (see
``CatalogConfig.DEFAULT_PRODUCTS_PER_COLLECTION``) the per-collection
response routinely exceeds the model's effective output-token budget,
which surfaces as ``json.JSONDecodeError: Unterminated string`` and
fails the entire collection (>5% rejection ⇒ step failure). Splitting
the skeleton list into chunks of this size keeps each response well
within the budget while preserving the per-collection cache file shape
(one ``<collection>.json`` per collection, sum of chunk outputs).
Concurrency is unchanged: chunks within a collection run sequentially;
collections still run in parallel under :data:`_MAX_WORKERS`.
"""

_FAILED_RAW_DUMP_PREFIX: Final[str] = "_failed"
"""Filename prefix for raw LLM responses persisted on parse failure."""

_TEXT_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Za-z]+")
"""Same capitalized-run regex the §5.6 scanner uses."""


# --------------------------------------------------------------------------- #
# Cached payload shape (synthesis-time, not the final Product schema)
# --------------------------------------------------------------------------- #


class _VariantDraft(BaseModel):
    """``ProductVariant`` minus ``id`` (assigned by :func:`assemble_data`).

    Mirrors :class:`~shop_arena.gen.data_synth.schema.ProductVariant` so the LLM
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
    :class:`~shop_arena.gen.data_synth.skeletons.ProductSkeleton` (title,
    handle, price hint, collection assignment) and the timestamps to
    produce the final :class:`~shop_arena.gen.data_synth.schema.Product`.

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
            :class:`~shop_arena.gen.data_synth.schema.ProductOption`.
        variants: Purchasable variants. Mirrors
            :class:`~shop_arena.gen.data_synth.schema.ProductVariant` minus the
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
    debug_dir: Path | None = None,
) -> tuple[list[ProductDetail], int]:
    """Synthesize details for one collection's product skeletons.

    The skeleton list is partitioned into chunks of at most
    :data:`_MAX_SKELETONS_PER_CALL`; each chunk drives one LLM completion
    (plus up to :data:`_MAX_RETRIES` re-prompts for rows that fail
    pydantic / allowlist validation). Chunking is purely a per-call
    output-size guard — the per-collection cache file shape and the
    rejection accounting are both unchanged from the single-call
    contract documented in spec §5.3.

    Each chunk parses the response into a JSON array, validates each
    entry against :class:`ProductDetail`, and re-prompts once on
    failure. Two failure modes share the single re-prompt budget:
    per-row validation rejects (pydantic / allowlist) re-prompt with the
    rejected handles only; whole-response parse failures (e.g. truncated
    JSON) re-prompt with the same handle list. After the retry,
    surviving per-row rejects are dropped and counted toward the global
    ``>5%`` budget; an unrecovered whole-response parse failure raises
    :class:`StageSynthError` (the raw response is persisted to
    ``debug_dir`` first when set).

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
        debug_dir: When set, raw LLM responses for chunks whose JSON
            cannot be parsed are persisted under
            ``<debug_dir>/_failed_<collection>_chunk_<i>_attempt_<n>.txt``
            before the :class:`StageSynthError` propagates. Lets the
            caller inspect truncated / malformed responses without
            re-running the whole step. ``None`` (default) suppresses
            the dump.

    Returns:
        Tuple ``(details, dropped_count)``: ``details`` is the validated
        list (length ≤ ``len(skeletons)``); ``dropped_count`` is the
        number of skeletons that failed both attempts across all chunks.

    Raises:
        StageSynthError: ``skeletons`` is empty, or any chunk's LLM
            response cannot be parsed as a JSON array (after stripping
            fences). The raw response is persisted to ``debug_dir``
            first when that argument is set.
    """
    if not skeletons:
        raise StageSynthError(
            f"{_STEP_ID}: refusing to synthesize details for empty skeleton list "
            f"(collection={collection.handle!r})",
        )
    target_allowlist = allowlist if allowlist is not None else load_allowlist()

    accepted: dict[str, ProductDetail] = {}
    total_dropped = 0
    for chunk_index, chunk in enumerate(_iter_chunks(skeletons, _MAX_SKELETONS_PER_CALL)):
        chunk_accepted, chunk_dropped = _synth_chunk_with_retries(
            identity=identity,
            collection=collection,
            skeletons=chunk,
            completer=completer,
            allowlist=target_allowlist,
            chunk_index=chunk_index,
            debug_dir=debug_dir,
        )
        accepted.update(chunk_accepted)
        total_dropped += chunk_dropped

    # Preserve the input skeleton order in the returned list.
    ordered: list[ProductDetail] = [accepted[s.handle] for s in skeletons if s.handle in accepted]
    return ordered, total_dropped


def _iter_chunks(
    skeletons: list[ProductSkeleton],
    chunk_size: int,
    /,
) -> Iterable[list[ProductSkeleton]]:
    """Yield successive ``chunk_size``-sized slices of ``skeletons``."""
    for start in range(0, len(skeletons), chunk_size):
        yield skeletons[start : start + chunk_size]


def _synth_chunk_with_retries(
    *,
    identity: dict[str, Any],
    collection: CollectionDraft,
    skeletons: list[ProductSkeleton],
    completer: LLMCompleter,
    allowlist: Allowlist,
    chunk_index: int,
    debug_dir: Path | None,
) -> tuple[dict[str, ProductDetail], int]:
    """Synthesize one chunk's details with the per-row retry loop.

    Returns ``(accepted_by_handle, dropped_count)``. The accepted map is
    keyed by ``ProductSkeleton.handle`` so the caller can merge across
    chunks without re-ordering.

    Both per-row validation failures and whole-response parse failures
    consume the same one re-prompt budget (spec §5.3 "Schema strictness
    vs. LLM drift"):

    * Per-row failures (pydantic / allowlist) on a non-final attempt
      push the failing skeleton onto ``next_pending``; the surviving
      rows are accepted as usual.
    * Whole-response parse failures on a non-final attempt dump the raw
      response (for inspection) and re-issue the call with the same
      ``pending`` list — useful when the model truncated transiently
      and a re-prompt yields a complete payload.
    * On the final attempt either failure mode escalates: per-row
      failures drop the skeleton (counted toward the global ≥ 5%
      budget); a whole-response parse failure raises so the step
      surfaces the dumped artefact rather than silently dropping the
      whole chunk.
    """
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
            allowlist=allowlist,
        )
        try:
            details = _parse_details_payload(
                raw,
                expected_handles=[s.handle for s in pending],
            )
        except StageSynthError:
            _dump_failed_response(
                raw,
                debug_dir=debug_dir,
                collection_handle=collection.handle,
                chunk_index=chunk_index,
                attempt=attempt,
            )
            # Whole-response parse failures (e.g. truncated JSON)
            # consume the same one re-prompt budget as per-row
            # validation failures (spec §5.3 "Schema strictness vs.
            # LLM drift"). On the final attempt the chunk has no
            # usable payload — escalate to the step-fatal failure so
            # the user sees the dump path in the run log.
            if attempt < _MAX_RETRIES:
                continue
            raise
        next_pending: list[ProductSkeleton] = []
        for skeleton in pending:
            detail = details.get(skeleton.handle)
            if detail is None:
                next_pending.append(skeleton)
                continue
            try:
                _assert_no_allowlist_token_in_text_fields(detail, allowlist=allowlist)
                _assert_vendor_in_allowlist(detail, allowlist=allowlist)
                _assert_variants_match_options(detail)
            except StageSynthError:
                if attempt < _MAX_RETRIES:
                    next_pending.append(skeleton)
                    continue
                # Final attempt: drop silently; the caller aggregates.
                continue
            accepted[skeleton.handle] = detail
        pending = next_pending

    dropped = len(skeletons) - len(accepted)
    return accepted, dropped


def _dump_failed_response(
    raw: str,
    *,
    debug_dir: Path | None,
    collection_handle: str,
    chunk_index: int,
    attempt: int,
) -> None:
    """Persist a parse-failed LLM response so the caller can inspect it.

    The dump is best-effort: ``debug_dir=None`` and any :class:`OSError`
    during the write are swallowed. The raise of the original parse
    error is the source of truth for the step failure — a missing
    debug artefact must not mask it.
    """
    if debug_dir is None:
        return
    filename = (
        f"{_FAILED_RAW_DUMP_PREFIX}_{collection_handle}"
        f"_chunk_{chunk_index}_attempt_{attempt}.txt"
    )
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / filename).write_text(raw, encoding="utf-8")
    except OSError:
        # Never let a debug-side failure shadow the real parse error.
        return


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
                step issues one LLM call per chunk of skeletons within
                each collection (see :data:`_MAX_SKELETONS_PER_CALL`).

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: Any of the upstream cached files
                (``identity.json``, ``collections.json``,
                ``skeletons.json``) is missing.
            StageSynthError: An LLM response is unparseable (the raw
                response is persisted as
                ``<details_dir>/_failed_<handle>_chunk_<i>_attempt_<n>.txt``
                for inspection before the error propagates), or the
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
                    debug_dir=details_dir,
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
