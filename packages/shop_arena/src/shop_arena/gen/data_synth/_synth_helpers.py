"""Shared plumbing for Phase 2 single-LLM-call synthesis steps.

Externalises the JSON-parse / code-fence-strip plumbing shared by
:mod:`shop_arena.gen.data_synth.store`, :mod:`shop_arena.gen.data_synth.pages`, and
:mod:`shop_arena.gen.data_synth.policies`. Each of those steps issues exactly
one LLM completion that emits a schema-shaped JSON document; this module
owns the boilerplate that converts the raw response into a typed
``dict`` / ``list`` ready for pydantic validation.

:mod:`shop_arena.gen.data_synth.identity` predates this helper and keeps its
own private helpers — it raises :class:`IdentitySynthError` rather than
:class:`StageSynthError` and the surgical-changes rule keeps that path
untouched.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final, cast

_FENCE_OPEN_RE: Final[re.Pattern[str]] = re.compile(r"^```(?:json)?\s*\n", re.IGNORECASE)
"""Match a single leading ```` ```json ``` / ```` ``` ``` Markdown fence."""

_FENCE_CLOSE_RE: Final[re.Pattern[str]] = re.compile(r"\n```\s*$")
"""Match a single trailing ```` ``` ``` Markdown fence."""


class StageSynthError(ValueError):
    """Raised when a Phase 2 stage step cannot parse its LLM response."""


def parse_json_object(raw: str, *, step_id: str) -> dict[str, Any]:
    """Decode ``raw`` as a JSON object, tolerating one wrapping code fence.

    Args:
        raw: Raw LLM completion body. Surrounding whitespace and a single
            ``` json ``` fence pair (if present) are stripped first.
        step_id: Step id used in error messages so the failure points at
            the offending step without ambiguity.

    Returns:
        The decoded JSON object.

    Raises:
        StageSynthError: ``raw`` is empty, not valid JSON, or not a
            top-level object.
    """
    body = _strip_fences_or_raise(raw, step_id=step_id)
    decoded = _decode_json(body, step_id=step_id)
    if not isinstance(decoded, dict):
        raise StageSynthError(
            f"{step_id}: LLM response must be a JSON object, got {type(decoded).__name__}",
        )
    return cast("dict[str, Any]", decoded)


def parse_json_array(raw: str, *, step_id: str) -> list[Any]:
    """Decode ``raw`` as a JSON array, tolerating one wrapping code fence.

    Args:
        raw: Raw LLM completion body. Surrounding whitespace and a single
            ``` json ``` fence pair (if present) are stripped first.
        step_id: Step id used in error messages so the failure points at
            the offending step without ambiguity.

    Returns:
        The decoded JSON array.

    Raises:
        StageSynthError: ``raw`` is empty, not valid JSON, or not a
            top-level array.
    """
    body = _strip_fences_or_raise(raw, step_id=step_id)
    decoded = _decode_json(body, step_id=step_id)
    if not isinstance(decoded, list):
        raise StageSynthError(
            f"{step_id}: LLM response must be a JSON array, got {type(decoded).__name__}",
        )
    return cast("list[Any]", decoded)


def _strip_fences_or_raise(raw: str, *, step_id: str) -> str:
    """Strip surrounding whitespace + an optional Markdown code fence."""
    stripped = raw.strip()
    if not stripped:
        raise StageSynthError(f"{step_id}: LLM returned an empty response")
    body = _FENCE_OPEN_RE.sub("", stripped, count=1)
    body = _FENCE_CLOSE_RE.sub("", body, count=1).strip()
    if not body:
        raise StageSynthError(f"{step_id}: LLM returned an empty response")
    return body


def _decode_json(body: str, *, step_id: str) -> Any:
    """``json.loads`` with a uniform :class:`StageSynthError` wrapper."""
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        snippet = _error_snippet(body, exc.pos)
        raise StageSynthError(
            f"{step_id}: LLM response is not valid JSON: {exc}; context: {snippet}",
        ) from exc


def _error_snippet(body: str, pos: int, *, radius: int = 60) -> str:
    """Return ``body[pos-radius:pos+radius]`` with the offending byte marked.

    Used to enrich :class:`json.JSONDecodeError` messages so a stage
    failure shows what the LLM actually emitted around the offending
    position. The marker is ``>>><<<`` placed around ``body[pos]``.
    """
    start = max(0, pos - radius)
    end = min(len(body), pos + radius)
    if pos < 0 or pos >= len(body):
        return repr(body[start:end])
    before = body[start:pos]
    here = body[pos]
    after = body[pos + 1 : end]
    return repr(f"{before}>>>{here}<<<{after}")


__all__ = [
    "StageSynthError",
    "parse_json_array",
    "parse_json_object",
]
