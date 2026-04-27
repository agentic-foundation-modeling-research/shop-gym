"""``synth_policies`` — Phase 2 ``policies.json`` synthesis (spec §5.3).

Single-LLM-call step that drafts the storefront's policy pages
(privacy / shipping / terms / refund) from the brand-free identity
emitted by ``synth_identity``. Each entry is validated against
:class:`~shop_gen.data_synth.schema.Policy`.

The validated payload is cached as a JSON array under
``<out_dir>/.shop_gen/stage_cache/policies.json`` (spec §5.3 table). The
terminal :func:`assemble_data` step (T3.11) re-reads the file and emits
the final ``data/policies.json``.

Step contract (spec §5.7.1):

* ``id``: ``synth_policies``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_gen.steps.base.StepInput` referencing
  ``synth_identity``.
* ``outputs``: ``.shop_gen/stage_cache/policies.json``.
* ``depends_on``: ``[synth_identity]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, cast

from pydantic import RootModel, ValidationError

from harness.runtimes import LLMCompleter
from shop_gen.data_synth._synth_helpers import StageSynthError, parse_json_array
from shop_gen.data_synth.prompts import load_synth_policies_template
from shop_gen.data_synth.schema import Policy
from shop_gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_policies"
_UPSTREAM_ID: Final[str] = "synth_identity"
_STEP_VERSION: Final[int] = 1

_OUT_POLICIES: Final[Path] = Path(".shop_gen") / "stage_cache" / "policies.json"
_IN_IDENTITY: Final[Path] = Path("identity.json")

_LLM_TIMEOUT_S: Final[float] = 60.0

_REQUIRED_HANDLES: Final[frozenset[str]] = frozenset(
    {
        "privacy-policy",
        "shipping-policy",
        "terms-of-service",
        "refund-policy",
    },
)
"""Conventional policy handles every storefront ships (spec §8.1.1).

The schema (:class:`Policy`) deliberately does not enumerate them so
unknown-but-valid policies still validate, but the prompt requires the
full set and the step asserts coverage at parse time.
"""


class _PoliciesPayload(RootModel[list[Policy]]):
    """Pydantic root wrapper validating the LLM's ``list[Policy]`` array."""


def synth_policies_from_identity(
    *,
    identity: dict[str, Any],
    completer: LLMCompleter,
) -> list[Policy]:
    """Synthesize the storefront's policy pages.

    Issues exactly one LLM completion, parses the response into a JSON
    array, validates the array against :class:`Policy`, and asserts
    that all conventional handles (:data:`_REQUIRED_HANDLES`) are
    present and unique.

    Args:
        identity: Decoded ``identity.json`` document.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).

    Returns:
        Validated, handle-unique :class:`Policy` records in the order
        the LLM emitted them.

    Raises:
        StageSynthError: The LLM response cannot be parsed, fails the
            :class:`Policy` schema, has duplicate handles, or is
            missing one of the conventional policy handles.
    """
    prompt = load_synth_policies_template().format(
        identity=json.dumps(identity, indent=2, sort_keys=True),
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S)
    payload = parse_json_array(raw, step_id=_STEP_ID)
    if not payload:
        raise StageSynthError(f"{_STEP_ID}: LLM emitted an empty policies array")
    try:
        validated = _PoliciesPayload.model_validate(payload)
    except ValidationError as exc:
        raise StageSynthError(
            f"{_STEP_ID}: response failed Policy schema validation: {exc}",
        ) from exc
    policies = validated.root
    seen: set[str] = set()
    for policy in policies:
        if policy.handle in seen:
            raise StageSynthError(
                f"{_STEP_ID}: duplicate policy handle {policy.handle!r}",
            )
        seen.add(policy.handle)
    missing = _REQUIRED_HANDLES - seen
    if missing:
        raise StageSynthError(
            f"{_STEP_ID}: missing required policy handles: {sorted(missing)}",
        )
    return policies


class SynthPoliciesStep:
    """Phase 2 ``synth_policies`` step (spec §5.3).

    Reads ``identity.json``, calls the runtime's
    :class:`~harness.runtimes.LLMCompleter` exactly once, validates
    each entry against :class:`Policy`, and writes the cached payload
    as a JSON array under ``.shop_gen/stage_cache/policies.json``.

    Attributes:
        id: Step id (``synth_policies``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` referencing ``synth_identity``.
        outputs: ``.shop_gen/stage_cache/policies.json``.
        depends_on: ``[synth_identity]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the ``synth_identity`` upstream."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_UPSTREAM_ID)]
        self.outputs: list[Path] = [_OUT_POLICIES]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``policies.json`` and cache it under ``.shop_gen/stage_cache/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step always calls the LLM exactly once.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: ``identity.json`` does not exist.
            StageSynthError: The LLM response cannot be parsed into a
                valid policies array.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_policies requires a runtime with LLMCompleter; got None",
            )
        identity_path = ctx.out_dir / _IN_IDENTITY
        if not identity_path.exists():
            raise FileNotFoundError(
                f"identity.json not found at {identity_path}; run synth_identity first",
            )
        identity = _load_identity(identity_path)

        policies = synth_policies_from_identity(identity=identity, completer=ctx.runtime)

        out_path = ctx.out_dir / _OUT_POLICIES
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                [policy.model_dump(mode="json") for policy in policies],
                indent=2,
                sort_keys=True,
            )
            + "\n",
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


__all__ = [
    "SynthPoliciesStep",
    "synth_policies_from_identity",
]
