"""``synth_identity`` — Phase 2 brand-identity synthesis (spec §5.3).

Single-LLM-call step that derives the brand-free identity fields
(``descriptor``, ``tone``, ``currency``, ``country``) from the merged
``manual/`` directory and assigns ``name`` deterministically by hashing
the seed paths plus the LLM-supplied descriptor against the curated
fake-brand allowlist (spec §5.6).

The deterministic name pick is the spec's answer to the "single
identity from N seeds" question (§5.3): the LLM authors a single
coherent descriptor / tone vector that fits the merged capabilities,
and the orchestrator then computes
``index = sha256(seeds + descriptor) mod len(allowlist) -> sorted
allowlist[index]`` so re-runs against the same seeds + descriptor
always pick the same brand name.

Step contract (spec §5.7.1):

* ``id``: ``synth_identity``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_gen.steps.base.StepInput` per upstream
  manual-merge step (multi-seed: ``merge_capabilities`` +
  ``merge_manual_prose``; single-seed: ``copy_seed_manual``). The
  step's fingerprint cascades from those upstream fingerprints —
  there is no need to also declare ``FileInput`` references on the
  ``manual/*`` files because the upstream steps own those bytes.
* ``outputs``: ``identity.json``.
* ``depends_on``: same upstream ids as :attr:`inputs`.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness.runtimes import LLMCompleter
from shop_gen.brands.allowlist import Allowlist, load_allowlist
from shop_gen.data_synth.prompts import load_synth_identity_template
from shop_gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "synth_identity"
_STEP_VERSION: Final[int] = 1

_OUT_IDENTITY: Final[Path] = Path("identity.json")
_IN_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"
_IN_MANUAL: Final[Path] = Path("manual") / "manual.md"

_LLM_TIMEOUT_S: Final[float] = 60.0

# The LLM may wrap its JSON in a Markdown code fence even when the
# prompt forbids it. Strip a single leading / trailing fence pair.
_FENCE_OPEN_RE: Final[re.Pattern[str]] = re.compile(r"^```(?:json)?\s*\n", re.IGNORECASE)
_FENCE_CLOSE_RE: Final[re.Pattern[str]] = re.compile(r"\n```\s*$")

_CURRENCY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{3}$")
_COUNTRY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{2}$")


class IdentitySynthError(ValueError):
    """Raised when the LLM response cannot be parsed into a valid :class:`Identity`."""


class Identity(BaseModel):
    """Synthesized fake-brand identity for one ``shop_gen`` run.

    Mirrors the published artifact ``<out_dir>/identity.json`` (spec
    §4.1 + §5.3). Closed schema — extra fields are rejected so a future
    field addition cannot silently leak through.

    Attributes:
        name: Brand name picked deterministically from the fake-brand
            allowlist (spec §5.6). Never invented by the LLM.
        descriptor: Short brand-free phrase (max 12 words) describing
            the storefront. Conditioned on the merged tone tags.
        tone: 1-3 short tone tags capturing brand voice.
        currency: ISO 4217 alpha-3 code (e.g. ``USD``).
        country: ISO 3166-1 alpha-2 code (e.g. ``US``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    descriptor: str = Field(min_length=1)
    tone: list[str] = Field(min_length=1, max_length=3)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    country: str = Field(pattern=r"^[A-Z]{2}$")


def synth_identity_from_manual(
    *,
    capabilities: dict[str, Any],
    manual: str,
    seeds: Sequence[Path],
    completer: LLMCompleter,
    allowlist: Allowlist | None = None,
) -> Identity:
    """Synthesize one :class:`Identity` from the merged ``manual/``.

    Calls ``completer`` exactly once with the rendered prompt, parses
    the returned JSON into the four LLM-authored fields, then assigns
    ``name`` deterministically from the allowlist via
    :func:`pick_name_from_allowlist`.

    Args:
        capabilities: Decoded ``manual/capabilities.json`` document.
        manual: Raw ``manual/manual.md`` body.
        seeds: Seed directory paths from
            :class:`~shop_gen.config.ShopGenConfig`. Hashed (via their
            POSIX rendering) into the deterministic name pick so the
            same input set always selects the same brand.
        completer: One-shot LLM completer (typically the runtime's
            :class:`~harness.runtimes.LLMCompleter`).
        allowlist: Optional pre-loaded allowlist. Defaults to the
            in-repo ``fake_brands.json``.

    Returns:
        A validated :class:`Identity`.

    Raises:
        IdentitySynthError: The LLM returned an empty response,
            non-JSON output, an out-of-shape JSON object, or values
            that fail :class:`Identity` schema validation.
    """
    target = allowlist if allowlist is not None else load_allowlist()
    prompt = load_synth_identity_template().format(
        capabilities=json.dumps(capabilities, indent=2, sort_keys=True),
        manual=manual.rstrip(),
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S).strip()
    if not raw:
        raise IdentitySynthError("synth_identity: LLM returned an empty response")
    payload = _parse_llm_json(raw)
    descriptor = _require_str(payload, "descriptor")
    tone = _require_str_list(payload, "tone")
    currency = _require_str(payload, "currency").upper()
    country = _require_str(payload, "country").upper()
    if not _CURRENCY_RE.match(currency):
        raise IdentitySynthError(
            f"synth_identity: 'currency' must be ISO 4217 alpha-3, got {currency!r}",
        )
    if not _COUNTRY_RE.match(country):
        raise IdentitySynthError(
            f"synth_identity: 'country' must be ISO 3166-1 alpha-2, got {country!r}",
        )
    name = pick_name_from_allowlist(seeds=seeds, descriptor=descriptor, allowlist=target)
    try:
        return Identity(
            name=name,
            descriptor=descriptor,
            tone=tone,
            currency=currency,
            country=country,
        )
    except ValidationError as exc:
        raise IdentitySynthError(
            f"synth_identity: response failed Identity schema validation: {exc}",
        ) from exc


def pick_name_from_allowlist(
    *,
    seeds: Sequence[Path],
    descriptor: str,
    allowlist: Allowlist,
) -> str:
    """Return the allowlist brand selected deterministically for ``(seeds, descriptor)``.

    Implements the spec §5.3 / §5.6 recipe: hash the seed POSIX paths
    plus a NUL separator plus the descriptor with sha256, take the
    integer value of the digest modulo the allowlist size, and index
    into the brands sorted lexicographically. Sorting fixes the
    ordering even if ``fake_brands.json`` shuffles its entries
    between releases.

    Args:
        seeds: Seed directory paths from
            :class:`~shop_gen.config.ShopGenConfig`. The same seeds in
            the same order always produce the same hash.
        descriptor: LLM-supplied brand descriptor string.
        allowlist: Allowlist to pick from. Must contain at least one
            brand.

    Returns:
        One of ``allowlist.brands``, picked deterministically.

    Raises:
        ValueError: ``allowlist.brands`` is empty.
    """
    sorted_brands = sorted(allowlist.brands)
    if not sorted_brands:
        raise ValueError("pick_name_from_allowlist: allowlist contains no brands")
    seeds_str = "\0".join(seed.as_posix() for seed in seeds)
    payload = f"{seeds_str}\0{descriptor}".encode()
    digest = hashlib.sha256(payload).digest()
    index = int.from_bytes(digest, "big") % len(sorted_brands)
    return sorted_brands[index]


class SynthIdentityStep:
    """Phase 2 ``synth_identity`` step (spec §5.3).

    Reads the merged ``manual/manual.md`` + ``manual/capabilities.json``,
    calls the runtime's :class:`~harness.runtimes.LLMCompleter` exactly
    once, then writes ``identity.json`` with the LLM-authored fields
    plus a deterministically-picked allowlist name.

    Attributes:
        id: Step id (``synth_identity``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` per upstream manual-merge step.
        outputs: ``identity.json``.
        depends_on: Same upstream ids as :attr:`inputs`.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self, *, manual_step_ids: Sequence[str] = ()) -> None:
        """Build the step bound to the upstream manual-merge step ids.

        Args:
            manual_step_ids: Upstream step ids that produce the merged
                ``manual/`` directory. ``("merge_capabilities",
                "merge_manual_prose")`` for multi-seed runs;
                ``("copy_seed_manual",)`` for single-seed runs. Empty
                in the listing branch (``--list-steps`` does not bind
                to a specific seed count); the placeholder still
                surfaces the step id in
                :func:`shop_gen.pipeline.list_steps`.
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=sid) for sid in manual_step_ids]
        self.outputs: list[Path] = [_OUT_IDENTITY]
        self.depends_on: list[str] = list(manual_step_ids)
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Synthesize ``identity.json`` from the merged manual.

        Args:
            ctx: Execution context. ``ctx.runtime`` is required — the
                step always calls the LLM exactly once.

        Raises:
            ValueError: ``ctx.runtime`` is ``None``.
            FileNotFoundError: The upstream ``manual/manual.md`` or
                ``manual/capabilities.json`` does not exist.
            IdentitySynthError: The LLM response cannot be parsed into a
                valid :class:`Identity`.
        """
        if ctx.runtime is None:
            raise ValueError(
                "synth_identity requires a runtime with LLMCompleter; got None",
            )
        capabilities_path = ctx.out_dir / _IN_CAPABILITIES
        manual_path = ctx.out_dir / _IN_MANUAL
        if not capabilities_path.exists():
            raise FileNotFoundError(
                f"merged capabilities not found at {capabilities_path}; "
                "run the manual-merge phase first",
            )
        if not manual_path.exists():
            raise FileNotFoundError(
                f"merged manual not found at {manual_path}; run the manual-merge phase first",
            )
        capabilities = _load_capabilities(capabilities_path)
        manual = manual_path.read_text(encoding="utf-8")

        identity = synth_identity_from_manual(
            capabilities=capabilities,
            manual=manual,
            seeds=ctx.config.seeds,
            completer=ctx.runtime,
        )

        out_path = ctx.out_dir / _OUT_IDENTITY
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(identity.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _load_capabilities(path: Path) -> dict[str, Any]:
    """Read ``manual/capabilities.json`` as a plain dict for the prompt.

    The closed-schema validation already happened upstream
    (:class:`shop_gen.manual_merge.capabilities.MergeCapabilitiesStep`
    or, in the single-seed branch, the seed itself). This step only
    needs the decoded payload to render the prompt, so a minimal
    JSON-object check is sufficient.
    """
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IdentitySynthError(
            f"merged capabilities at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise IdentitySynthError(
            f"merged capabilities at {path} must be a JSON object, got {type(raw).__name__}",
        )
    return cast("dict[str, Any]", raw)


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Strip optional Markdown code fences and decode the LLM's JSON.

    The prompt forbids fences but production LLMs occasionally ignore
    that instruction. A single leading ```` ```json ```` / ```` ``` ````
    fence and its matching closer are tolerated; anything else raises.
    """
    body = _FENCE_OPEN_RE.sub("", raw, count=1)
    body = _FENCE_CLOSE_RE.sub("", body, count=1).strip()
    try:
        decoded: Any = json.loads(body)
    except json.JSONDecodeError as exc:
        raise IdentitySynthError(
            f"synth_identity: LLM response is not valid JSON: {exc}",
        ) from exc
    if not isinstance(decoded, dict):
        raise IdentitySynthError(
            f"synth_identity: LLM response must be a JSON object, got {type(decoded).__name__}",
        )
    return cast("dict[str, Any]", decoded)


def _require_str(payload: dict[str, Any], key: str) -> str:
    """Pull a non-empty string field out of the LLM's JSON object."""
    value: Any = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IdentitySynthError(
            f"synth_identity: LLM response missing non-empty string {key!r}",
        )
    return value.strip()


def _require_str_list(payload: dict[str, Any], key: str) -> list[str]:
    """Pull a non-empty list-of-strings field out of the LLM's JSON object."""
    value: Any = payload.get(key)
    if not isinstance(value, list) or not value:
        raise IdentitySynthError(
            f"synth_identity: LLM response missing non-empty list {key!r}",
        )
    items = cast("list[Any]", value)
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise IdentitySynthError(
                f"synth_identity: LLM response {key!r} must contain non-empty strings",
            )
        cleaned.append(item.strip())
    return cleaned


__all__ = [
    "Identity",
    "IdentitySynthError",
    "SynthIdentityStep",
    "pick_name_from_allowlist",
    "synth_identity_from_manual",
]
