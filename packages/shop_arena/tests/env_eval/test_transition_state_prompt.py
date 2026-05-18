"""Tests for the v0.1 state-namer prompt asset (impl-plan M5).

The full ``transition.stateful`` rule executor lands later in M5 (rule
selector resolution, structural diff, vision call, state-namer artifact
writer). This file pins the prompt asset itself so the closed §5.5.2
state-name enum stays in lockstep with
``RULE_STATE_NAMES`` in :mod:`shop_arena.env_eval.transition.rules` plus
the three LLM-only entries (``popup_modal``, ``other``, ``no_change``).
"""

from __future__ import annotations

from importlib import resources

from shop_arena.env_eval.transition.rules import RULE_STATE_NAMES

_PROMPT_RESOURCE = ("shop_arena.env_eval.transition", "state_prompt.md")

#: The closed state-namer enum the prompt asset must enumerate.  Strict
#: superset of :data:`RULE_STATE_NAMES`: rules can predict the eight
#: deterministic states; the LLM additionally produces ``popup_modal``
#: (ad-hoc overlays no rule targets), ``other`` (meaningfully new but
#: out-of-enum), and ``no_change`` (the explicit negative answer).
_LLM_ONLY_STATES: tuple[str, ...] = ("popup_modal", "other", "no_change")
_STATE_NAMES: tuple[str, ...] = tuple(RULE_STATE_NAMES) + _LLM_ONLY_STATES


def _read_prompt() -> str:
    package, name = _PROMPT_RESOURCE
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def test_state_prompt_file_exists() -> None:
    """``transition/state_prompt.md`` ships with the package."""
    text = _read_prompt()
    assert text.strip(), "state_prompt.md must not be empty"


def test_state_prompt_has_documentation_divider() -> None:
    """Prompt loader contract: documentation header + ``---`` + body."""
    text = _read_prompt()
    assert "\n---\n" in text, (
        "state_prompt.md must split documentation from the prompt body with a '---' divider"
    )


def test_state_prompt_lists_every_closed_state_name() -> None:
    """Every §5.5.2 state name appears verbatim in the prompt body."""
    text = _read_prompt()
    body = text.split("\n---\n", 1)[1]
    for state_name in _STATE_NAMES:
        token = f"`{state_name}`"
        assert token in body, f"state_prompt.md is missing closed-enum state {token}"


def test_state_prompt_does_not_introduce_unknown_states() -> None:
    """No bullet token in the body matches an off-enum state name.

    Guards against silently widening the enum via prompt drift; new
    state names must come paired with a ``RULE_STATE_NAMES`` (or
    LLM-only) bump and a schema-version revision.
    """
    text = _read_prompt()
    body = text.split("\n---\n", 1)[1]
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
    assert bullet_labels, "state_prompt.md should bullet-list every state as '- `name`'"
    unknown = bullet_labels - set(_STATE_NAMES)
    assert not unknown, (
        f"state_prompt.md introduces states outside the closed enum: {sorted(unknown)}"
    )


def test_state_prompt_is_deterministic() -> None:
    """Reading the prompt twice yields byte-identical content (no templating at load time)."""
    assert _read_prompt() == _read_prompt()


def test_state_prompt_enum_is_superset_of_rule_state_names() -> None:
    """Sanity: the LLM enum contains every rule-emitted state name.

    Rules predict a state name; the LLM may confirm or override. The
    prompt's enum must therefore enumerate every ``RULE_STATE_NAMES``
    entry so a rule's prediction is always a legal LLM answer.
    """
    text = _read_prompt()
    body = text.split("\n---\n", 1)[1]
    for rule_state in RULE_STATE_NAMES:
        assert f"`{rule_state}`" in body, (
            f"state_prompt.md must enumerate rule state name `{rule_state}`"
        )
