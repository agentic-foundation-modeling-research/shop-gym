"""``synth_collections`` — Phase 2 ``collections.json`` synthesis (spec §5.3).

Single-LLM-call step that drafts the storefront's collection records
from the brand-free identity emitted by ``synth_identity``, the merged
``capabilities.json`` (the manual's ground-truth list of categories the
storefront promises), and the merged ``stats.json`` (priors for how many
collections the seeds ship and how many products each one carries).

The LLM is asked for ``N`` records (default 10, optionally tuned to the
merged stats' ``collections_total``) where each record carries the
fields needed by downstream Phase 2 steps:

* ``title`` — plain descriptive ("outerwear", "kitchen tools"). The
  step rejects titles that contain any allowlisted brand token (spec
  §5.6: "plain-description fields … no proper nouns at all unless from
  the allowlist", and even then collection titles are descriptive — we
  go a step further and forbid allowlist tokens too).
* ``handle`` — URL-safe slug. Unique within the array.
* ``description`` — short plain-text description.
* ``sort_order`` — sort-order keyword (``"manual"``, ``"best-selling"``,
  ``"created-desc"``, etc.).
* ``target_product_count`` — synthesis-time hint consumed by
  ``synth_product_skeletons`` (T3.6) so it knows how to distribute the
  catalog's ``products_total`` budget across collections. Not part of
  the final :class:`~shop_arena.gen.data_synth.schema.Collection` schema; the
  cached file therefore uses the local :class:`CollectionDraft` shape.

The validated draft list is cached as a JSON array under
``<out_dir>/.shop_gen/stage_cache/collections.json`` (spec §5.3 table).
The terminal :func:`assemble_data` step (T3.11) re-reads the file,
attaches ``product_handles`` once skeletons land, and emits the final
``data/collections.json``.

Step contract (spec §5.7.1):

* ``id``: ``synth_collections``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_arena.gen.steps.base.StepInput` per upstream
  step (``synth_identity`` plus the manual-merge step ids that own
  ``manual/capabilities.json`` and ``manual/stats.json``). The cascade
  through those steps already covers the merged manual files.
* ``outputs``: ``.shop_gen/stage_cache/collections.json``.
* ``depends_on``: ``[synth_identity, *manual_step_ids]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from harness.runtimes import LLMCompleter
from shop_arena.gen.brands.allowlist import Allowlist, load_allowlist
from shop_arena.gen.data_synth._synth_helpers import StageSynthError, parse_json_array
from shop_arena.gen.data_synth.prompts import load_synth_collections_template
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_collections"
_IDENTITY_UPSTREAM_ID: Final[str] = "synth_identity"
_STEP_VERSION: Final[int] = 1

_OUT_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"
_IN_IDENTITY: Final[Path] = Path("identity.json")
_IN_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"
_IN_STATS: Final[Path] = Path("manual") / "stats.json"

_LLM_TIMEOUT_S: Final[float] = 300.0

_TARGET_COUNT_DEFAULT: Final[int] = 10
"""Default collection count when the merged stats do not constrain it (spec §5.3)."""

_TARGET_COUNT_MIN: Final[int] = 3
_TARGET_COUNT_MAX: Final[int] = 30
"""Clamp range applied to ``stats.collections_total`` before prompting.

The merged priors are noisy (median across 1-3 seeds); clamping keeps the
catalog buildable at v0.1 scale (~200 products) regardless of seed quirks.
"""

_TITLE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Za-z]+")
"""Same capitalized-run regex the §5.6 scanner uses, applied to titles."""


# --------------------------------------------------------------------------- #
# Cached payload shape (synthesis-time, NOT the final Collection schema)
# --------------------------------------------------------------------------- #


class CollectionDraft(BaseModel):
    """One collection record as emitted by ``synth_collections``.

    Carries only the fields the LLM authors at this stage. The terminal
    :func:`assemble_data` step (T3.11) attaches ``id``,
    ``description_html``, ``image``, ``published_at``, ``updated_at``,
    and ``product_handles`` to produce the final
    :class:`~shop_arena.gen.data_synth.schema.Collection`.

    Attributes:
        title: Plain-descriptive display title (e.g. ``"outerwear"``,
            ``"kitchen tools"``). Must not contain any allowlisted
            brand token; enforced in
            :func:`synth_collections_from_identity`.
        handle: URL-safe slug (lowercase ASCII, hyphens between words).
            Unique within the emitted array.
        description: Short plain-text description.
        sort_order: Sort-order keyword (``"manual"``, ``"best-selling"``,
            ``"created-desc"``, ``"price-asc"``, etc.).
        target_product_count: Hint for ``synth_product_skeletons`` so it
            can split the catalog budget across collections. Must be at
            least 1.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    handle: str
    description: str
    sort_order: str
    target_product_count: int


class _CollectionsPayload(RootModel[list[CollectionDraft]]):
    """Pydantic root wrapper validating the LLM's ``list[CollectionDraft]`` array."""


# --------------------------------------------------------------------------- #
# Synthesis function
# --------------------------------------------------------------------------- #


def resolve_target_count(stats: dict[str, Any]) -> int:
    """Pick the ``N`` to ask the LLM for, given the merged stats priors.

    Uses ``stats.collections_total`` when it is a positive integer,
    otherwise falls back to :data:`_TARGET_COUNT_DEFAULT` (spec §5.3
    "default 10"). Always clamps to ``[_TARGET_COUNT_MIN,
    _TARGET_COUNT_MAX]`` to keep the catalog buildable at v0.1 scale.

    Args:
        stats: Decoded ``manual/stats.json`` document.

    Returns:
        Clamped collection count.
    """
    raw: Any = stats.get("collections_total", 0)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        candidate = _TARGET_COUNT_DEFAULT
    else:
        candidate = raw
    return max(_TARGET_COUNT_MIN, min(_TARGET_COUNT_MAX, candidate))


def synth_collections_from_identity(
    *,
    identity: dict[str, Any],
    capabilities: dict[str, Any],
    stats: dict[str, Any],
    completer: LLMCompleter,
    allowlist: Allowlist | None = None,
) -> list[CollectionDraft]:
    """Synthesize the storefront's collections.

    Issues exactly one LLM completion, parses the response into a JSON
    array, validates the array against :class:`CollectionDraft`, and
    asserts that the count matches the prior, that handles are unique,
    and that no title contains an allowlisted brand token (spec §5.6:
    plain-description fields are brand-free).

    Args:
        identity: Decoded ``identity.json`` document.
        capabilities: Decoded ``manual/capabilities.json`` document.
        stats: Decoded ``manual/stats.json`` document. Drives the
            target collection count via :func:`resolve_target_count`.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).
        allowlist: Optional pre-loaded :class:`Allowlist`. Defaults to
            the in-repo ``fake_brands.json`` (cached after first use).

    Returns:
        Validated, handle-unique :class:`CollectionDraft` records in
        the order the LLM emitted them.

    Raises:
        StageSynthError: The LLM response cannot be parsed, fails the
            :class:`CollectionDraft` schema, has the wrong record
            count, has duplicate handles, or includes an allowlisted
            brand token in a title.
    """
    target_count = resolve_target_count(stats)
    prompt = load_synth_collections_template().format(
        identity=json.dumps(identity, indent=2, sort_keys=True),
        capabilities=json.dumps(capabilities, indent=2, sort_keys=True),
        stats=json.dumps(stats, indent=2, sort_keys=True),
        target_count=target_count,
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S)
    payload = parse_json_array(raw, step_id=_STEP_ID)
    if not payload:
        raise StageSynthError(f"{_STEP_ID}: LLM emitted an empty collections array")
    try:
        validated = _CollectionsPayload.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: response failed CollectionDraft schema validation: {exc}",
        ) from exc
    collections = validated.root
    if len(collections) != target_count:
        raise StageSynthError(
            f"{_STEP_ID}: expected {target_count} collections, got {len(collections)}",
        )
    seen: set[str] = set()
    for collection in collections:
        if collection.target_product_count < 1:
            raise StageSynthError(
                f"{_STEP_ID}: collection {collection.handle!r} has non-positive "
                f"target_product_count={collection.target_product_count}",
            )
        if collection.handle in seen:
            raise StageSynthError(
                f"{_STEP_ID}: duplicate collection handle {collection.handle!r}",
            )
        seen.add(collection.handle)
    target_allowlist = allowlist if allowlist is not None else load_allowlist()
    for collection in collections:
        leak = _allowlist_token_in_title(collection.title, target_allowlist)
        if leak is not None:
            raise StageSynthError(
                f"{_STEP_ID}: collection title {collection.title!r} contains "
                f"allowlisted brand token {leak!r}; titles must be plain descriptive",
            )
    return collections


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class SynthCollectionsStep:
    """Phase 2 ``synth_collections`` step (spec §5.3).

    Reads ``identity.json``, ``manual/capabilities.json``, and
    ``manual/stats.json``, calls the runtime's
    :class:`~harness.runtimes.LLMCompleter` exactly once, validates each
    entry against :class:`CollectionDraft`, and writes the cached
    payload as a JSON array under
    ``.shop_gen/stage_cache/collections.json``.

    Attributes:
        id: Step id (``synth_collections``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` per upstream step.
        outputs: ``.shop_gen/stage_cache/collections.json``.
        depends_on: ``[synth_identity, *manual_step_ids]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self, *, manual_step_ids: Sequence[str] = ()) -> None:
        """Build the step bound to ``synth_identity`` + the manual-merge upstreams.

        Args:
            manual_step_ids: Upstream step ids that produce the merged
                ``manual/`` directory. ``("merge_capabilities",
                "merge_manual_prose", "compute_merge_stats")`` for
                multi-seed runs; ``("copy_seed_manual",)`` for
                single-seed runs. Empty in the listing branch
                (``--list-steps`` does not bind to a specific seed
                count); the placeholder still surfaces the step id in
                :func:`shop_arena.gen.pipeline.list_steps`.
        """
        upstream_ids: tuple[str, ...] = (_IDENTITY_UPSTREAM_ID, *manual_step_ids)
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=sid) for sid in upstream_ids]
        self.outputs: list[Path] = [_OUT_COLLECTIONS]
        self.depends_on: list[str] = list(upstream_ids)
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``collections.json`` and cache it under ``.shop_gen/stage_cache/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step always calls the LLM exactly once.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: ``identity.json``,
                ``manual/capabilities.json``, or ``manual/stats.json``
                does not exist.
            StageSynthError: The LLM response cannot be parsed into a
                valid collections array, or a title contains an
                allowlisted brand token.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_collections requires a runtime with LLMCompleter; got None",
            )
        identity_path = ctx.out_dir / _IN_IDENTITY
        if not identity_path.exists():
            raise FileNotFoundError(
                f"identity.json not found at {identity_path}; run synth_identity first",
            )
        capabilities_path = ctx.out_dir / _IN_CAPABILITIES
        if not capabilities_path.exists():
            raise FileNotFoundError(
                f"merged capabilities not found at {capabilities_path}; "
                "run the manual-merge phase first",
            )
        stats_path = ctx.out_dir / _IN_STATS
        if not stats_path.exists():
            raise FileNotFoundError(
                f"merged stats not found at {stats_path}; run the manual-merge phase first",
            )
        identity = _load_json_object(identity_path, label="identity.json")
        capabilities = _load_json_object(capabilities_path, label="manual/capabilities.json")
        stats = _load_json_object(stats_path, label="manual/stats.json")

        collections = synth_collections_from_identity(
            identity=identity,
            capabilities=capabilities,
            stats=stats,
            completer=ctx.runtime,
        )

        out_path = ctx.out_dir / _OUT_COLLECTIONS
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                [collection.model_dump(mode="json") for collection in collections],
                indent=2,
                sort_keys=True,
            )
            + "\n",
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


def _allowlist_token_in_title(title: str, allowlist: Allowlist) -> str | None:
    """Return the first allowlist brand token found in ``title``, or ``None``.

    Collection titles are plain descriptive (spec §5.3): even allowlisted
    brand tokens are forbidden in titles, because the storefront's brand
    name lives in ``store.name`` and ``product.vendor`` — not on a
    category card.
    """
    for match in _TITLE_TOKEN_RE.finditer(title):
        token = match.group(0)
        if allowlist.is_allowed(token):
            return token
    return None


__all__ = [
    "CollectionDraft",
    "SynthCollectionsStep",
    "resolve_target_count",
    "synth_collections_from_identity",
]
