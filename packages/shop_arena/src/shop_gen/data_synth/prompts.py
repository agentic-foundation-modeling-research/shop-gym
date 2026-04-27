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
_STORE_FILE: Final[str] = "synth_store.md"
_PAGES_FILE: Final[str] = "synth_pages.md"
_POLICIES_FILE: Final[str] = "synth_policies.md"
_COLLECTIONS_FILE: Final[str] = "synth_collections.md"
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


@cache
def load_synth_store_template() -> str:
    """Return the ``synth_store`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{identity}``.

    Raises:
        FileNotFoundError: ``synth_store.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_STORE_FILE)


@cache
def load_synth_pages_template() -> str:
    """Return the ``synth_pages`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{identity}``,
        ``{capabilities}``.

    Raises:
        FileNotFoundError: ``synth_pages.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_PAGES_FILE)


@cache
def load_synth_policies_template() -> str:
    """Return the ``synth_policies`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{identity}``.

    Raises:
        FileNotFoundError: ``synth_policies.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_POLICIES_FILE)


@cache
def load_synth_collections_template() -> str:
    """Return the ``synth_collections`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{identity}``,
        ``{capabilities}``, ``{stats}``, ``{target_count}``.

    Raises:
        FileNotFoundError: ``synth_collections.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_COLLECTIONS_FILE)


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
    "load_synth_collections_template",
    "load_synth_identity_template",
    "load_synth_pages_template",
    "load_synth_policies_template",
    "load_synth_store_template",
]
