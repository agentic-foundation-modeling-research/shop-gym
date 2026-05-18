"""Unit tests for ``shop_arena.env_eval.action`` (spec §5.4).

Covers:

* :data:`ACTION_SUBSETS` matches the spec-pinned subset list.
* :data:`HEURISTIC_VERSION` matches the v0.1 string.
* :func:`discover_vocabulary` derives a sorted, deterministic vocabulary
  from BrowserGym's :class:`HighLevelActionSet` and includes every action
  the spec §5.4 example artifact references.
* :data:`ROLE_TO_ACTIONS` mirrors the spec §5.4 role/action table with
  closed role sets and sorted action tuples.
* :func:`is_page_scrollable` honors the "any scrollable node OR
  document scrollHeight > viewport" rule.

The full ``compute_action_space`` composition ships in a later M3 task
and is tested separately.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from browsergym.core.action.highlevel import HighLevelActionSet

from shop_arena.env_eval import action


def test_action_module_is_importable() -> None:
    """M0 layout marker: ``action`` module exists and imports."""
    assert action.__name__ == "shop_arena.env_eval.action"


def test_action_subsets_match_spec() -> None:
    """``ACTION_SUBSETS`` mirrors the spec §5.4 ShopGuru-agent subset list."""
    assert action.ACTION_SUBSETS == ("chat", "infeas", "bid", "nav", "tab")


def test_action_subsets_is_immutable_tuple() -> None:
    """The subset list must be a tuple so it cannot be mutated by callers."""
    assert isinstance(action.ACTION_SUBSETS, tuple)


def test_heuristic_version_is_v0_2() -> None:
    """``HEURISTIC_VERSION`` is pinned to ``"0.2"`` for the choice-target fix."""
    assert action.HEURISTIC_VERSION == "0.2"


def test_discover_vocabulary_returns_sorted_unique_tuple() -> None:
    """Vocabulary is a sorted tuple (byte-stable) of unique action names."""
    vocab = action.discover_vocabulary()
    assert isinstance(vocab, tuple)
    assert list(vocab) == sorted(vocab)
    assert len(vocab) == len(set(vocab))


def test_discover_vocabulary_matches_highlevelactionset_keys() -> None:
    """Vocabulary equals ``HighLevelActionSet.action_set.keys()`` for the subsets.

    The whole point of reading from BrowserGym is that EnvEval reports
    *exactly* the action names agents can emit; any drift would invalidate
    downstream metrics.
    """
    expected = tuple(
        sorted(
            HighLevelActionSet(subsets=cast("Any", list(action.ACTION_SUBSETS))).action_set.keys()
        )
    )
    assert action.discover_vocabulary() == expected


def test_discover_vocabulary_contains_spec_example_actions() -> None:
    """Vocabulary covers every action named in the spec §5.4 example artifact.

    Spec §5.4 lists ``click``, ``fill``, ``hover``, ``goto``,
    ``send_msg_to_user`` in the example ``action_space.json`` plus
    ``select_option`` and ``scroll`` in the role→action table.  All must be
    discoverable from the configured subsets.
    """
    vocab = set(action.discover_vocabulary())
    spec_actions = {
        "click",
        "fill",
        "hover",
        "goto",
        "send_msg_to_user",
        "select_option",
        "scroll",
        "report_infeasible",
        "go_back",
        "go_forward",
        "new_tab",
        "tab_focus",
        "tab_close",
        "noop",
    }
    missing = spec_actions - vocab
    assert not missing, f"spec §5.4 actions missing from vocabulary: {sorted(missing)}"


def test_discover_vocabulary_is_deterministic() -> None:
    """Repeated calls return identical tuples (byte-stable artifacts)."""
    assert action.discover_vocabulary() == action.discover_vocabulary()


def test_discover_vocabulary_accepts_alternative_subsets() -> None:
    """Caller-supplied subsets are honored — used for unit-testing the rule.

    Passing only ``("nav",)`` must produce a strict subset of the default
    vocabulary, proving the function actually consults its argument rather
    than always returning the spec default.
    """
    nav_only = set(action.discover_vocabulary(subsets=("nav",)))
    full = set(action.discover_vocabulary())
    assert nav_only, "nav subset must contribute at least one action"
    assert nav_only.issubset(full)
    assert nav_only != full


# ---------------------------------------------------------------------------
# Role → action mapping (spec §5.4 table)
# ---------------------------------------------------------------------------


def test_clickable_roles_match_spec_table() -> None:
    """Clickable roles include the three explicit spec entries plus the
    aria controls implied by "clickable controls"."""
    assert {"button", "link", "menuitem"}.issubset(action.CLICKABLE_ROLES)
    # The map must not silently swallow text or select roles.
    assert action.CLICKABLE_ROLES.isdisjoint(action.TEXT_INPUT_ROLES)
    assert action.CLICKABLE_ROLES.isdisjoint(action.SELECT_ROLES)


def test_text_input_roles_match_spec_table() -> None:
    """Spec §5.4 row 2: ``textbox``, ``searchbox``, text-like inputs."""
    assert action.TEXT_INPUT_ROLES == frozenset({"textbox", "searchbox"})  # noqa: SIM300


def test_select_roles_match_spec_table() -> None:
    """Spec §5.4 row 3: ``combobox``, ``listbox``, ``option``."""
    assert action.SELECT_ROLES == frozenset({"combobox", "listbox", "option"})  # noqa: SIM300


def test_choice_target_roles_cover_discrete_controls() -> None:
    """Choice-target roles include native select controls plus radio/checkbox."""
    assert (
        frozenset(
            {"checkbox", "combobox", "listbox", "option", "radio"},
        )
        == action.CHOICE_TARGET_ROLES
    )


def test_role_to_actions_clickable_bucket() -> None:
    """Clickable roles map to the sorted ``click/dblclick/hover`` triple."""
    expected = ("click", "dblclick", "hover")
    for role in action.CLICKABLE_ROLES:
        assert action.ROLE_TO_ACTIONS[role] == expected, role


def test_role_to_actions_text_bucket() -> None:
    """Text inputs map to the sorted ``clear/fill/press`` triple."""
    expected = ("clear", "fill", "press")
    for role in action.TEXT_INPUT_ROLES:
        assert action.ROLE_TO_ACTIONS[role] == expected, role


def test_role_to_actions_select_bucket() -> None:
    """Select-style roles map to the singleton ``select_option`` tuple."""
    expected = ("select_option",)
    for role in action.SELECT_ROLES:
        assert action.ROLE_TO_ACTIONS[role] == expected, role


def test_role_to_actions_unknown_role_omitted() -> None:
    """Roles outside the closed sets contribute no per-target actions.

    ``slider``, ``spinbutton``, ``heading``, landmarks and ``generic`` are
    real ARIA roles but they have no spec §5.4 row, so they must be
    absent from the mapping rather than silently re-classified.
    """
    for role in ("slider", "spinbutton", "heading", "banner", "generic", ""):
        assert role not in action.ROLE_TO_ACTIONS


def test_role_to_actions_is_immutable() -> None:
    """The mapping is wrapped in ``MappingProxyType`` so callers cannot mutate it."""
    with pytest.raises(TypeError):
        action.ROLE_TO_ACTIONS["button"] = ()  # pyright: ignore[reportIndexIssue]


def test_role_to_actions_action_tuples_are_sorted() -> None:
    """Each value is a sorted tuple so artifacts stay byte-stable."""
    for role, actions in action.ROLE_TO_ACTIONS.items():
        assert isinstance(actions, tuple), role
        assert list(actions) == sorted(actions), role
        assert len(actions) == len(set(actions)), role


def test_role_to_actions_actions_are_in_vocabulary() -> None:
    """Every action verb in the mapping is present in the discovered vocabulary."""
    vocab = set(action.discover_vocabulary())
    for role, actions in action.ROLE_TO_ACTIONS.items():
        for verb in actions:
            assert verb in vocab, f"{role} -> {verb} not in vocabulary"


# ---------------------------------------------------------------------------
# Scroll detection (spec §5.4 trailing rule)
# ---------------------------------------------------------------------------


def test_is_page_scrollable_direct_node_attribute() -> None:
    """A node with a top-level ``scrollable: True`` flag flips the result."""
    axtree = {"nodes": [{"nodeId": "1", "scrollable": True}]}
    assert action.is_page_scrollable(axtree) is True


def test_is_page_scrollable_property_entry() -> None:
    """CDP-style ``properties: [{name: scrollable, value: {value: True}}]``."""
    axtree = {
        "nodes": [
            {
                "nodeId": "1",
                "properties": [
                    {"name": "editable", "value": {"value": True}},
                    {"name": "scrollable", "value": {"value": True}},
                ],
            }
        ]
    }
    assert action.is_page_scrollable(axtree) is True


def test_is_page_scrollable_property_with_bare_value_true() -> None:
    """Tolerate the rarer ``properties: [{name: scrollable, value: True}]``."""
    axtree = {"nodes": [{"properties": [{"name": "scrollable", "value": True}]}]}
    assert action.is_page_scrollable(axtree) is True


def test_is_page_scrollable_scroll_height_exceeds_viewport() -> None:
    """Empty axtree but ``scroll_height > viewport_height`` still trips the rule."""
    assert action.is_page_scrollable({"nodes": []}, scroll_height=2000, viewport_height=900) is True


def test_is_page_scrollable_returns_false_when_short_and_no_node() -> None:
    """No scrollable node and document fits the viewport → ``False``."""
    axtree = {"nodes": [{"nodeId": "1", "role": {"value": "button"}}]}
    assert action.is_page_scrollable(axtree, scroll_height=600, viewport_height=900) is False


def test_is_page_scrollable_returns_false_when_height_unknown() -> None:
    """Missing height inputs alone do not flip the result to ``True``."""
    assert action.is_page_scrollable({"nodes": []}) is False


def test_is_page_scrollable_property_value_false_does_not_match() -> None:
    """A ``scrollable: False`` property must not flip the result."""
    axtree = {"nodes": [{"properties": [{"name": "scrollable", "value": {"value": False}}]}]}
    assert action.is_page_scrollable(axtree) is False


def test_is_page_scrollable_tolerates_malformed_properties() -> None:
    """Non-list ``properties`` and non-mapping entries do not raise."""
    axtree = {
        "nodes": [
            {"properties": "not-a-list"},
            {"properties": ["not-a-mapping", None]},
            "not-a-node",
        ]
    }
    assert action.is_page_scrollable(axtree) is False


def test_is_page_scrollable_rejects_non_mapping_axtree() -> None:
    """Defensive guard: a non-mapping argument raises ``TypeError``."""
    with pytest.raises(TypeError):
        action.is_page_scrollable(cast("Any", [1, 2, 3]))


# ---------------------------------------------------------------------------
# compute_action_space (spec §5.4 artifact composition)
# ---------------------------------------------------------------------------


def _node(
    *,
    role: str | None,
    name: str | None = None,
    bid: str | None = None,
    node_id: str | None = None,
    scrollable: bool = False,
    child_ids: list[str] | None = None,
    properties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a CDP-shaped axtree node for the unit tests."""
    out: dict[str, Any] = {}
    if node_id is not None:
        out["nodeId"] = node_id
    if role is not None:
        out["role"] = {"value": role}
    if name is not None:
        out["name"] = {"value": name}
    if bid is not None:
        out["browsergym_id"] = bid
    if scrollable:
        out["scrollable"] = True
    if child_ids is not None:
        out["childIds"] = child_ids
    if properties is not None:
        out["properties"] = properties
    return out


class _StubPage:
    """Minimal Playwright-page double exposing ``evaluate`` + ``viewport_size``."""

    def __init__(
        self,
        *,
        scroll_height: int | None,
        viewport_height: int | None,
        raise_on_evaluate: bool = False,
    ) -> None:
        self.scroll_height = scroll_height
        self.viewport_size: dict[str, int] | None = (
            {"width": 1440, "height": viewport_height} if viewport_height is not None else None
        )
        self.raise_on_evaluate = raise_on_evaluate
        self.evaluate_calls: list[str] = []

    def evaluate(self, expression: str) -> int | None:
        self.evaluate_calls.append(expression)
        if self.raise_on_evaluate:
            raise RuntimeError("evaluate() boom")
        return self.scroll_height


def test_compute_action_space_returns_spec_shape() -> None:
    """Output dict carries every key the spec §5.4 example lists."""
    axtree = {"nodes": [_node(role="button", name="Buy", bid="a1")]}
    page = _StubPage(scroll_height=2000, viewport_height=900)
    result = action.compute_action_space(axtree, None, page)
    assert set(result) == {
        "vocabulary",
        "by_action",
        "by_category",
        "elements",
        "subsets",
        "heuristic_version",
    }
    assert result["heuristic_version"] == action.HEURISTIC_VERSION
    assert result["subsets"] == list(action.ACTION_SUBSETS)
    assert result["vocabulary"] == list(action.discover_vocabulary())


def test_compute_action_space_vocabulary_is_byte_stable() -> None:
    """Calling twice with the same inputs returns identical dicts (byte-stable)."""
    axtree = {
        "nodes": [
            _node(role="button", name="A", bid="a1"),
            _node(role="link", name="B", bid="a2"),
            _node(role="textbox", name="C", bid="a3"),
        ],
    }
    page = _StubPage(scroll_height=600, viewport_height=900)
    first = action.compute_action_space(axtree, None, page)
    second = action.compute_action_space(axtree, None, page)
    assert first == second


def test_compute_action_space_role_mapping_clickable_button() -> None:
    """A ``button`` node maps to the click/dblclick/hover triple."""
    axtree = {"nodes": [_node(role="button", name="Add to cart", bid="b1")]}
    page = _StubPage(scroll_height=None, viewport_height=None)
    result = action.compute_action_space(axtree, None, page)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert len(elements) == 1
    assert elements[0]["role"] == "button"
    assert elements[0]["name"] == "Add to cart"
    assert elements[0]["bid"] == "b1"
    assert elements[0]["actions"] == ["click", "dblclick", "hover"]
    assert result["by_action"] == {"click": 1, "dblclick": 1, "hover": 1}


def test_compute_action_space_role_mapping_text_input() -> None:
    """A ``textbox`` node maps to clear/fill/press."""
    axtree = {"nodes": [_node(role="searchbox", name="q", bid="s1")]}
    result = action.compute_action_space(axtree, None, None)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert elements[0]["actions"] == ["clear", "fill", "press"]
    assert result["by_action"] == {"clear": 1, "fill": 1, "press": 1}


def test_compute_action_space_role_mapping_select() -> None:
    """A ``combobox`` node maps to the singleton ``select_option`` tuple."""
    axtree = {"nodes": [_node(role="combobox", name="Size", bid="c1")]}
    result = action.compute_action_space(axtree, None, None)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert elements[0]["actions"] == ["select_option"]
    assert result["by_action"] == {"select_option": 1}
    assert result["by_category"] == {"choice": 1}


def test_compute_action_space_choice_category_counts_non_select_controls() -> None:
    """Radio/checkbox/sort controls count as choices even without select_option."""
    axtree = {
        "nodes": [
            _node(role="radio", name="XS", bid="r1"),
            _node(role="checkbox", name="In stock", bid="c1"),
            _node(
                role="button",
                name="Sort: Trending",
                bid="s1",
                properties=[{"name": "hasPopup", "value": {"value": "listbox"}}],
            ),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    assert result["by_category"] == {"choice": 3}


def test_compute_action_space_choice_category_uses_pressed_button_context() -> None:
    """Pressed color/size buttons count as choices, unrelated toggles do not."""
    axtree = {
        "nodes": [
            _node(role="list", name="Available colors", node_id="parent", child_ids=["child"]),
            _node(
                role="button",
                name="Black",
                bid="b1",
                node_id="child",
                properties=[{"name": "pressed", "value": {"value": "true"}}],
            ),
            _node(
                role="button",
                name="Pause announcements",
                bid="b2",
                properties=[{"name": "pressed", "value": {"value": "false"}}],
            ),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    assert result["by_category"] == {"choice": 1}


def test_compute_action_space_skips_unmapped_roles() -> None:
    """Roles outside :data:`ROLE_TO_ACTIONS` contribute zero elements."""
    axtree = {
        "nodes": [
            _node(role="heading", name="H"),
            _node(role="generic", name="G"),
            _node(role="banner", name="B"),
            _node(role="StaticText", name="text"),
            _node(role=None, name=None),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    assert result["elements"] == []
    assert result["by_action"] == {}
    assert result["by_category"] == {}


def test_compute_action_space_skips_hidden_action_targets() -> None:
    """Hidden AX nodes do not count as action targets or choice targets."""
    axtree = {
        "nodes": [
            _node(
                role="button",
                name="Hidden menu",
                bid="hidden",
                properties=[
                    {"name": "hidden", "value": {"value": True}},
                    {"name": "hiddenRoot", "value": {}},
                ],
            ),
            _node(role="button", name="Visible", bid="visible"),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    assert result["by_action"] == {"click": 1, "dblclick": 1, "hover": 1}
    assert cast("list[dict[str, Any]]", result["elements"])[0]["bid"] == "visible"


def test_compute_action_space_aggregates_counts_across_elements() -> None:
    """``by_action`` counts each verb across every counted target."""
    axtree = {
        "nodes": [
            _node(role="button", name="A", bid="b1"),
            _node(role="link", name="B", bid="b2"),
            _node(role="button", name="C", bid="b3"),
            _node(role="textbox", name="q", bid="t1"),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    # 3 clickable nodes → click/dblclick/hover = 3 each; 1 textbox → clear/fill/press = 1 each.
    assert result["by_action"] == {
        "clear": 1,
        "click": 3,
        "dblclick": 3,
        "fill": 1,
        "hover": 3,
        "press": 1,
    }


def test_compute_action_space_by_action_is_sorted_by_key() -> None:
    """``by_action`` keys are sorted so the artifact is byte-stable."""
    axtree = {"nodes": [_node(role="button", name="A", bid="b1")]}
    result = action.compute_action_space(axtree, None, None)
    keys = list(cast("dict[str, int]", result["by_action"]).keys())
    assert keys == sorted(keys)


def test_compute_action_space_omits_zero_count_verbs() -> None:
    """``by_action`` only lists verbs with at least one counted target."""
    axtree = {"nodes": [_node(role="button", name="A", bid="b1")]}
    result = action.compute_action_space(axtree, None, None)
    assert result["by_action"] == {"click": 1, "dblclick": 1, "hover": 1}
    # ``select_option`` is in the vocabulary but not counted on this page.
    assert "select_option" not in result["by_action"]
    assert "select_option" in result["vocabulary"]


def test_compute_action_space_scroll_via_scroll_height() -> None:
    """``scroll`` flips to 1 when ``scrollHeight > viewport`` even with no scrollable node."""
    axtree = {"nodes": [_node(role="button", name="A", bid="b1")]}
    page = _StubPage(scroll_height=2000, viewport_height=900)
    result = action.compute_action_space(axtree, None, page)
    assert result["by_action"]["scroll"] == 1
    assert page.evaluate_calls == ["document.documentElement.scrollHeight"]


def test_compute_action_space_scroll_via_axtree_node() -> None:
    """A ``scrollable: True`` node alone is enough to set ``scroll = 1``."""
    axtree = {
        "nodes": [
            _node(role="button", name="A", bid="b1"),
            _node(role=None, scrollable=True),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    assert result["by_action"]["scroll"] == 1


def test_compute_action_space_scroll_off_when_short_and_no_node() -> None:
    """Short page with no scrollable node → ``scroll`` is absent from ``by_action``."""
    axtree = {"nodes": [_node(role="button", name="A", bid="b1")]}
    page = _StubPage(scroll_height=600, viewport_height=900)
    result = action.compute_action_space(axtree, None, page)
    assert "scroll" not in result["by_action"]


def test_compute_action_space_scroll_tolerates_evaluate_failure() -> None:
    """A failing ``page.evaluate`` falls back to the axtree signal alone."""
    axtree = {
        "nodes": [
            _node(role="button", name="A", bid="b1"),
            _node(role=None, scrollable=True),
        ],
    }
    page = _StubPage(scroll_height=None, viewport_height=900, raise_on_evaluate=True)
    result = action.compute_action_space(axtree, None, page)
    assert result["by_action"]["scroll"] == 1


def test_compute_action_space_truncates_name_to_80_chars() -> None:
    """Spec §5.4: accessible names are truncated to 80 chars."""
    long_name = "x" * 200
    axtree = {"nodes": [_node(role="button", name=long_name, bid="b1")]}
    result = action.compute_action_space(axtree, None, None)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert elements[0]["name"] == "x" * 80
    assert len(elements[0]["name"]) == action.NAME_MAX_LENGTH


def test_compute_action_space_strips_whitespace_before_truncating() -> None:
    """Names are stripped before length checks so leading/trailing space does not pad."""
    axtree = {"nodes": [_node(role="button", name="   Buy now   ", bid="b1")]}
    result = action.compute_action_space(axtree, None, None)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert elements[0]["name"] == "Buy now"


def test_compute_action_space_missing_bid_is_none() -> None:
    """Counted targets without a BrowserGym id record ``bid: None``."""
    axtree = {"nodes": [_node(role="button", name="A")]}
    result = action.compute_action_space(axtree, None, None)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert elements[0]["bid"] is None


def test_compute_action_space_preserves_axtree_node_order() -> None:
    """``elements`` mirrors the axtree node order (CDP DOM order)."""
    axtree = {
        "nodes": [
            _node(role="button", name="first", bid="b1"),
            _node(role="link", name="second", bid="b2"),
            _node(role="button", name="third", bid="b3"),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert [e["bid"] for e in elements] == ["b1", "b2", "b3"]


def test_compute_action_space_subsets_in_spec_order() -> None:
    """``subsets`` mirrors :data:`ACTION_SUBSETS` in spec (not sorted) order."""
    result = action.compute_action_space({"nodes": []}, None, None)
    assert result["subsets"] == ["chat", "infeas", "bid", "nav", "tab"]


def test_compute_action_space_dom_object_is_optional_and_unused() -> None:
    """v0.1 does not consume ``dom_object``; ``None`` and a stub yield identical output."""
    axtree = {"nodes": [_node(role="button", name="A", bid="b1")]}
    a = action.compute_action_space(axtree, None, None)
    b = action.compute_action_space(axtree, {"documents": []}, None)
    assert a == b


def test_compute_action_space_rejects_non_mapping_axtree() -> None:
    """Defensive guard: a non-mapping ``axtree`` raises ``TypeError``."""
    with pytest.raises(TypeError):
        action.compute_action_space(cast("Any", [1, 2, 3]), None, None)


def test_compute_action_space_rejects_non_list_nodes() -> None:
    """Defensive guard: a non-list ``nodes`` raises ``TypeError``."""
    with pytest.raises(TypeError):
        action.compute_action_space(cast("Any", {"nodes": "oops"}), None, None)


def test_compute_action_space_tolerates_non_mapping_node_entries() -> None:
    """Garbage entries inside ``nodes`` are skipped, not raised on."""
    axtree = {
        "nodes": [
            "not-a-node",
            None,
            _node(role="button", name="A", bid="b1"),
        ],
    }
    result = action.compute_action_space(axtree, None, None)
    assert len(cast("list[dict[str, Any]]", result["elements"])) == 1


def test_compute_action_space_honors_name_max_length_override() -> None:
    """The ``name_max_length`` keyword overrides the spec constant for tests."""
    axtree = {"nodes": [_node(role="button", name="abcdef", bid="b1")]}
    result = action.compute_action_space(axtree, None, None, name_max_length=3)
    elements = cast("list[dict[str, Any]]", result["elements"])
    assert elements[0]["name"] == "abc"
