"""``synth_store`` — Phase 2 ``store.json`` synthesis (spec §5.3).

Single-LLM-call step that drafts the ``store.json`` payload from the
brand-free identity emitted by ``synth_identity``. The orchestrator
overrides ``shop_id`` (assigned deterministically by ``assemble_data``),
``name`` (picked from the fake-brand allowlist by ``synth_identity``),
``currency_code``, and ``country_code`` (from ``identity.json``); the
LLM only authors the storefront's domain, description, payment options,
and brand visuals.

The validated :class:`~shop_arena.gen.data_synth.schema.Store` payload is
cached under ``<out_dir>/.shop_gen/stage_cache/store.json`` (spec §5.3
table). The terminal :func:`assemble_data` step (T3.11) re-reads the
file, re-assigns ``shop_id``, and emits the final ``data/store.json``.

Step contract (spec §5.7.1):

* ``id``: ``synth_store``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_arena.gen.steps.base.StepInput` referencing
  ``synth_identity``. The cascade through ``synth_identity`` already
  covers the merged manual files, so no :class:`FileInput` references
  are declared.
* ``outputs``: ``.shop_gen/stage_cache/store.json``.
* ``depends_on``: ``[synth_identity]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, cast

from pydantic import ValidationError

from harness.runtimes import LLMCompleter
from shop_arena.gen.data_synth._synth_helpers import StageSynthError, parse_json_object
from shop_arena.gen.data_synth.prompts import load_synth_store_template
from shop_arena.gen.data_synth.schema import Store
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_store"
_UPSTREAM_ID: Final[str] = "synth_identity"
_STEP_VERSION: Final[int] = 1

_OUT_STORE: Final[Path] = Path(".shop_gen") / "stage_cache" / "store.json"
_IN_IDENTITY: Final[Path] = Path("identity.json")

_LLM_TIMEOUT_S: Final[float] = 60.0

_PLACEHOLDER_SHOP_ID: Final[int] = 0
"""``Store.shop_id`` placeholder; ``assemble_data`` reassigns it."""


def synth_store_from_identity(
    *,
    identity: dict[str, Any],
    completer: LLMCompleter,
) -> Store:
    """Synthesize a :class:`Store` payload from the brand-free identity.

    Issues exactly one LLM completion, parses the response into the
    LLM-authored fields (``domain``, ``description``,
    ``payment_settings``, ``brand``), then assembles the final
    :class:`Store` with the identity-locked fields (``name``,
    ``currency_code``, ``country_code``) and the placeholder
    ``shop_id`` overridden in by the orchestrator.

    Args:
        identity: Decoded ``identity.json`` document. Must contain
            ``name``, ``currency``, and ``country``.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).

    Returns:
        A validated :class:`Store`.

    Raises:
        StageSynthError: The LLM response cannot be parsed into the
            shape :class:`Store` requires (missing fields, wrong types,
            schema violations).
    """
    name = _require_str(identity, "name")
    currency = _require_str(identity, "currency")
    country = _require_str(identity, "country")

    prompt = load_synth_store_template().format(
        identity=json.dumps(identity, indent=2, sort_keys=True),
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S)
    payload = parse_json_object(raw, step_id=_STEP_ID)

    # Orchestrator-owned fields are stripped from the LLM payload before
    # validation so an over-eager model can't smuggle conflicting values
    # past the schema check.
    for owned_key in ("shop_id", "name", "currency_code", "country_code"):
        payload.pop(owned_key, None)
    payload["shop_id"] = _PLACEHOLDER_SHOP_ID
    payload["name"] = name
    payload["currency_code"] = currency
    payload["country_code"] = country

    try:
        return Store.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: response failed Store schema validation: {exc}",
        ) from exc


class SynthStoreStep:
    """Phase 2 ``synth_store`` step (spec §5.3).

    Reads ``identity.json``, calls the runtime's
    :class:`~harness.runtimes.LLMCompleter` exactly once, validates the
    response against :class:`Store`, and writes the cached payload to
    ``.shop_gen/stage_cache/store.json``.

    Attributes:
        id: Step id (``synth_store``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` referencing ``synth_identity``.
        outputs: ``.shop_gen/stage_cache/store.json``.
        depends_on: ``[synth_identity]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the ``synth_identity`` upstream."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_UPSTREAM_ID)]
        self.outputs: list[Path] = [_OUT_STORE]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``store.json`` and cache it under ``.shop_gen/stage_cache/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step always calls the LLM exactly once.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: ``identity.json`` does not exist.
            StageSynthError: The LLM response cannot be parsed into a
                valid :class:`Store`.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_store requires a runtime with LLMCompleter; got None",
            )
        identity_path = ctx.out_dir / _IN_IDENTITY
        if not identity_path.exists():
            raise FileNotFoundError(
                f"identity.json not found at {identity_path}; run synth_identity first",
            )
        identity = _load_identity(identity_path)

        store = synth_store_from_identity(identity=identity, completer=ctx.runtime)

        out_path = ctx.out_dir / _OUT_STORE
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(store.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _load_identity(path: Path) -> dict[str, Any]:
    """Read ``identity.json`` as a plain dict for prompt rendering."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"identity.json at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise StageSynthError(
            f"identity.json at {path} must be a JSON object, got {type(raw).__name__}",
        )
    return cast("dict[str, Any]", raw)


def _require_str(payload: dict[str, Any], key: str) -> str:
    """Pull a non-empty string field out of a JSON object or raise."""
    value: Any = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StageSynthError(
            f"{_STEP_ID}: identity.json missing non-empty string {key!r}",
        )
    return value.strip()


__all__ = [
    "SynthStoreStep",
    "synth_store_from_identity",
]
