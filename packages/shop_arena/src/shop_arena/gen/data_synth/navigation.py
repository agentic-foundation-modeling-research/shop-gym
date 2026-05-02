"""``synth_navigation`` — Phase 2 ``navigation.json`` synthesis (spec §5.3).

Single-LLM-call step that drafts the storefront's navigation menus
(``main-menu`` and ``footer``) from the synthesized collections, the
synthesized content pages, and the merged capabilities. The validated
payload is cached as a JSON object under
``<out_dir>/.shop_gen/stage_cache/navigation.json`` (spec §5.3 table);
the terminal :func:`assemble_data` step (T3.11) re-reads the file and
emits the final ``data/navigation.json``.

The output schema mirrors :class:`~shop_arena.gen.data_synth.schema.Navigation`
— a ``{menuHandle: NavigationItem[]}`` object with two required keys.
On top of the schema check, the step asserts that **every collection
handle is reachable from ``main-menu``** (T3.8): the navigation must
not silently drop a category. Missing-collection errors fail the step
so the cache stays in sync with whatever ``synth_collections`` emitted.

Step contract (spec §5.7.1):

* ``id``: ``synth_navigation``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_arena.gen.steps.base.StepInput` per upstream
  step (``synth_collections``, ``synth_pages``, plus the manual-merge
  step ids that own ``manual/capabilities.json``). The cascade through
  those steps already covers the merged manual files.
* ``outputs``: ``.shop_gen/stage_cache/navigation.json``.
* ``depends_on``: ``[synth_collections, synth_pages, *manual_step_ids]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from pydantic import ValidationError

from harness.runtimes import LLMCompleter
from shop_arena.gen.data_synth._synth_helpers import StageSynthError, parse_json_object
from shop_arena.gen.data_synth.prompts import load_synth_navigation_template
from shop_arena.gen.data_synth.schema import Navigation, NavigationItem
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_navigation"
_COLLECTIONS_UPSTREAM_ID: Final[str] = "synth_collections"
_PAGES_UPSTREAM_ID: Final[str] = "synth_pages"
_STEP_VERSION: Final[int] = 1

_OUT_NAVIGATION: Final[Path] = Path(".shop_gen") / "stage_cache" / "navigation.json"
_IN_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"
_IN_PAGES: Final[Path] = Path(".shop_gen") / "stage_cache" / "pages.json"
_IN_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"

_LLM_TIMEOUT_S: Final[float] = 60.0

_MAIN_MENU_HANDLE: Final[str] = "main-menu"
_FOOTER_HANDLE: Final[str] = "footer"
_REQUIRED_MENUS: Final[frozenset[str]] = frozenset({_MAIN_MENU_HANDLE, _FOOTER_HANDLE})

_COLLECTION_URL_PREFIX: Final[str] = "/collections/"


def synth_navigation_from_collections(
    *,
    collections: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    capabilities: dict[str, Any],
    completer: LLMCompleter,
) -> Navigation:
    """Synthesize the storefront's navigation menus.

    Issues exactly one LLM completion, parses the response into a JSON
    object, validates it against :class:`Navigation`, asserts that the
    required ``main-menu`` and ``footer`` handles are present, and that
    every collection handle in ``collections`` is reachable from
    ``main-menu``.

    Args:
        collections: Decoded ``.shop_gen/stage_cache/collections.json``
            payload (the cached :class:`CollectionDraft` array).
        pages: Decoded ``.shop_gen/stage_cache/pages.json`` payload.
        capabilities: Decoded ``manual/capabilities.json`` document.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).

    Returns:
        Validated :class:`Navigation` payload.

    Raises:
        StageSynthError: The LLM response cannot be parsed, fails the
            :class:`Navigation` schema, is missing one of the required
            menu handles, or omits a collection from ``main-menu``.
    """
    prompt = load_synth_navigation_template().format(
        collections=json.dumps(collections, indent=2, sort_keys=True),
        pages=json.dumps(pages, indent=2, sort_keys=True),
        capabilities=json.dumps(capabilities, indent=2, sort_keys=True),
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S)
    payload = parse_json_object(raw, step_id=_STEP_ID)
    try:
        navigation = Navigation.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: response failed Navigation schema validation: {exc}",
        ) from exc
    menus = navigation.root
    missing_menus = _REQUIRED_MENUS - menus.keys()
    if missing_menus:
        raise StageSynthError(
            f"{_STEP_ID}: missing required menu handles: {sorted(missing_menus)}",
        )
    expected_handles = {
        cast("str", entry["handle"])
        for entry in collections
        if isinstance(entry.get("handle"), str)
    }
    reachable = _collection_handles_reachable(menus[_MAIN_MENU_HANDLE])
    missing_collections = expected_handles - reachable
    if missing_collections:
        raise StageSynthError(
            f"{_STEP_ID}: main-menu is missing collection handles: {sorted(missing_collections)}",
        )
    return navigation


class SynthNavigationStep:
    """Phase 2 ``synth_navigation`` step (spec §5.3).

    Reads the cached collections + pages payloads and the merged
    ``manual/capabilities.json``, calls the runtime's
    :class:`~harness.runtimes.LLMCompleter` exactly once, validates the
    response against :class:`Navigation`, and writes the cached payload
    as a JSON object under ``.shop_gen/stage_cache/navigation.json``.

    Attributes:
        id: Step id (``synth_navigation``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` per upstream step.
        outputs: ``.shop_gen/stage_cache/navigation.json``.
        depends_on: ``[synth_collections, synth_pages, *manual_step_ids]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self, *, manual_step_ids: Sequence[str] = ()) -> None:
        """Build the step bound to the cached upstreams + manual-merge step ids.

        Args:
            manual_step_ids: Upstream step ids that produce the merged
                ``manual/`` directory. ``("merge_capabilities",
                "merge_manual_prose")`` for multi-seed runs;
                ``("copy_seed_manual",)`` for single-seed runs. Empty
                in the listing branch (``--list-steps`` does not bind
                to a specific seed count); the placeholder still
                surfaces the step id in
                :func:`shop_arena.gen.pipeline.list_steps`.
        """
        upstream_ids: tuple[str, ...] = (
            _COLLECTIONS_UPSTREAM_ID,
            _PAGES_UPSTREAM_ID,
            *manual_step_ids,
        )
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=sid) for sid in upstream_ids]
        self.outputs: list[Path] = [_OUT_NAVIGATION]
        self.depends_on: list[str] = list(upstream_ids)
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``navigation.json`` and cache it under ``.shop_gen/stage_cache/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step always calls the LLM exactly once.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: One of the cached upstream payloads or
                ``manual/capabilities.json`` does not exist.
            StageSynthError: The LLM response cannot be parsed into a
                valid navigation payload, is missing a required menu
                handle, or omits a collection from ``main-menu``.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_navigation requires a runtime with LLMCompleter; got None",
            )
        collections_path = ctx.out_dir / _IN_COLLECTIONS
        if not collections_path.exists():
            raise FileNotFoundError(
                f"cached collections not found at {collections_path}; run synth_collections first",
            )
        pages_path = ctx.out_dir / _IN_PAGES
        if not pages_path.exists():
            raise FileNotFoundError(
                f"cached pages not found at {pages_path}; run synth_pages first",
            )
        capabilities_path = ctx.out_dir / _IN_CAPABILITIES
        if not capabilities_path.exists():
            raise FileNotFoundError(
                f"merged capabilities not found at {capabilities_path}; "
                "run the manual-merge phase first",
            )
        collections = _load_json_array(collections_path, label="collections.json")
        pages = _load_json_array(pages_path, label="pages.json")
        capabilities = _load_json_object_file(
            capabilities_path,
            label="manual/capabilities.json",
        )

        navigation = synth_navigation_from_collections(
            collections=collections,
            pages=pages,
            capabilities=capabilities,
            completer=ctx.runtime,
        )

        out_path = ctx.out_dir / _OUT_NAVIGATION
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                navigation.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _collection_handles_reachable(items: Sequence[NavigationItem]) -> set[str]:
    """Return every collection handle linked from ``items`` or any descendant.

    Walks the navigation tree, picks out nodes whose ``type`` is
    ``"COLLECTION"`` and whose ``url`` starts with ``/collections/``,
    and returns the handle suffix for each.
    """
    handles: set[str] = set()
    stack: list[NavigationItem] = list(items)
    while stack:
        node = stack.pop()
        if node.type == "COLLECTION" and node.url.startswith(_COLLECTION_URL_PREFIX):
            handle = node.url[len(_COLLECTION_URL_PREFIX) :].split("/", 1)[0]
            if handle:
                handles.add(handle)
        stack.extend(node.children)
    return handles


def _load_json_array(path: Path, *, label: str) -> list[dict[str, Any]]:
    """Read ``path`` as a JSON array of objects for prompt rendering."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"{label} at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, list):
        raise StageSynthError(
            f"{label} at {path} must be a JSON array, got {type(raw).__name__}",
        )
    entries = cast("list[Any]", raw)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise StageSynthError(
                f"{label} at {path} entry {index} must be a JSON object, "
                f"got {type(entry).__name__}",
            )
    return cast("list[dict[str, Any]]", entries)


def _load_json_object_file(path: Path, *, label: str) -> dict[str, Any]:
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


__all__ = [
    "SynthNavigationStep",
    "synth_navigation_from_collections",
]
