"""Tests for the v0.1 screenshot-rubric prompt asset (impl-plan M2).

The full ``observation.rubric`` module lands later in M2 (vision call,
schema validation, malformed-response fallback). This file pins the
prompt asset itself so the closed §5.3 enum stays in lockstep with
``RUBRIC_CATEGORIES`` in :mod:`shop_arena.env_eval.schema.metrics`.
"""

from __future__ import annotations

from importlib import resources

from shop_arena.env_eval.schema.metrics import RUBRIC_CATEGORIES

_PROMPT_RESOURCE = ("shop_arena.env_eval.observation", "prompt.md")


def _read_prompt() -> str:
    package, name = _PROMPT_RESOURCE
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def test_rubric_prompt_file_exists() -> None:
    """``observation/prompt.md`` ships with the package."""
    text = _read_prompt()
    assert text.strip(), "prompt.md must not be empty"


def test_rubric_prompt_has_documentation_divider() -> None:
    """Prompt loader contract: documentation header + ``---`` + body."""
    text = _read_prompt()
    assert "\n---\n" in text, (
        "prompt.md must split documentation from the prompt body with a '---' divider"
    )


def test_rubric_prompt_lists_every_closed_category() -> None:
    """Every §5.3 category appears verbatim in the prompt body."""
    text = _read_prompt()
    body = text.split("\n---\n", 1)[1]
    for category in RUBRIC_CATEGORIES:
        token = f"`{category}`"
        assert token in body, f"prompt.md is missing closed-enum category {token}"


def test_rubric_prompt_does_not_introduce_unknown_categories() -> None:
    """No `backtick` token in the body matches an off-enum category name.

    Guards against silently widening the enum via prompt drift; new
    categories must come paired with a ``RUBRIC_CATEGORIES`` bump.
    """
    text = _read_prompt()
    body = text.split("\n---\n", 1)[1]
    # Collect bullet labels of the form "- `<name>`"
    bullet_labels: set[str] = set()
    for line in body.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("- `"):
            continue
        rest = stripped[3:]
        end = rest.find("`")
        if end <= 0:
            continue
        bullet_labels.add(rest[:end])
    assert bullet_labels, "prompt.md should bullet-list every category as '- `name`'"
    unknown = bullet_labels - set(RUBRIC_CATEGORIES)
    assert not unknown, (
        f"prompt.md introduces categories outside RUBRIC_CATEGORIES: {sorted(unknown)}"
    )


def test_rubric_prompt_is_deterministic() -> None:
    """Reading the prompt twice yields byte-identical content (no templating at load time)."""
    assert _read_prompt() == _read_prompt()
