"""``manual.md`` rendering for §5.10 synthesis.

Builds the merge prompt, calls the LLM exactly once, and falls back to
deterministic concatenation of ``parts/*.md`` when the response is
empty / too short / the client raises (spec §5.10).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from shop_explore.capabilities import Capabilities

if TYPE_CHECKING:
    from shop_explore.synthesize.core import LLMClient

MANUAL_MIN_CHARS = 200
"""Minimum stripped length of an LLM-rendered manual; shorter falls back (spec §5.10)."""


def concat_parts(parts_dir: Path) -> str:
    """Return ``parts/*.md`` concatenated in sorted filename order.

    Each part is right-trimmed of trailing newlines and joined with a
    blank line so the result reads as a single document. The output
    always ends with a single newline.
    """
    chunks: list[str] = []
    for path in sorted(parts_dir.glob("*.md")):
        chunks.append(path.read_text(encoding="utf-8").rstrip("\n"))
    if not chunks:
        return ""
    return "\n\n".join(chunks).rstrip("\n") + "\n"


def render_manual(
    *,
    llm: LLMClient,
    manual_prompt: str,
    capabilities: Capabilities,
    parts_concat: str,
) -> tuple[str, bool]:
    """One LLM call; on short / empty / failed response, fall back.

    Returns the manual text plus a boolean indicating whether we used
    the deterministic fallback. ``True`` matches
    ``manifest.manual_fallback`` per spec §5.10.
    """
    full_prompt = (
        manual_prompt.rstrip("\n")
        + "\n\n## Capabilities\n\n```json\n"
        + capabilities.model_dump_json(indent=2)
        + "\n```\n\n## Per-task parts\n\n"
        + parts_concat
    )
    try:
        response = llm.complete(full_prompt)
    except Exception:  # fall back on any LLM client failure
        # Spec §5.10 only enumerates the "empty / < 200 chars" case
        # explicitly, but a raised exception is the same observable
        # outcome (no usable manual text). Surface it through the
        # fallback path so we always emit ``manual.md``.
        return parts_concat, True

    if len(response.strip()) < MANUAL_MIN_CHARS:
        return parts_concat, True
    if not response.endswith("\n"):
        response = response + "\n"
    return response, False
