"""Closed-enum screenshot rubric: vision call, schema validate, persist artifact.

This module owns the M2 ``observation/<bucket>.rubric.json`` writer (spec
§5.3 / impl-plan M2).  It glues three pieces together:

* :data:`RUBRIC_RESPONSE_SCHEMA` — JSON schema sent to the vision model.
  Mirrors :data:`shop_arena.env_eval.schema.metrics.RUBRIC_CATEGORIES` exactly and
  closes ``additionalProperties`` so OpenAI strict mode and Anthropic
  ``tool_use`` both reject unknown keys.  Every category is required so the
  schema works under OpenAI's strict ``json_schema`` mode (which mandates an
  exhaustive ``required`` list); the prompt explicitly permits zero-valued
  keys for absent categories.
* :func:`run_rubric` — issues one vision call, validates the parsed mapping
  against :class:`shop_arena.env_eval.schema.metrics.Rubric` (closed pydantic
  schema, ``extra="forbid"``), and returns a fully populated
  :class:`RubricArtifact`.  Parse failures (missing tool-use block, invalid
  JSON, schema rejection) collapse to zero counts plus non-empty
  ``parse_errors`` instead of raising — successful rubric runs are the
  reproducibility boundary; failures are quarantined into the artifact for
  audit, not propagated.
* :func:`write_rubric_artifact` — deterministic JSON writer (two-space
  indent, trailing newline, sorted keys) so the artifact is byte-stable
  across reruns.

The module deliberately holds no provider knowledge — it accepts any
:class:`shop_arena.util._llm.LLMVisionClient`, which lets pipeline code
inject a fake client in tests without hitting the network.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shop_arena.env_eval.schema.metrics import RUBRIC_CATEGORIES, Rubric
from shop_arena.util._llm import (
    DEFAULT_RUBRIC_TEMPERATURE,
    LLMVisionClient,
    VisionResponse,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "RUBRIC_PROMPT_VERSION",
    "RUBRIC_RESPONSE_SCHEMA",
    "RubricArtifact",
    "build_rubric_prompt_payload",
    "load_rubric_prompt",
    "run_rubric",
    "write_rubric_artifact",
]

#: Version of the rubric prompt + response schema (spec §5.3, impl-plan M2).
#: Bumped on any contract-affecting change (prompt body, response enum,
#: or input shape) and persisted in every ``*.rubric.json`` so cohorts of
#: artifacts can be filtered by version.  ``0.3`` adds a state-node mode
#: that takes both the pre- and post-action screenshots (and drops the
#: axtree dump) so the model can disambiguate transient overlays from
#: their underlying page; URL nodes still receive a single screenshot
#: plus the page's axtree text exactly as in ``0.2``.  Counts always
#: describe the post-action page — the pre image is context only.
#: ``0.2`` covered the URL-only flow that combined screenshot + axtree;
#: ``0.1`` was screenshot-alone and predates the axtree augmentation.
#: Older artifacts should be regenerated rather than compared head-to-
#: head with ``0.3`` outputs.
RUBRIC_PROMPT_VERSION: Final[str] = "0.3"

#: JSON schema the vision client forwards to the model.  Closed enum: every
#: :data:`RUBRIC_CATEGORIES` key is required and ``additionalProperties`` is
#: forbidden, matching the pydantic :class:`Rubric` model used for parse-time
#: validation.
RUBRIC_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {category: {"type": "integer", "minimum": 0} for category in RUBRIC_CATEGORIES},
    "required": list(RUBRIC_CATEGORIES),
    "additionalProperties": False,
}

#: importlib package + filename the prompt body is loaded from.
_PROMPT_PACKAGE: Final[str] = "shop_arena.env_eval.observation"
_PROMPT_FILENAME: Final[str] = "prompt.md"

#: Divider that separates the documentation header from the prompt body in
#: ``prompt.md``.  Mirrored by ``test_rubric_prompt`` so the loader contract
#: stays in lockstep with the asset.
_PROMPT_DIVIDER: Final[str] = "\n---\n"

#: Header used by :func:`build_rubric_prompt_payload` to attach the page's
#: axtree text to the prompt.  Persisted in the prompt assets so a single
#: divider string is the source of truth across the loader, the renderer,
#: and any test that inspects the on-wire prompt body.
_AXTREE_HEADER: Final[str] = "--- AXTREE ---"


def load_rubric_prompt() -> str:
    """Return the rubric prompt body (text after the first ``---`` divider).

    The on-disk asset is a Markdown file: an internal documentation header,
    a single ``---`` divider, and the verbatim prompt body the model sees.
    Loading collapses the trailing whitespace into one final newline so the
    payload is byte-stable regardless of the file's final-newline state.

    Returns:
        Prompt body as a UTF-8 string.

    Raises:
        RuntimeError: ``prompt.md`` is missing the ``---`` divider that
            separates documentation from the prompt body.
    """
    text = resources.files(_PROMPT_PACKAGE).joinpath(_PROMPT_FILENAME).read_text(encoding="utf-8")
    if _PROMPT_DIVIDER not in text:
        raise RuntimeError(
            f"{_PROMPT_FILENAME} is missing the required '---' divider between "
            "the documentation header and the prompt body",
        )
    body = text.split(_PROMPT_DIVIDER, 1)[1]
    return body.strip() + "\n"


class RubricArtifact(BaseModel):
    """Closed schema for a single ``observation/<bucket>.rubric.json`` file.

    Mirrors the impl-plan M2 task list exactly: every artifact records
    ``prompt_version`` / ``model`` / ``temperature`` / ``counts`` /
    ``raw_response`` / ``parse_errors``.  The model is frozen + closed so
    drift in the artifact format (e.g. an unexpected key from a future M5
    state-namer artifact) fails loudly at parse time.

    Attributes:
        prompt_version: Version of the rubric prompt + schema that produced
            ``counts`` (currently :data:`RUBRIC_PROMPT_VERSION`).
        model: Model id reported by the vision client (e.g.
            ``"claude-sonnet-4-6"``, ``"gpt-4o"``).
        temperature: Sampling temperature passed to the vision client.
            Provider-side fixed-temperature models still record the
            requested value; the actual on-wire temperature is the
            provider default.
        counts: Closed-enum :class:`Rubric` counts (zeros when the response
            could not be validated; see ``parse_errors``).
        raw_response: Provider-agnostic textual record of the response,
            persisted verbatim for audit.
        parse_errors: Tuple of human-readable parse errors.  Empty on a
            clean call; populated when the response failed JSON decoding,
            tool-use extraction, or closed-schema validation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0.0)
    counts: Rubric
    raw_response: str
    parse_errors: tuple[str, ...] = ()


def build_rubric_prompt_payload(
    axtree_text: str,
    base_prompt: str | None = None,
) -> str:
    """Return the prompt body augmented with the page's axtree text.

    The state-namer module follows the same pattern: the static prompt body
    loaded from disk holds the model's instructions, and per-call context is
    appended below a fixed delimiter so callers can keep the schema and the
    asset stable.

    Args:
        axtree_text: Deterministic text dump of the page's accessibility
            tree (the same string written to ``<bucket>.axtree.txt`` by the
            pipeline).  Empty strings are accepted for the rare case where
            the renderer produced nothing (an axtree without a root); the
            section header is still emitted so the model sees a stable
            prompt shape.
        base_prompt: Override for the bundled prompt body.  Defaults to
            :func:`load_rubric_prompt`.

    Returns:
        ``"<base_prompt>\\n\\n--- AXTREE ---\\n<axtree_text>\\n"``
    """
    body = base_prompt if base_prompt is not None else load_rubric_prompt()
    return body.rstrip() + "\n\n" + _AXTREE_HEADER + "\n" + axtree_text.rstrip() + "\n"


def run_rubric(
    client: LLMVisionClient,
    images: Sequence[bytes],
    *,
    axtree_text: str,
    temperature: float = DEFAULT_RUBRIC_TEMPERATURE,
    prompt: str | None = None,
) -> RubricArtifact:
    """Run the rubric against ``client`` and return its artifact.

    The function never raises on a malformed model response — callers that
    persist the artifact (the M2 pipeline) want a schema-valid file on disk
    even when the model emitted garbage, so parse failures collapse to zero
    counts plus ``parse_errors``.  Configuration errors (missing API keys,
    text-only model dispatch) still bubble up from the client because they
    are caller bugs, not data quality issues.

    Args:
        client: Any concrete :class:`LLMVisionClient`.  Tests inject a fake.
        images: PNG-encoded screenshot bytes in the order the model should
            see them.  URL nodes pass a 1-tuple ``(post_png,)`` together
            with a non-empty ``axtree_text`` so the model can reach
            below-the-fold structure.  Stateful nodes pass a 2-tuple
            ``(pre_png, post_png)`` and an empty ``axtree_text``: the pre
            image disambiguates an overlay from the underlying page, and
            the axtree is dropped because state-overlay axtrees double the
            input length without adding signal a second screenshot does
            not already provide.  An empty sequence raises ``ValueError``
            via the underlying client.
        axtree_text: Deterministic text dump of the post page's axtree
            (the same string the pipeline writes to
            ``<bucket>.axtree.txt``).  Pass an empty string to omit the
            axtree section — the section header is still emitted so the
            on-wire prompt shape is stable.
        temperature: Sampling temperature forwarded to the client; defaults
            to :data:`DEFAULT_RUBRIC_TEMPERATURE` (``0.0``) per spec §5.3.
        prompt: Override for the prompt body.  Defaults to the bundled
            ``prompt.md`` (loaded via :func:`load_rubric_prompt`).

    Returns:
        Populated :class:`RubricArtifact`.  ``parse_errors`` is empty on a
        clean call; on any failure the ``counts`` field is a zero
        :class:`Rubric` and ``parse_errors`` describes what went wrong.
    """
    body = build_rubric_prompt_payload(axtree_text, base_prompt=prompt)
    response = client.call(
        prompt=body,
        images=tuple(images),
        schema=RUBRIC_RESPONSE_SCHEMA,
        temperature=temperature,
    )
    counts, parse_errors = _validate_counts(response)
    return RubricArtifact(
        prompt_version=RUBRIC_PROMPT_VERSION,
        model=client.model,
        temperature=temperature,
        counts=counts,
        raw_response=response.raw_response,
        parse_errors=parse_errors,
    )


def write_rubric_artifact(artifact: RubricArtifact, path: Path) -> Path:
    """Serialize ``artifact`` to ``path`` as deterministic JSON.

    Output format mirrors the other run-directory artifacts (pages.json,
    metrics.json, manifest.json): two-space indent, sorted top-level keys,
    trailing newline.  Sorting makes the file byte-stable across pydantic
    minor versions whose model-dump key ordering may shift.

    Args:
        artifact: Validated :class:`RubricArtifact`.
        path: Destination path.  Parent directories must already exist.

    Returns:
        The same ``path`` as a :class:`pathlib.Path`, for chaining.
    """
    payload = artifact.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _validate_counts(response: VisionResponse) -> tuple[Rubric, tuple[str, ...]]:
    """Validate ``response.parsed`` against the closed :class:`Rubric` schema.

    Three failure modes collapse to a zero :class:`Rubric` plus non-empty
    parse errors:

    * the client could not parse a response at all (``parsed is None``),
    * the closed pydantic schema rejected the response (extra keys, wrong
      types, negative counts),
    * the JSON root was not an object (already surfaced upstream as a
      parse error from the client).

    Returns:
        ``(counts, parse_errors)`` — ``counts`` is the validated rubric on
        success and a zero :class:`Rubric` on any failure.
    """
    if response.parsed is None:
        return Rubric(), response.parse_errors
    try:
        counts = Rubric.model_validate(dict(response.parsed))
    except ValidationError as exc:
        return Rubric(), tuple(_combine_errors(response.parse_errors, exc))
    return counts, response.parse_errors


def _combine_errors(
    upstream: Sequence[str],
    exc: ValidationError,
) -> list[str]:
    """Append schema-validation errors to ``upstream`` in human-readable form."""
    out = list(upstream)
    for err in exc.errors():
        loc_parts = [str(part) for part in err["loc"]]
        loc = ".".join(loc_parts) if loc_parts else "<root>"
        out.append(f"rubric schema validation: {loc}: {err['msg']}")
    return out
