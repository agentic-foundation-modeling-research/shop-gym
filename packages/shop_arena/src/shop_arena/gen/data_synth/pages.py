"""``synth_pages`` — Phase 2 ``pages.json`` synthesis (spec §5.3).

Single-LLM-call step that drafts the storefront's content pages
(about / contact / FAQ / shipping / etc.) from the brand-free identity
emitted by ``synth_identity`` and the merged ``capabilities.json`` (the
manual's ground-truth list of pages the storefront promises). Each
emitted entry is validated against
:class:`~shop_arena.gen.data_synth.schema.Page`.

The validated payload is cached as a JSON array under
``<out_dir>/.shop_gen/stage_cache/pages.json`` (spec §5.3 table). The
terminal :func:`assemble_data` step (T3.11) re-reads the file and emits
the final ``data/pages.json``.

Step contract (spec §5.7.1):

* ``id``: ``synth_pages``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_arena.gen.steps.base.StepInput` per upstream
  step (``synth_identity`` plus the manual-merge step ids that own
  ``manual/capabilities.json``). The cascade through those steps
  already covers the merged manual files.
* ``outputs``: ``.shop_gen/stage_cache/pages.json``.
* ``depends_on``: ``[synth_identity, *manual_step_ids]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from pydantic import RootModel, ValidationError

from harness.runtimes import LLMCompleter
from shop_arena.gen.data_synth._synth_helpers import StageSynthError, parse_json_array
from shop_arena.gen.data_synth.prompts import load_synth_pages_template
from shop_arena.gen.data_synth.schema import Page
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_pages"
_IDENTITY_UPSTREAM_ID: Final[str] = "synth_identity"
_STEP_VERSION: Final[int] = 1

_OUT_PAGES: Final[Path] = Path(".shop_gen") / "stage_cache" / "pages.json"
_IN_IDENTITY: Final[Path] = Path("identity.json")
_IN_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"

_LLM_TIMEOUT_S: Final[float] = 360.0


class _PagesPayload(RootModel[list[Page]]):
    """Pydantic root wrapper validating the LLM's ``list[Page]`` array."""


def synth_pages_from_identity(
    *,
    identity: dict[str, Any],
    capabilities: dict[str, Any],
    completer: LLMCompleter,
) -> list[Page]:
    """Synthesize the storefront's content pages.

    Issues exactly one LLM completion, parses the response into a JSON
    array, validates the array against :class:`Page`, and asserts that
    handles are unique.

    Args:
        identity: Decoded ``identity.json`` document.
        capabilities: Decoded ``manual/capabilities.json`` document.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).

    Returns:
        Validated, handle-unique :class:`Page` records in the order the
        LLM emitted them.

    Raises:
        StageSynthError: The LLM response cannot be parsed, fails the
            :class:`Page` schema, is empty, or has duplicate handles.
    """
    prompt = load_synth_pages_template().format(
        identity=json.dumps(identity, indent=2, sort_keys=True),
        capabilities=json.dumps(capabilities, indent=2, sort_keys=True),
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S)
    payload = parse_json_array(raw, step_id=_STEP_ID)
    if not payload:
        raise StageSynthError(f"{_STEP_ID}: LLM emitted an empty pages array")
    try:
        validated = _PagesPayload.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: response failed Page schema validation: {exc}",
        ) from exc
    pages = validated.root
    seen: set[str] = set()
    for page in pages:
        if page.handle in seen:
            raise StageSynthError(
                f"{_STEP_ID}: duplicate page handle {page.handle!r}",
            )
        seen.add(page.handle)
    return pages


class SynthPagesStep:
    """Phase 2 ``synth_pages`` step (spec §5.3).

    Reads ``identity.json`` + ``manual/capabilities.json``, calls the
    runtime's :class:`~harness.runtimes.LLMCompleter` exactly once,
    validates each entry against :class:`Page`, and writes the cached
    payload as a JSON array under ``.shop_gen/stage_cache/pages.json``.

    Attributes:
        id: Step id (``synth_pages``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` per upstream step.
        outputs: ``.shop_gen/stage_cache/pages.json``.
        depends_on: ``[synth_identity, *manual_step_ids]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self, *, manual_step_ids: Sequence[str] = ()) -> None:
        """Build the step bound to ``synth_identity`` + the manual-merge upstreams.

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
        upstream_ids: tuple[str, ...] = (_IDENTITY_UPSTREAM_ID, *manual_step_ids)
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=sid) for sid in upstream_ids]
        self.outputs: list[Path] = [_OUT_PAGES]
        self.depends_on: list[str] = list(upstream_ids)
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``pages.json`` and cache it under ``.shop_gen/stage_cache/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step always calls the LLM exactly once.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: ``identity.json`` or
                ``manual/capabilities.json`` does not exist.
            StageSynthError: The LLM response cannot be parsed into a
                valid pages array.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_pages requires a runtime with LLMCompleter; got None",
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
        identity = _load_json_object(identity_path, label="identity.json")
        capabilities = _load_json_object(capabilities_path, label="manual/capabilities.json")

        pages = synth_pages_from_identity(
            identity=identity,
            capabilities=capabilities,
            completer=ctx.runtime,
        )

        out_path = ctx.out_dir / _OUT_PAGES
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                [page.model_dump(mode="json") for page in pages],
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


__all__ = [
    "SynthPagesStep",
    "synth_pages_from_identity",
]
