"""Image-generation prompt template loader (spec §5.1.1).

Loads ``prompts/image.md`` once (cached) and renders it for each
``(handle, index)`` pair. The brand-safety hard-constraint suffix is
part of the template body — bumping :data:`PROMPT_VERSION` busts every
cache entry on the next run when the constraint text is edited.

Module is import-safe: no I/O at import (the read is deferred to first
:func:`render_image_prompt` call via :func:`functools.cache`).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Final

PROMPT_VERSION: Final[int] = 1
"""Version of ``prompts/image.md``. Bump on any edit to the brand-safety
suffix or the body so cache keys are invalidated downstream."""

_PROMPT_FILE: Final[Path] = Path(__file__).resolve().parent.parent / "prompts" / "image.md"
_DIVIDER: Final[str] = "\n---\n"


def render_image_prompt(*, title: str, category: str) -> str:
    """Return the rendered prompt for one product image.

    Args:
        title: Product display title.
        category: Category label (collection title or product type).

    Returns:
        The rendered prompt with the brand-safety suffix appended.

    Raises:
        FileNotFoundError: ``prompts/image.md`` is missing.
        ValueError: The prompt file is missing the ``---`` divider.
    """
    body = _load_template_body()
    return body.format(title=title, category=category)


@cache
def _load_template_body() -> str:
    """Read the prompt body once and cache it for subsequent renders."""
    text = _PROMPT_FILE.read_text(encoding="utf-8")
    _, sep, body = text.partition(_DIVIDER)
    if not sep:
        raise ValueError(
            f"{_PROMPT_FILE.name}: prompt file must contain a '---' divider "
            "separating the documentation header from the template body",
        )
    return body.strip("\n")


__all__ = ["PROMPT_VERSION", "render_image_prompt"]
