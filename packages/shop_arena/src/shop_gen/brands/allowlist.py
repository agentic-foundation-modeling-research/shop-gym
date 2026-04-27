"""Fake-brand allowlist loader + post-pass scanner.

Implements the deterministic post-pass scanner from spec §5.6: every
brand-shaped token in ``data/*.json`` and ``hydrogen/app/**`` must
either match the curated 8-element fake-brand allowlist or fall in the
small safe-noun list. Anything else is a leak.

The allowlist + safe-noun list ship as
``packages/shop_arena/src/shop_gen/brands/fake_brands.json``. The file
is checked into the repo and considered API; changes are versioned.

Public surface:

* :class:`Hit` — one record per non-allowlisted brand-shaped token.
* :class:`Allowlist` — frozen view over the shipped JSON document.
* :func:`load_allowlist` — read and validate ``fake_brands.json``.
* :func:`is_allowed` — exact-case allowlist membership predicate.
* :func:`scan` — tokenize a string and return :class:`Hit` records for
  any token that is NOT allowlisted (after dropping sentence-initial
  words and safe nouns).

Module is import-safe: the shipped allowlist file is loaded lazily on
first use, never at import time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, cast

_DEFAULT_ALLOWLIST_PATH: Final[Path] = Path(__file__).parent / "fake_brands.json"

# A "brand-shaped" candidate: a capitalized run of two or more letters.
# This single pattern covers both PascalCase compounds (``AisleArena``
# matches as one token because ``[A-Za-z]+`` is greedy across the inner
# capital) and ALL-CAPS abbreviations (``USA``). Hyphens, apostrophes,
# and digits are deliberately excluded; v0.1 keeps the tokenizer simple
# and absorbs edge cases via the safe-noun list (spec §5.6).
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Za-z]+")

# ASCII sentence terminators. Prompts forbid non-ASCII stylization so a
# wider Unicode set is not needed at v0.1.
_SENTENCE_TERMINATORS: Final[frozenset[str]] = frozenset(".!?")


@dataclass(frozen=True)
class Hit:
    """One non-allowlisted brand-shaped token reported by :func:`scan`.

    Attributes:
        token: The raw matched token, with case preserved exactly as it
            appeared in the source text.
        start: Index of the first character of ``token`` in the source
            string (0-indexed, inclusive).
        end: Index one past the last character. Slicing
            ``text[start:end]`` returns ``token``.
    """

    token: str
    start: int
    end: int


@dataclass(frozen=True)
class Allowlist:
    """Frozen view over the shipped ``fake_brands.json`` document.

    Attributes:
        version: Allowlist schema version, e.g. ``"0.1.2"``.
        brands: Canonical brand tokens. Membership is case-sensitive.
        safe_nouns: Capitalized tokens (colors, materials, units,
            country abbreviations, common stopwords) that the scanner
            treats as non-brand-shaped.
    """

    version: str
    brands: frozenset[str]
    safe_nouns: frozenset[str]

    def is_allowed(self, token: str) -> bool:
        """Return ``True`` iff ``token`` is an allowlisted brand.

        Args:
            token: The candidate brand-shaped token.

        Returns:
            ``True`` when ``token`` matches an allowlist entry exactly
            (case-sensitive). Safe-noun membership is **not** checked
            here — use :func:`scan` for the full §5.6 pipeline.
        """
        return token in self.brands


def load_allowlist(path: Path | None = None) -> Allowlist:
    """Read and validate a ``fake_brands.json`` document.

    Args:
        path: Path to the allowlist file. Defaults to the in-repo
            ``fake_brands.json`` shipped alongside this module.

    Returns:
        A frozen :class:`Allowlist`.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ValueError: The file is not valid JSON, is not a JSON object,
            is missing required keys, or has the wrong shape.
    """
    target = path if path is not None else _DEFAULT_ALLOWLIST_PATH
    if not target.exists():
        raise FileNotFoundError(f"allowlist file not found: {target}")
    raw_text = target.read_text(encoding="utf-8")
    try:
        decoded: Any = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"allowlist file {target} is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(
            f"allowlist file {target} must be a JSON object, got {type(decoded).__name__}",
        )
    document = cast("dict[str, Any]", decoded)

    version = document.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"allowlist file {target} missing string 'version'")

    brands = _parse_brands(document, source=target)
    safe_nouns = _parse_safe_nouns(document, source=target)

    return Allowlist(
        version=version,
        brands=frozenset(brands),
        safe_nouns=frozenset(safe_nouns),
    )


def is_allowed(token: str, *, allowlist: Allowlist | None = None) -> bool:
    """Return ``True`` iff ``token`` is an allowlisted brand.

    Args:
        token: The candidate brand-shaped token.
        allowlist: Optional pre-loaded :class:`Allowlist`. Defaults to
            the in-repo ``fake_brands.json`` (cached after first use).

    Returns:
        ``True`` when ``token`` matches an allowlist entry exactly
        (case-sensitive).
    """
    target = allowlist if allowlist is not None else _default_allowlist()
    return target.is_allowed(token)


def scan(text: str, *, allowlist: Allowlist | None = None) -> list[Hit]:
    """Scan ``text`` and return non-allowlisted brand-shaped tokens.

    Implements the §5.6 scanner pipeline:

    1. Tokenize ``text`` via ``[A-Z][A-Za-z]+`` (capitalized runs of at
       least two letters; PascalCase compounds match as one token).
    2. Drop sentence-initial tokens (the first capitalized token at the
       start of ``text`` or following ``.``/``!``/``?`` + whitespace).
    3. Drop tokens that appear in the safe-noun list.
    4. Emit one :class:`Hit` per remaining token that is NOT in the
       allowlist, preserving match order.

    Args:
        text: Source string to scan.
        allowlist: Optional pre-loaded :class:`Allowlist`. Defaults to
            the in-repo ``fake_brands.json`` (cached after first use).

    Returns:
        Hits in source order. Empty when every brand-shaped token is
        either sentence-initial, a safe noun, or an allowlisted brand.
    """
    target = allowlist if allowlist is not None else _default_allowlist()
    hits: list[Hit] = []
    for match in _TOKEN_RE.finditer(text):
        if _is_sentence_initial(text, match.start()):
            continue
        token = match.group(0)
        if token in target.safe_nouns:
            continue
        if target.is_allowed(token):
            continue
        hits.append(Hit(token=token, start=match.start(), end=match.end()))
    return hits


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_allowlist() -> Allowlist:
    """Return the cached in-repo allowlist, loading it on first call."""
    return load_allowlist(_DEFAULT_ALLOWLIST_PATH)


def _parse_brands(document: dict[str, Any], *, source: Path) -> list[str]:
    """Extract the ``brands[].token`` list from a parsed allowlist document."""
    brands_raw = document.get("brands")
    if not isinstance(brands_raw, list):
        raise ValueError(f"allowlist file {source} missing 'brands' list")
    tokens: list[str] = []
    for index, entry in enumerate(cast("list[Any]", brands_raw)):
        if not isinstance(entry, dict):
            raise ValueError(
                f"allowlist file {source}: brands[{index}] must be an object, "
                f"got {type(entry).__name__}",
            )
        token = cast("dict[str, Any]", entry).get("token")
        if not isinstance(token, str) or not token:
            raise ValueError(
                f"allowlist file {source}: brands[{index}] missing string 'token'",
            )
        tokens.append(token)
    if not tokens:
        raise ValueError(f"allowlist file {source}: 'brands' must not be empty")
    return tokens


def _parse_safe_nouns(document: dict[str, Any], *, source: Path) -> set[str]:
    """Flatten the ``safe_nouns`` categories into one set of tokens."""
    safe_nouns_raw = document.get("safe_nouns")
    if not isinstance(safe_nouns_raw, dict):
        raise ValueError(f"allowlist file {source} missing 'safe_nouns' object")
    flattened: set[str] = set()
    for key, values in cast("dict[str, Any]", safe_nouns_raw).items():
        if key == "comment":
            continue
        if not isinstance(values, list):
            raise ValueError(
                f"allowlist file {source}: safe_nouns.{key} must be a list, "
                f"got {type(values).__name__}",
            )
        for index, value in enumerate(cast("list[Any]", values)):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"allowlist file {source}: safe_nouns.{key}[{index}] must "
                    f"be a non-empty string",
                )
            flattened.add(value)
    return flattened


def _is_sentence_initial(text: str, start: int) -> bool:
    """Return ``True`` iff the token at ``start`` opens a sentence.

    A token is sentence-initial when either:

    * It sits at the start of ``text`` (modulo leading whitespace), or
    * Its preceding non-whitespace character is one of ``.``/``!``/``?``
      AND there is at least one whitespace character separating that
      terminator from the token (so ``"abc.AisleArena"`` is *not*
      treated as sentence-initial).
    """
    if start == 0:
        return True
    if not text[start - 1].isspace():
        return False
    cursor = start - 2
    while cursor >= 0 and text[cursor].isspace():
        cursor -= 1
    if cursor < 0:
        return True
    return text[cursor] in _SENTENCE_TERMINATORS


__all__ = [
    "Allowlist",
    "Hit",
    "is_allowed",
    "load_allowlist",
    "scan",
]
