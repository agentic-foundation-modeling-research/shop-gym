"""Prompt-template loader for the Phase 2 data-synthesis steps.

Externalises the ``str.format()`` bodies that
:mod:`shop_gen.data_synth.identity` (and the M3 follow-up steps) send
to the LLM. Keeping prompts in ``.md`` files under
:mod:`shop_gen.data_synth.prompts` lets prompt engineering iterate
without touching the Python implementation.

Each file ships a short documentation header followed by an HR
divider (``---``) and the template body. The loader splits on the
first divider and returns the body verbatim; documentation above the
divider is ignored. The single-template-per-file shape mirrors what
the data-synth steps need (one prompt per step) and keeps the
contract trivially debuggable from a file viewer.

Lookups are cached so repeated calls are free; the disk read happens
lazily on first use, keeping the parent package import-safe (no I/O at
module import time).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Final

_PROMPTS_DIR: Final[Path] = Path(__file__).resolve().parent / "prompts"
_IDENTITY_FILE: Final[str] = "synth_identity.md"
_DIVIDER: Final[str] = "\n---\n"


@cache
def load_synth_identity_template() -> str:
    """Return the ``synth_identity`` ``str.format()`` body.

    The file ships a documentation header followed by ``---`` and the
    template body. The loader returns the body verbatim, stripped of
    leading / trailing blank lines.

    Returns:
        The template body. Format placeholders: ``{capabilities}``,
        ``{manual}``.

    Raises:
        FileNotFoundError: ``synth_identity.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_IDENTITY_FILE)


def _read_template_body(name: str) -> str:
    """Read ``<prompts dir>/<name>`` and return everything after the first ``---``.

    Args:
        name: File name relative to the package's ``prompts/`` directory.

    Returns:
        The body trimmed of leading / trailing blank lines.

    Raises:
        FileNotFoundError: The prompt file does not exist.
        ValueError: The file does not contain the ``---`` divider.
    """
    text = (_PROMPTS_DIR / name).read_text(encoding="utf-8")
    _, sep, body = text.partition(_DIVIDER)
    if not sep:
        raise ValueError(
            f"{name}: prompt file must contain a '---' divider separating "
            "the documentation header from the template body",
        )
    return body.strip("\n").rstrip() + "\n"


__all__ = [
    "load_synth_identity_template",
]
