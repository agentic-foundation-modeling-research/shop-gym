"""Deterministic axtree text renderer (spec §5.3, impl-plan M1).

Covers:

* ``render_axtree_text`` returns ``str``, never ``None``, and is pure.
* Output is tab-indented one level per visible depth in DFS order.
* Lines are formatted ``[bid] role 'name'`` with ``[bid]`` and ``'name'``
  omitted when missing.
* ``LineBreak``/empty ``generic`` wrappers are skipped without losing
  their children's structural depth.
* ``StaticText`` is suppressed when its value already appears in the
  visible parent's accessible name.
* Cycles and dangling child ids never hang the renderer.
* Malformed top-level inputs raise ``TypeError``.
"""

from __future__ import annotations

from typing import Any

import pytest

from shop_arena.env_eval.observation import axtree_text
from shop_arena.env_eval.observation.axtree_text import (
    IGNORED_AXTREE_ROLES,
    render_axtree_text,
)


def _node(
    node_id: str,
    role: str,
    *,
    name: str = "",
    children: tuple[str, ...] = (),
    bid: str | None = None,
) -> dict[str, Any]:
    """Build a CDP-shaped axtree node for fixtures (mirrors stats tests)."""
    payload: dict[str, Any] = {
        "nodeId": node_id,
        "role": {"value": role},
        "name": {"value": name},
        "childIds": list(children),
    }
    if bid is not None:
        payload["browsergym_id"] = bid
    return payload


def test_render_axtree_text_module_is_importable() -> None:
    """M0 layout marker: the renderer module exists under observation/."""
    assert axtree_text.__name__ == "shop_arena.env_eval.observation.axtree_text"


def test_render_axtree_text_empty_tree_is_empty_string() -> None:
    """An empty axtree renders to ``""`` so artifacts stay byte-stable."""
    assert render_axtree_text({"nodes": []}) == ""


def test_render_axtree_text_indents_one_tab_per_visible_depth() -> None:
    """Nodes are emitted in DFS order with one tab per visible depth."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", name="Shop", children=("2", "3")),
            _node("2", "navigation", name="Primary", children=("4",)),
            _node("3", "main", name="Body"),
            _node("4", "link", name="Home"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert rendered == (
        "RootWebArea 'Shop'\n\tnavigation 'Primary'\n\t\tlink 'Home'\n\tmain 'Body'"
    )


def test_render_axtree_text_includes_bid_prefix_when_present() -> None:
    """``browsergym_id`` becomes a leading ``[bid]`` prefix on the line."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "button", name="Add to cart", bid="42"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert "\t[42] button 'Add to cart'" in rendered.splitlines()


def test_render_axtree_text_omits_name_when_empty_and_skips_quotes() -> None:
    """Nameless interactive nodes render as bare role with no empty quotes."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "image"),
        ]
    }

    rendered = render_axtree_text(tree)

    # The interactive node prints with no trailing ``''`` when there is no
    # accessible name — matters for byte-stable diffs across runs.
    assert "\timage" in rendered.splitlines()
    assert "''" not in rendered


def test_render_axtree_text_skips_linebreak_role() -> None:
    """``LineBreak`` is in :data:`IGNORED_AXTREE_ROLES` and never renders."""
    assert "LineBreak" in IGNORED_AXTREE_ROLES
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2", "3")),
            _node("2", "LineBreak"),
            _node("3", "link", name="Home"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert "LineBreak" not in rendered
    assert rendered.splitlines() == [
        "RootWebArea",
        "\tlink 'Home'",
    ]


def test_render_axtree_text_skips_empty_generic_but_keeps_children_at_parent_depth() -> None:
    """Anonymous ``generic`` wrappers are collapsed without flattening structure."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            # generic with no name → skipped; child stays at depth 1, not 2.
            _node("2", "generic", children=("3",)),
            _node("3", "link", name="Home"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert rendered.splitlines() == [
        "RootWebArea",
        "\tlink 'Home'",
    ]


def test_render_axtree_text_keeps_named_generic_wrappers() -> None:
    """A ``generic`` node with a name carries information and is kept."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "generic", name="Hero", children=("3",)),
            _node("3", "link", name="Home"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert rendered.splitlines() == [
        "RootWebArea",
        "\tgeneric 'Hero'",
        "\t\tlink 'Home'",
    ]


def test_render_axtree_text_drops_static_text_redundant_with_parent_name() -> None:
    """``StaticText`` whose value is in the parent's name is suppressed."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "button", name="Add to cart", children=("3",)),
            _node("3", "StaticText", name="Add to cart"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert "StaticText" not in rendered


def test_render_axtree_text_keeps_static_text_when_not_in_parent_name() -> None:
    """``StaticText`` outside the parent name still carries page text."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "main", children=("3",)),
            _node("3", "StaticText", name="Free shipping over $50"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert "\t\tStaticText 'Free shipping over $50'" in rendered.splitlines()


def test_render_axtree_text_handles_cycle_safely() -> None:
    """A self-referential ``childIds`` does not cause infinite recursion."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "main", name="Body", children=("2",)),
        ]
    }

    rendered = render_axtree_text(tree)

    # The cycle is broken: ``main`` shows once, no infinite repetition.
    assert rendered.count("main") == 1


def test_render_axtree_text_ignores_dangling_child_ids() -> None:
    """Child ids that don't resolve to a node are skipped, not crashed on."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("missing", "2")),
            _node("2", "link", name="Home"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert rendered.splitlines() == [
        "RootWebArea",
        "\tlink 'Home'",
    ]


def test_render_axtree_text_returns_empty_when_root_id_missing() -> None:
    """If the first node has no string ``nodeId`` the renderer returns ``""``."""
    tree: dict[str, Any] = {
        "nodes": [
            {"role": {"value": "RootWebArea"}, "name": {"value": ""}, "childIds": []},
        ]
    }

    assert render_axtree_text(tree) == ""


def test_render_axtree_text_rejects_non_mapping_input() -> None:
    """Top-level malformations raise ``TypeError`` (shape contract)."""
    with pytest.raises(TypeError, match="must be a mapping"):
        render_axtree_text(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_render_axtree_text_rejects_non_list_nodes() -> None:
    """Non-list ``nodes`` is a type error, not a silent empty render."""
    with pytest.raises(TypeError, match="must be a list"):
        render_axtree_text({"nodes": {"not": "a list"}})


def test_render_axtree_text_does_not_mutate_input() -> None:
    """The renderer is pure: input dict + nested children stay identical."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", name="Shop", children=("2",)),
            _node("2", "link", name="Home", bid="3"),
        ]
    }
    snapshot = {
        "nodes": [
            _node("1", "RootWebArea", name="Shop", children=("2",)),
            _node("2", "link", name="Home", bid="3"),
        ]
    }

    render_axtree_text(tree)

    assert tree == snapshot


def test_render_axtree_text_is_deterministic_across_calls() -> None:
    """Two calls on the same input return byte-identical output (replay-safe)."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", name="Shop", children=("2", "3")),
            _node("2", "navigation", name="Primary"),
            _node("3", "main"),
        ]
    }

    assert render_axtree_text(tree) == render_axtree_text(tree)


def test_render_axtree_text_no_trailing_newline() -> None:
    """Renderer emits no trailing newline; the writer owns final framing."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", name="Shop", children=("2",)),
            _node("2", "link", name="Home"),
        ]
    }

    rendered = render_axtree_text(tree)

    assert not rendered.endswith("\n")
