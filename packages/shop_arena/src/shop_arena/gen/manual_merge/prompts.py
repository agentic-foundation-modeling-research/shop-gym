"""Prompt-template loader for the Phase 1 manual-merge sub-DAG.

Externalises the Python ``str.format()`` bodies that
:mod:`shop_arena.gen.manual_merge.capabilities` and
:mod:`shop_arena.gen.manual_merge.prose` send to the LLM. Keeping the prompts
in `.md` files (under :mod:`shop_arena.gen.manual_merge.prompts` package
directory) lets prompt engineering iterate without touching the Python
implementation.

Two files live next to this module:

* ``merge_capabilities_tiebreak.md`` — bundles the ``descriptor`` and
  ``layout`` sub-templates exposed by
  :func:`load_capabilities_tiebreak_templates`. The file is split on
  H2 headings; body text before the first H2 is treated as
  documentation and ignored.
* ``merge_manual_prose.md`` — single template body returned verbatim
  by :func:`load_prose_section_template`.

Lookups are cached so repeated calls are free; the disk read happens
lazily on first use, keeping the parent package import-safe (no I/O at
module import time).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Final

_PROMPTS_DIR: Final[Path] = Path(__file__).resolve().parent / "prompts"
_TIEBREAK_FILE: Final[str] = "merge_capabilities_tiebreak.md"
_PROSE_FILE: Final[str] = "merge_manual_prose.md"

_CAPABILITIES_TIEBREAK_TEMPLATES: Final[tuple[str, ...]] = ("descriptor", "layout")

_H2_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^##\s+(?P<name>\S+)\s*$",
    re.MULTILINE,
)


@cache
def load_capabilities_tiebreak_templates() -> dict[str, str]:
    """Return the named sub-templates from ``merge_capabilities_tiebreak.md``.

    The file is split on H2 headings (``## name``); each section's body
    becomes the template for its name. Both ``descriptor`` and
    ``layout`` must be present — a missing entry indicates the prompt
    file was edited away from the documented contract and is treated as
    a programmer error.

    Returns:
        Mapping from sub-template name to the ``str.format()`` body.
        The mapping is cached; callers must not mutate it.

    Raises:
        FileNotFoundError: ``merge_capabilities_tiebreak.md`` is missing.
        ValueError: The file does not declare the required H2 sections.
    """
    text = _read_prompt_file(_TIEBREAK_FILE)
    sections = _split_h2_sections(text)
    missing = [name for name in _CAPABILITIES_TIEBREAK_TEMPLATES if name not in sections]
    if missing:
        raise ValueError(
            f"{_TIEBREAK_FILE}: missing required template section(s): {missing}",
        )
    return {name: sections[name] for name in _CAPABILITIES_TIEBREAK_TEMPLATES}


@cache
def load_prose_section_template() -> str:
    """Return the per-section prose-merge template.

    The whole file body is the template — there is no header / framing
    convention, so the loader just reads and returns it verbatim.

    Returns:
        The ``str.format()`` body for one ``## {section}`` merge call.

    Raises:
        FileNotFoundError: ``merge_manual_prose.md`` is missing.
    """
    return _read_prompt_file(_PROSE_FILE)


def _read_prompt_file(name: str) -> str:
    """Read ``<prompts dir>/<name>`` as UTF-8 text."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _split_h2_sections(text: str) -> dict[str, str]:
    """Split a markdown document into ``{h2_name: body}``.

    Body text before the first H2 is ignored. Each section body is
    stripped of leading / trailing blank lines and re-terminated with a
    single newline so callers see a stable shape.
    """
    sections: dict[str, str] = {}
    matches = list(_H2_PATTERN.finditer(text))
    for index, match in enumerate(matches):
        name = match.group("name")
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip("\n").rstrip()
        sections[name] = body + "\n"
    return sections


__all__ = [
    "load_capabilities_tiebreak_templates",
    "load_prose_section_template",
]
