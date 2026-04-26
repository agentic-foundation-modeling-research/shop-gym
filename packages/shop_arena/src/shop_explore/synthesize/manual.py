"""``manual.md`` rendering for §5.10 synthesis.

Builds the merge prompt and calls the LLM exactly once. An empty / too
short response or a raised exception is fatal — the caller raises
:class:`shop_explore.synthesize.core.SynthesisError` and no manual.md is
emitted (spec §5.10). There is no silent fallback to deterministic
concatenation; that path masked LLM-client misconfiguration in earlier
revisions and was removed deliberately.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from shop_explore.capabilities import Capabilities

if TYPE_CHECKING:
    from shop_explore.synthesize.core import LLMClient

MANUAL_MIN_CHARS = 200
"""Minimum stripped length of an LLM-rendered manual; shorter is fatal (spec §5.10)."""


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
) -> str:
    """Run the single LLM merge call and return the rendered manual.

    Args:
        llm: Client used for the single manual-merge completion.
        manual_prompt: Merge prompt body owned by ``shop_explore.prompts``.
        capabilities: Merged capabilities document, embedded in the prompt.
        parts_concat: Concatenated per-task ``parts/*.md`` body, also
            embedded in the prompt.

    Returns:
        The model's text completion, with a trailing newline appended if
        the response did not already end in one.

    Raises:
        ManualRenderError: If the LLM returns a response shorter than
            :data:`MANUAL_MIN_CHARS`. Exceptions raised by ``llm.complete``
            propagate unchanged so the caller can distinguish wire-level
            failures from short responses.
    """
    full_prompt = (
        manual_prompt.rstrip("\n")
        + "\n\n## Capabilities\n\n```json\n"
        + capabilities.model_dump_json(indent=2)
        + "\n```\n\n## Per-task parts\n\n"
        + parts_concat
    )
    response = llm.complete(full_prompt)
    if len(response.strip()) < MANUAL_MIN_CHARS:
        raise ManualRenderError(
            f"LLM returned a manual shorter than {MANUAL_MIN_CHARS} chars "
            f"(stripped length: {len(response.strip())})"
        )
    if not response.endswith("\n"):
        response = response + "\n"
    return response


class ManualRenderError(RuntimeError):
    """Raised when the manual-merge LLM call returns an unusable response.

    Currently only triggered by sub-:data:`MANUAL_MIN_CHARS` responses;
    wire-level failures from ``llm.complete`` propagate unchanged.
    """
