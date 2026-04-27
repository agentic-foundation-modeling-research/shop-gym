"""Unit tests for :mod:`shop_gen.brands.allowlist`.

Covers the T3.1 requirements from
``docs/impl/shop_gen_implementation.md``:

* Loader parses ``fake_brands.json`` and surfaces structural errors.
* :func:`is_allowed` is exact-case allowlist membership.
* :func:`scan` tokenizer over ``[A-Z][A-Za-z]+``:

    * clean text → no hits
    * single hit
    * multi-hit
    * sentence-initial false-positive avoidance
    * TitleCase composite handled as one token

* Sentence-initial detection respects whitespace boundaries (tokens
  glued to punctuation are not treated as sentence-initial).
* Allowlisted brands and safe-noun tokens never produce hits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shop_gen.brands.allowlist import (
    Allowlist,
    is_allowed,
    load_allowlist,
    scan,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_allowlist(
    *,
    brands: list[str] | None = None,
    safe_nouns: list[str] | None = None,
    version: str = "test",
) -> Allowlist:
    """Build a small in-memory :class:`Allowlist` for focused tests."""
    return Allowlist(
        version=version,
        brands=frozenset(brands or []),
        safe_nouns=frozenset(safe_nouns or []),
    )


def _write_doc(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# load_allowlist
# --------------------------------------------------------------------------- #


def test_load_allowlist_default_returns_shipped_document() -> None:
    """The default load resolves the in-repo ``fake_brands.json``."""
    allowlist = load_allowlist()

    assert allowlist.version  # non-empty version string
    # Spec §5.6 table — these two tokens are part of the curated 8.
    assert "AisleArena" in allowlist.brands
    assert "Shopliseum" in allowlist.brands
    # Safe-noun categories are flattened into a single set.
    assert "Black" in allowlist.safe_nouns
    assert "Cotton" in allowlist.safe_nouns
    assert "USA" in allowlist.safe_nouns


def test_load_allowlist_missing_file_raises(tmp_path: Path) -> None:
    """A non-existent path is reported as ``FileNotFoundError``."""
    with pytest.raises(FileNotFoundError):
        load_allowlist(tmp_path / "missing.json")


def test_load_allowlist_invalid_json_raises(tmp_path: Path) -> None:
    """Malformed JSON surfaces as ``ValueError``."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_allowlist(bad)


def test_load_allowlist_non_object_root_raises(tmp_path: Path) -> None:
    """Top-level non-object documents are rejected."""
    path = tmp_path / "list.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_allowlist(path)


def test_load_allowlist_missing_version_raises(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path / "no_version.json",
        {"brands": [{"token": "Vendarena"}], "safe_nouns": {}},
    )
    with pytest.raises(ValueError, match="missing string 'version'"):
        load_allowlist(path)


def test_load_allowlist_missing_brands_raises(tmp_path: Path) -> None:
    path = _write_doc(tmp_path / "no_brands.json", {"version": "1", "safe_nouns": {}})
    with pytest.raises(ValueError, match="missing 'brands' list"):
        load_allowlist(path)


def test_load_allowlist_empty_brands_raises(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path / "empty_brands.json",
        {"version": "1", "brands": [], "safe_nouns": {}},
    )
    with pytest.raises(ValueError, match="must not be empty"):
        load_allowlist(path)


def test_load_allowlist_brand_entry_missing_token_raises(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path / "bad_brand.json",
        {"version": "1", "brands": [{"composition": "x + y"}], "safe_nouns": {}},
    )
    with pytest.raises(ValueError, match="brands\\[0\\] missing string 'token'"):
        load_allowlist(path)


def test_load_allowlist_skips_safe_nouns_comment(tmp_path: Path) -> None:
    """The ``comment`` key inside ``safe_nouns`` is ignored, not treated as data."""
    path = _write_doc(
        tmp_path / "with_comment.json",
        {
            "version": "1",
            "brands": [{"token": "Vendarena"}],
            "safe_nouns": {
                "comment": "ignored",
                "colors": ["Red"],
                "stopwords": ["The"],
            },
        },
    )
    allowlist = load_allowlist(path)
    assert allowlist.safe_nouns == frozenset({"Red", "The"})


def test_load_allowlist_safe_nouns_non_list_value_raises(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path / "bad_safe.json",
        {
            "version": "1",
            "brands": [{"token": "Vendarena"}],
            "safe_nouns": {"colors": "Red"},  # should be a list
        },
    )
    with pytest.raises(ValueError, match=r"safe_nouns\.colors must be a list"):
        load_allowlist(path)


# --------------------------------------------------------------------------- #
# is_allowed
# --------------------------------------------------------------------------- #


def test_is_allowed_exact_match_returns_true() -> None:
    """Allowlist membership is exact-case true for shipped tokens."""
    assert is_allowed("AisleArena") is True
    assert is_allowed("Shopliseum") is True


def test_is_allowed_unknown_token_returns_false() -> None:
    assert is_allowed("Acme") is False


def test_is_allowed_is_case_sensitive() -> None:
    """Lower-cased / upper-cased variants do not satisfy membership."""
    assert is_allowed("aislearena") is False
    assert is_allowed("AISLEARENA") is False


def test_is_allowed_does_not_treat_safe_nouns_as_brands() -> None:
    """Safe-noun tokens are NOT brands; ``is_allowed`` rejects them."""
    assert is_allowed("Black") is False
    assert is_allowed("USA") is False


def test_is_allowed_uses_explicit_allowlist_argument() -> None:
    custom = _make_allowlist(brands=["AcmeCorp"])
    assert is_allowed("AcmeCorp", allowlist=custom) is True
    # Default-allowlisted tokens should be unknown to a custom allowlist.
    assert is_allowed("AisleArena", allowlist=custom) is False


# --------------------------------------------------------------------------- #
# scan — happy-path coverage from the impl checklist
# --------------------------------------------------------------------------- #


def test_scan_clean_text_returns_no_hits() -> None:
    """Lowercase prose with no proper nouns produces no hits."""
    text = "the quick brown fox jumps over the lazy dog"
    assert scan(text) == []


def test_scan_single_hit_mid_sentence() -> None:
    """One non-allowlisted token in mid-sentence produces exactly one hit."""
    text = "We sell a Glamora dress for $40."
    hits = scan(text)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.token == "Glamora"
    assert text[hit.start : hit.end] == "Glamora"


def test_scan_multi_hit_preserves_source_order() -> None:
    """Multiple leaks are reported separately, in source order."""
    text = "We compared Acme to Wayland yesterday."
    hits = scan(text)
    assert [h.token for h in hits] == ["Acme", "Wayland"]
    assert hits[0].start < hits[1].start


def test_scan_skips_sentence_initial_words() -> None:
    """A capitalized word at the start of a sentence is not a candidate."""
    text = "Welcome to the store. The collection is curated."
    # Both "Welcome" and "The" are sentence-initial; neither is a hit.
    assert scan(text) == []


def test_scan_skips_sentence_initial_after_exclamation_and_question() -> None:
    text = "Buy now! Save more. Why wait? Order today."
    # Every capitalized word here opens a sentence — no hits.
    assert scan(text) == []


def test_scan_titlecase_composite_matches_as_one_token() -> None:
    """``AisleArena`` is consumed greedily by the regex as one token."""
    text = "We partner with AisleArena for fulfillment."
    # AisleArena is in the default allowlist → no leak.
    assert scan(text) == []
    # And the same text against an empty allowlist reports it as one
    # contiguous token, not two ("Aisle" + "Arena").
    custom = _make_allowlist(brands=[])
    hits = scan(text, allowlist=custom)
    assert [h.token for h in hits] == ["AisleArena"]


def test_scan_skips_allowlisted_brand_tokens() -> None:
    """Allowlisted brands appearing in text are not reported."""
    text = "Vendors include AisleArena and Shopliseum."
    assert scan(text) == []


def test_scan_skips_safe_noun_tokens() -> None:
    """Colors, materials, and country abbrevs are absorbed by safe-nouns."""
    text = "Available in Black or Red, made of Cotton, ships from USA."
    assert scan(text) == []


def test_scan_glued_tokens_are_not_sentence_initial() -> None:
    """``"abc.Acme"`` (no whitespace after ``.``) flags ``Acme`` as a hit."""
    text = "see ref.Acme for details"
    hits = scan(text)
    assert [h.token for h in hits] == ["Acme"]


def test_scan_token_after_paragraph_break_with_terminator_is_initial() -> None:
    """A terminator + newline counts as a sentence boundary."""
    text = "First sentence.\n\nThe second begins here."
    # "The" is in the safe-noun list anyway, but more importantly the
    # scanner recognises the terminator-then-whitespace boundary.
    assert scan(text) == []


def test_scan_hit_offsets_round_trip_back_to_token() -> None:
    """``text[hit.start:hit.end]`` equals ``hit.token`` for every hit."""
    text = "Shop the Glamora line and the Wayland line."
    for hit in scan(text):
        assert text[hit.start : hit.end] == hit.token


def test_scan_ignores_lowercase_only_tokens() -> None:
    """Tokens with no uppercase letters never match ``[A-Z][A-Za-z]+``."""
    text = "the brand offered fast shipping yesterday"
    assert scan(text) == []


def test_scan_uses_explicit_allowlist_argument() -> None:
    """Passing an ``allowlist=`` overrides the default (and skips the cache)."""
    custom = _make_allowlist(brands=["AcmeCorp"], safe_nouns=["Boutique"])
    text = "We carry AcmeCorp Boutique Glamora picks."
    hits = scan(text, allowlist=custom)
    assert [h.token for h in hits] == ["Glamora"]


def test_scan_ignores_single_capital_letter_words() -> None:
    """Single-character capitals (``I``, ``A``) cannot match the 2+ regex."""
    text = "I bought A jacket."
    assert scan(text) == []


def test_scan_handles_text_starting_with_whitespace() -> None:
    """Leading whitespace does not break sentence-initial detection."""
    text = "   Hello there."
    # "Hello" is sentence-initial (start of text modulo whitespace).
    assert scan(text) == []
