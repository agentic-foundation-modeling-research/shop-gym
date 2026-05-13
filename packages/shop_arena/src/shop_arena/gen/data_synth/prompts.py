"""Prompt-template loader for the Phase 2 data-synthesis steps.

Externalises the ``str.format()`` bodies that
:mod:`shop_arena.gen.data_synth.identity` (and the M3 follow-up steps) send
to the LLM. Keeping prompts in ``.md`` files under
:mod:`shop_arena.gen.data_synth.prompts` lets prompt engineering iterate
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

import json
from functools import cache
from pathlib import Path
from typing import Any, Final, cast

_PROMPTS_DIR: Final[Path] = Path(__file__).resolve().parent / "prompts"
_BRANDS_FILE: Final[Path] = Path(__file__).resolve().parent.parent / "brands" / "fake_brands.json"
_IDENTITY_FILE: Final[str] = "synth_identity.md"
_STORE_FILE: Final[str] = "synth_store.md"
_PAGES_FILE: Final[str] = "synth_pages.md"
_POLICIES_FILE: Final[str] = "synth_policies.md"
_COLLECTIONS_FILE: Final[str] = "synth_collections.md"
_PRODUCT_SKELETONS_FILE: Final[str] = "synth_product_skeletons.md"
_PRODUCT_DETAILS_FILE: Final[str] = "synth_product_details.md"
_NAVIGATION_FILE: Final[str] = "synth_navigation.md"
_ALT_TEXT_FILE: Final[str] = "synth_alt_text.md"
_DIVIDER: Final[str] = "\n---\n"
_BRAND_SAFETY_PLACEHOLDER: Final[str] = "{brand_safety}"


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


@cache
def load_synth_product_skeletons_template() -> str:
    """Return the ``synth_product_skeletons`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{collections}``,
        ``{total_products}``.

    Raises:
        FileNotFoundError: ``synth_product_skeletons.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_PRODUCT_SKELETONS_FILE)


@cache
def load_synth_product_details_template() -> str:
    """Return the ``synth_product_details`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{identity}``,
        ``{collection}``, ``{skeletons}``, ``{product_count}``,
        ``{allowlist}``.

    Raises:
        FileNotFoundError: ``synth_product_details.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_PRODUCT_DETAILS_FILE)


@cache
def load_synth_navigation_template() -> str:
    """Return the ``synth_navigation`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{collections}``,
        ``{pages}``, ``{capabilities}``.

    Raises:
        FileNotFoundError: ``synth_navigation.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_NAVIGATION_FILE)


@cache
def load_synth_alt_text_template() -> str:
    """Return the ``synth_alt_text`` ``str.format()`` body.

    Returns:
        The template body. Format placeholders: ``{collection}``,
        ``{products}``, ``{images_per_product}``, ``{min_chars}``,
        ``{max_chars}``.

    Raises:
        FileNotFoundError: ``synth_alt_text.md`` is missing.
        ValueError: The file does not contain the ``---`` divider that
            separates the documentation header from the template body.
    """
    return _read_template_body(_ALT_TEXT_FILE)


def _read_template_body(name: str) -> str:
    """Read ``<prompts dir>/<name>`` and return everything after the first ``---``.

    Substitutes the literal ``{brand_safety}`` token (if present) with the
    rendered allowlist + safe-noun reference block (spec §5.6) so every
    Phase 2 prompt embeds the brand-safety contract from a single source
    of truth (``fake_brands.json``). The substitution happens *before* the
    step calls :py:meth:`str.format`, so the block never collides with the
    step's own format placeholders.

    Args:
        name: File name relative to the package's ``prompts/`` directory.

    Returns:
        The body trimmed of leading / trailing blank lines, with the
        ``{brand_safety}`` token (if any) replaced by the rendered block.

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
    body = body.strip("\n").rstrip() + "\n"
    if _BRAND_SAFETY_PLACEHOLDER in body:
        body = body.replace(_BRAND_SAFETY_PLACEHOLDER, _brand_safety_block())
    return body


@cache
def _brand_safety_block() -> str:
    """Return the markdown brand-safety reference rendered from ``fake_brands.json``.

    The block enumerates every allowlisted fake-brand token and the
    safe-noun categories the post-pass scanner treats as common nouns
    (spec §5.6). Cached so repeated template loads do not re-read disk.

    Returns:
        A multi-line markdown string ending with a single newline.

    Raises:
        FileNotFoundError: ``fake_brands.json`` is missing.
        ValueError: The file is malformed (not a JSON object, missing
            ``brands``, or missing ``safe_nouns``).
    """
    raw = _BRANDS_FILE.read_text(encoding="utf-8")
    decoded: Any = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError(
            f"{_BRANDS_FILE}: brand-safety document must be a JSON object",
        )
    document = cast("dict[str, Any]", decoded)

    brand_tokens = _extract_brand_tokens(document)
    safe_categories = _extract_safe_categories(document)

    lines: list[str] = ["**Brand-safety reference**", ""]
    lines.append(
        "The following fake-brand tokens are the ONLY allowlisted proper "
        "nouns (spec §5.6). Use exact case; do not invent new tokens; do "
        "not use any real-world brand:",
    )
    lines.append("")
    for token in brand_tokens:
        lines.append(f"- `{token}`")
    lines.append("")
    lines.append(
        "Capitalized common nouns the post-pass scanner treats as safe "
        "(use freely as descriptive vocabulary; they are NOT flagged as "
        "brand-shaped):",
    )
    lines.append("")
    for label, values in safe_categories:
        rendered = ", ".join(f"`{value}`" for value in values)
        lines.append(f"- {label}: {rendered}")
    lines.append("")
    lines.append(
        "Any other capitalized multi-letter token in your output is treated "
        "as a brand leak by the post-pass scanner and will fail the run.",
    )
    return "\n".join(lines) + "\n"


_SAFE_NOUN_LABELS: Final[dict[str, str]] = {
    "colors": "Colors",
    "materials": "Materials",
    "units": "Sizes & units",
    "countries": "Country abbreviations",
    "stopwords": "Common stopwords",
}


def _extract_brand_tokens(document: dict[str, Any]) -> list[str]:
    """Return the sorted list of ``brands[].token`` values."""
    raw = document.get("brands")
    if not isinstance(raw, list):
        raise ValueError(
            f"{_BRANDS_FILE}: 'brands' must be a list, got {type(raw).__name__}",
        )
    tokens: list[str] = []
    for index, entry in enumerate(cast("list[Any]", raw)):
        if not isinstance(entry, dict):
            raise ValueError(
                f"{_BRANDS_FILE}: brands[{index}] must be an object",
            )
        token = cast("dict[str, Any]", entry).get("token")
        if not isinstance(token, str) or not token:
            raise ValueError(
                f"{_BRANDS_FILE}: brands[{index}] missing string 'token'",
            )
        tokens.append(token)
    if not tokens:
        raise ValueError(f"{_BRANDS_FILE}: 'brands' must not be empty")
    return sorted(tokens)


def _extract_safe_categories(document: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Return ``(label, values)`` for each non-empty safe-noun category."""
    raw = document.get("safe_nouns")
    if not isinstance(raw, dict):
        raise ValueError(
            f"{_BRANDS_FILE}: 'safe_nouns' must be an object, got {type(raw).__name__}",
        )
    categories: list[tuple[str, list[str]]] = []
    for key, label in _SAFE_NOUN_LABELS.items():
        values = cast("dict[str, Any]", raw).get(key)
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValueError(
                f"{_BRANDS_FILE}: safe_nouns.{key} must be a list, got {type(values).__name__}",
            )
        rendered: list[str] = []
        for index, value in enumerate(cast("list[Any]", values)):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"{_BRANDS_FILE}: safe_nouns.{key}[{index}] must be a non-empty string",
                )
            rendered.append(value)
        if rendered:
            # Preserve insertion order so the prompt presents categories in
            # the order the JSON document declared them.
            seen: set[str] = set()
            unique: list[str] = []
            for value in rendered:
                if value not in seen:
                    seen.add(value)
                    unique.append(value)
            categories.append((label, unique))
    if not categories:
        raise ValueError(
            f"{_BRANDS_FILE}: 'safe_nouns' must declare at least one non-empty category",
        )
    return categories


__all__ = [
    "load_synth_alt_text_template",
    "load_synth_collections_template",
    "load_synth_identity_template",
    "load_synth_navigation_template",
    "load_synth_pages_template",
    "load_synth_policies_template",
    "load_synth_product_details_template",
    "load_synth_product_skeletons_template",
    "load_synth_store_template",
]
