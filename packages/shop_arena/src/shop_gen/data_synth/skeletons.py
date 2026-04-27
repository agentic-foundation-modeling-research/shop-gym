"""``synth_product_skeletons`` — Phase 2 catalog skeleton synthesis (spec §5.3).

Bulk-LLM-call step that drafts every product's "spine" — title, handle,
price hint, and collection assignment — in one pass. At v0.1 scale
(~200 products) the entire catalog fits in one prompt; per-collection
bulk naming makes intra-collection duplicates impossible by
construction.

Reads the cached ``CollectionDraft`` list emitted by
``synth_collections`` and uses each collection's ``target_product_count``
as the per-collection budget. Total catalog size is the sum of those
budgets. The validated payload is cached as a JSON array under
``<out_dir>/.shop_gen/stage_cache/skeletons.json`` (spec §5.3 table) and
consumed by :func:`synth_product_details` (T3.7) and the terminal
:func:`assemble_data` step (T3.11).

Step contract (spec §5.7.1):

* ``id``: ``synth_product_skeletons``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_gen.steps.base.StepInput` referencing
  ``synth_collections``. The cascade through that step already covers
  the merged manual files and the identity payload, so no
  :class:`FileInput` references are declared.
* ``outputs``: ``.shop_gen/stage_cache/skeletons.json``.
* ``depends_on``: ``[synth_collections]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from harness.runtimes import LLMCompleter
from shop_gen.brands.allowlist import Allowlist, load_allowlist
from shop_gen.data_synth._synth_helpers import StageSynthError, parse_json_array
from shop_gen.data_synth.collections import CollectionDraft
from shop_gen.data_synth.prompts import load_synth_product_skeletons_template
from shop_gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_product_skeletons"
_UPSTREAM_ID: Final[str] = "synth_collections"
_STEP_VERSION: Final[int] = 1

_OUT_SKELETONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "skeletons.json"
_IN_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"

_LLM_TIMEOUT_S: Final[float] = 120.0
"""Bulk-call budget. ~200 products fit comfortably in one completion at v0.1 scale."""

_TITLE_MIN_WORDS: Final[int] = 2
_TITLE_MAX_WORDS: Final[int] = 5
"""Two-to-five-word naming rule (spec §5.3)."""

_TITLE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Za-z]+")
"""Same capitalized-run regex the §5.6 scanner uses, applied to titles."""

_WORD_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
"""Whitespace splitter for the title-word-count check."""


# --------------------------------------------------------------------------- #
# Cached payload shape (synthesis-time, not the final Product schema)
# --------------------------------------------------------------------------- #


class ProductSkeleton(BaseModel):
    """One product skeleton as emitted by ``synth_product_skeletons``.

    Carries only the fields the bulk LLM call authors at this stage. The
    follow-up :func:`synth_product_details` step (T3.7) attaches
    variants, options, ``description_html``, vendor, and tags, and the
    terminal :func:`assemble_data` step (T3.11) attaches ``id`` and
    timestamps to produce the final
    :class:`~shop_gen.data_synth.schema.Product`.

    Attributes:
        title: Plain-descriptive 2-5 word noun phrase
            (e.g. ``"white sport t-shirt"``). Must not contain any
            allowlisted brand token; enforced in
            :func:`synth_product_skeletons_from_collections`.
        handle: URL-safe slug (lowercase ASCII, hyphens between words).
            Unique within each collection.
        price: Decimal price hint serialized as a string
            (e.g. ``"29.99"``). Refined per-variant by
            :func:`synth_product_details`.
        collection_handle: Handle of the collection this skeleton
            belongs to. Must match exactly one of the upstream
            :class:`~shop_gen.data_synth.collections.CollectionDraft`
            handles.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    handle: str
    price: str
    collection_handle: str


class _SkeletonsPayload(RootModel[list[ProductSkeleton]]):
    """Pydantic root wrapper validating the LLM's ``list[ProductSkeleton]`` array."""


# --------------------------------------------------------------------------- #
# Synthesis function
# --------------------------------------------------------------------------- #


def synth_product_skeletons_from_collections(
    *,
    collections: list[CollectionDraft],
    completer: LLMCompleter,
    allowlist: Allowlist | None = None,
) -> list[ProductSkeleton]:
    """Synthesize the storefront's product catalog skeleton.

    Issues exactly one bulk LLM completion, parses the response into a
    JSON array, validates each entry against :class:`ProductSkeleton`,
    and asserts:

    * Total count equals ``sum(c.target_product_count for c in collections)``.
    * Every ``collection_handle`` references an upstream collection.
    * Per-collection product count matches each collection's
      ``target_product_count``.
    * Handles are unique within each collection (cross-collection
      conflicts are tolerated; resolved at assembly time per spec §5.3).
    * Titles contain 2-5 whitespace-separated words.
    * Titles do not contain any allowlisted brand token (spec §5.6:
      plain-description fields are brand-free; ``Product.vendor`` is
      where the allowlist appears).

    Args:
        collections: Validated :class:`CollectionDraft` records emitted
            by :func:`synth_collections`. Must be non-empty.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).
        allowlist: Optional pre-loaded :class:`Allowlist`. Defaults to
            the in-repo ``fake_brands.json`` (cached after first use).

    Returns:
        Validated :class:`ProductSkeleton` records in the order the LLM
        emitted them.

    Raises:
        StageSynthError: ``collections`` is empty, the LLM response
            cannot be parsed, fails the :class:`ProductSkeleton`
            schema, has the wrong total count, references an unknown
            collection handle, has the wrong per-collection count,
            duplicates a handle within a collection, has a title
            outside the 2-5 word range, or has a title containing an
            allowlisted brand token.
    """
    if not collections:
        raise StageSynthError(
            f"{_STEP_ID}: refusing to synthesize skeletons against an empty collection list",
        )
    total_products = sum(c.target_product_count for c in collections)
    prompt = load_synth_product_skeletons_template().format(
        collections=json.dumps(
            [c.model_dump(mode="json") for c in collections],
            indent=2,
            sort_keys=True,
        ),
        total_products=total_products,
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S)
    payload = parse_json_array(raw, step_id=_STEP_ID)
    if not payload:
        raise StageSynthError(f"{_STEP_ID}: LLM emitted an empty skeletons array")
    try:
        validated = _SkeletonsPayload.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: response failed ProductSkeleton schema validation: {exc}",
        ) from exc
    skeletons = validated.root
    if len(skeletons) != total_products:
        raise StageSynthError(
            f"{_STEP_ID}: expected {total_products} skeletons, got {len(skeletons)}",
        )
    target_allowlist = allowlist if allowlist is not None else load_allowlist()
    _assert_known_collections(skeletons, collections=collections)
    _assert_per_collection_counts(skeletons, collections=collections)
    _assert_unique_handles_per_collection(skeletons)
    _assert_title_word_counts(skeletons)
    _assert_no_allowlist_token_in_titles(skeletons, allowlist=target_allowlist)
    return skeletons


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class SynthProductSkeletonsStep:
    """Phase 2 ``synth_product_skeletons`` step (spec §5.3).

    Reads the cached :class:`CollectionDraft` list at
    ``.shop_gen/stage_cache/collections.json``, calls the runtime's
    :class:`~harness.runtimes.LLMCompleter` exactly once, validates each
    entry against :class:`ProductSkeleton`, and writes the cached
    payload as a JSON array under
    ``.shop_gen/stage_cache/skeletons.json``.

    Attributes:
        id: Step id (``synth_product_skeletons``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` referencing ``synth_collections``.
        outputs: ``.shop_gen/stage_cache/skeletons.json``.
        depends_on: ``[synth_collections]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the ``synth_collections`` upstream."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_UPSTREAM_ID)]
        self.outputs: list[Path] = [_OUT_SKELETONS]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``skeletons.json`` and cache it under ``.shop_gen/stage_cache/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step always calls the LLM exactly once.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: ``.shop_gen/stage_cache/collections.json``
                does not exist.
            StageSynthError: The cached collections file is malformed,
                or the LLM response cannot be parsed into a valid
                skeletons array.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_product_skeletons requires a runtime with LLMCompleter; got None",
            )
        collections_path = ctx.out_dir / _IN_COLLECTIONS
        if not collections_path.exists():
            raise FileNotFoundError(
                f"cached collections not found at {collections_path}; run synth_collections first",
            )
        collections = _load_collections(collections_path)

        skeletons = synth_product_skeletons_from_collections(
            collections=collections,
            completer=ctx.runtime,
        )

        out_path = ctx.out_dir / _OUT_SKELETONS
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                [skeleton.model_dump(mode="json") for skeleton in skeletons],
                indent=2,
                sort_keys=True,
            )
            + "\n",
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


def _assert_known_collections(
    skeletons: list[ProductSkeleton],
    *,
    collections: list[CollectionDraft],
) -> None:
    """Reject skeletons whose ``collection_handle`` is not in ``collections``."""
    known = {c.handle for c in collections}
    for skeleton in skeletons:
        if skeleton.collection_handle not in known:
            raise StageSynthError(
                f"{_STEP_ID}: skeleton {skeleton.handle!r} references unknown "
                f"collection_handle {skeleton.collection_handle!r}",
            )


def _assert_per_collection_counts(
    skeletons: list[ProductSkeleton],
    *,
    collections: list[CollectionDraft],
) -> None:
    """Reject when a collection's skeleton count differs from its target."""
    actual: dict[str, int] = {c.handle: 0 for c in collections}
    for skeleton in skeletons:
        actual[skeleton.collection_handle] += 1
    for collection in collections:
        expected = collection.target_product_count
        got = actual[collection.handle]
        if got != expected:
            raise StageSynthError(
                f"{_STEP_ID}: collection {collection.handle!r} expected "
                f"{expected} skeletons, got {got}",
            )


def _assert_unique_handles_per_collection(skeletons: list[ProductSkeleton]) -> None:
    """Reject duplicate ``handle`` values within the same ``collection_handle``."""
    seen: dict[str, set[str]] = {}
    for skeleton in skeletons:
        bucket = seen.setdefault(skeleton.collection_handle, set())
        if skeleton.handle in bucket:
            raise StageSynthError(
                f"{_STEP_ID}: duplicate skeleton handle {skeleton.handle!r} "
                f"within collection {skeleton.collection_handle!r}",
            )
        bucket.add(skeleton.handle)


def _assert_title_word_counts(skeletons: list[ProductSkeleton]) -> None:
    """Reject titles that fall outside the 2-5 word range (spec §5.3)."""
    for skeleton in skeletons:
        words = [w for w in _WORD_SPLIT_RE.split(skeleton.title.strip()) if w]
        if not _TITLE_MIN_WORDS <= len(words) <= _TITLE_MAX_WORDS:
            raise StageSynthError(
                f"{_STEP_ID}: skeleton {skeleton.handle!r} title "
                f"{skeleton.title!r} has {len(words)} words; "
                f"expected between {_TITLE_MIN_WORDS} and {_TITLE_MAX_WORDS}",
            )


def _assert_no_allowlist_token_in_titles(
    skeletons: list[ProductSkeleton],
    *,
    allowlist: Allowlist,
) -> None:
    """Reject titles that contain any allowlisted brand token (spec §5.6)."""
    for skeleton in skeletons:
        for match in _TITLE_TOKEN_RE.finditer(skeleton.title):
            token = match.group(0)
            if allowlist.is_allowed(token):
                raise StageSynthError(
                    f"{_STEP_ID}: skeleton {skeleton.handle!r} title "
                    f"{skeleton.title!r} contains allowlisted brand token "
                    f"{token!r}; titles must be plain descriptive",
                )


__all__ = [
    "ProductSkeleton",
    "SynthProductSkeletonsStep",
    "synth_product_skeletons_from_collections",
]
