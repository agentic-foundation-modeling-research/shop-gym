"""Statistics on hand-crafted axtrees (spec §5.3, impl-plan M1).

Covers:

* ``compute_axtree_stats`` returns a closed, validated ``AxtreeStats``.
* Per-role counters honour the closed role frozensets.
* ``max_depth`` walks the merged tree from the first (root) node and is
  robust against cycles and dangling child ids.
* ``content_character_count`` counts normalized accessible-name characters.
* Malformed inputs raise ``TypeError`` for shape errors and tolerate
  missing role/name/childIds inside individual nodes.
"""

from __future__ import annotations

from typing import Any

import pytest

from shop_arena.env_eval.observation import axtree_stats
from shop_arena.env_eval.observation.axtree_stats import (
    BUTTON_ROLES,
    HEADING_ROLES,
    IMAGE_ROLES,
    INTERACTIVE_ROLES,
    LANDMARK_ROLES,
    LINK_ROLES,
    SEMANTIC_DEPTH_IGNORED_ROLES,
    TEXTBOX_ROLES,
    compute_axtree_stats,
)
from shop_arena.env_eval.schema.metrics import AxtreeStats


def _node(
    node_id: str,
    role: str,
    *,
    name: str = "",
    children: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a CDP-shaped axtree node for fixtures."""
    return {
        "nodeId": node_id,
        "role": {"value": role},
        "name": {"value": name},
        "childIds": list(children),
    }


def test_axtree_stats_module_is_importable() -> None:
    """M0 layout marker: ``observation.axtree_stats`` exists and imports."""
    assert axtree_stats.__name__ == "shop_arena.env_eval.observation.axtree_stats"


def test_compute_axtree_stats_empty_tree_is_all_zero() -> None:
    """An empty axtree yields a fully-zero ``AxtreeStats``."""
    stats = compute_axtree_stats({"nodes": []})

    assert isinstance(stats, AxtreeStats)
    assert stats.model_dump() == {
        "node_count": 0,
        "interactive_count": 0,
        "link_count": 0,
        "button_count": 0,
        "textbox_count": 0,
        "image_count": 0,
        "heading_count": 0,
        "landmark_count": 0,
        "max_depth": 0,
        "semantic_max_depth": 0,
        "content_character_count": 0,
    }


def test_compute_axtree_stats_counts_each_closed_enum_role_once() -> None:
    """Every closed-enum role contributes to its bucket and to ``node_count``.

    The fixture mixes link/button/textbox/image/heading/landmark plus a
    couple of interactive-only roles (``checkbox``, ``menuitem``) to
    confirm ``interactive_count`` covers the wider enum and the per-role
    buckets stay tight.
    """
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2", "3", "4", "5", "6", "7", "8", "9")),
            _node("2", "navigation"),  # landmark
            _node("3", "main"),  # landmark
            _node("4", "link", name="Home"),
            _node("5", "button", name="Add to cart"),
            _node("6", "textbox"),  # interactive + textbox
            _node("7", "image"),
            _node("8", "heading", name="Hero"),
            _node("9", "checkbox"),  # interactive only
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.node_count == 9
    assert stats.link_count == 1
    assert stats.button_count == 1
    assert stats.textbox_count == 1
    assert stats.image_count == 1
    assert stats.heading_count == 1
    assert stats.landmark_count == 2
    # link + button + textbox + checkbox -> 4 interactive nodes.
    assert stats.interactive_count == 4


def test_compute_axtree_stats_searchbox_counts_as_textbox_and_interactive() -> None:
    """``searchbox`` is folded into ``textbox_count`` per spec §5.3."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "searchbox", name="Search"),
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.textbox_count == 1
    assert stats.interactive_count == 1


def test_compute_axtree_stats_landmark_enum_is_complete() -> None:
    """All ARIA landmark roles in the closed set bump ``landmark_count``."""
    nodes = [_node("0", "RootWebArea")]
    for idx, role in enumerate(sorted(LANDMARK_ROLES), start=1):
        nodes.append(_node(str(idx), role))
    nodes[0]["childIds"] = [n["nodeId"] for n in nodes[1:]]

    stats = compute_axtree_stats({"nodes": nodes})

    assert stats.landmark_count == len(LANDMARK_ROLES)


def test_compute_axtree_stats_unknown_role_only_bumps_node_count() -> None:
    """Roles outside the closed enums add to ``node_count`` but to no bucket."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2", "3")),
            _node("2", "generic"),
            _node("3", "tooltip"),  # not in any closed set
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.node_count == 3
    assert stats.link_count == 0
    assert stats.button_count == 0
    assert stats.interactive_count == 0
    assert stats.landmark_count == 0


def test_compute_axtree_stats_max_depth_follows_deepest_branch() -> None:
    """``max_depth`` is the longest root → leaf path in edges."""
    # Root has two branches; the right branch is 3 edges deep.
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2", "3")),
            _node("2", "generic"),
            _node("3", "main", children=("4",)),
            _node("4", "navigation", children=("5",)),
            _node("5", "link", name="Deep"),
        ]
    }

    stats = compute_axtree_stats(tree)

    # Path: 1 → 3 → 4 → 5 == depth 3.
    assert stats.max_depth == 3
    assert stats.semantic_max_depth == 3


def test_compute_axtree_stats_max_depth_handles_cycles() -> None:
    """Cyclic ``childIds`` are tolerated; depth stays finite."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "generic", children=("1",)),  # back-edge
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.max_depth == 1
    assert stats.node_count == 2
    assert stats.semantic_max_depth == 0


def test_compute_axtree_stats_dangling_child_ids_are_skipped() -> None:
    """Child ids that do not resolve to a node are ignored, not crashed on."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2", "MISSING")),
            _node("2", "generic"),
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.node_count == 2
    assert stats.max_depth == 1
    assert stats.semantic_max_depth == 0


def test_compute_axtree_stats_content_characters_count_accessible_names() -> None:
    """``content_character_count`` sums normalized accessible names.

    The count includes both interactive labels and static text so the aggregate
    metric reflects the text surface an agent can observe.
    """
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2", "3")),
            _node("2", "button", name="Add to cart", children=("3",)),
            _node("3", "StaticText", name="Add to cart"),
            _node("4", "StaticText", name="  spaced  out   text  "),
        ]
    }
    tree["nodes"][0]["childIds"] = ["2", "4"]

    stats = compute_axtree_stats(tree)

    # Button "Add to cart" (11) + StaticText "Add to cart" (11)
    # + "spaced out text" (15) == 37.
    assert stats.content_character_count == 37


def test_compute_axtree_stats_content_characters_handle_missing_name() -> None:
    """A node without a usable name contributes zero characters."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2", "3")),
            {"nodeId": "2", "role": {"value": "StaticText"}},  # no name
            _node("3", "StaticText", name=""),  # empty name
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.content_character_count == 0


def test_compute_axtree_stats_tolerates_missing_role_keys() -> None:
    """Nodes missing ``role``/``name`` keys are counted toward ``node_count`` only."""
    tree = {
        "nodes": [
            {"nodeId": "1", "childIds": ["2"]},  # no role
            {"nodeId": "2"},  # no role, no name, no children
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.node_count == 2
    assert stats.link_count == 0
    assert stats.interactive_count == 0
    # Walk still terminates cleanly: node 1 → node 2 == depth 1.
    assert stats.max_depth == 1
    assert stats.semantic_max_depth == 0


def test_compute_axtree_stats_rejects_non_mapping_input() -> None:
    """Top-level shape mistakes raise ``TypeError`` (not silent zeros)."""
    with pytest.raises(TypeError):
        compute_axtree_stats([])  # type: ignore[arg-type]


def test_compute_axtree_stats_rejects_non_list_nodes() -> None:
    """``nodes`` must be a list — otherwise the input is malformed."""
    with pytest.raises(TypeError):
        compute_axtree_stats({"nodes": "oops"})


def test_compute_axtree_stats_semantic_max_depth_collapses_wrappers() -> None:
    """``semantic_max_depth`` traverses wrappers without counting them."""
    tree = {
        "nodes": [
            _node("1", "RootWebArea", children=("2",)),
            _node("2", "generic", children=("3",)),
            _node("3", "none", children=("4",)),
            _node("4", "main", children=("5",)),
            _node("5", "Section", children=("6",)),
            _node("6", "button", name="Add", children=("7",)),
            _node("7", "StaticText", name="Add"),
        ]
    }

    stats = compute_axtree_stats(tree)

    assert stats.max_depth == 6
    assert stats.semantic_max_depth == 2


def test_semantic_depth_ignored_roles_cover_text_and_layout_noise() -> None:
    """The ignored-role enum captures common CDP wrapper/text roles."""
    assert {
        "none",
        "generic",
        "Section",
        "StaticText",
        "InlineTextBox",
        "LineBreak",
    }.issubset(SEMANTIC_DEPTH_IGNORED_ROLES)


def test_role_frozensets_are_disjoint_for_per_role_buckets() -> None:
    """Per-role buckets are disjoint so a node only lands in one of them.

    ``INTERACTIVE_ROLES`` is the deliberate superset (it covers
    ``link``/``button``/``textbox``/``searchbox`` plus other controls);
    every other per-role frozenset must be pairwise disjoint.
    """
    per_role = [LINK_ROLES, BUTTON_ROLES, TEXTBOX_ROLES, IMAGE_ROLES, HEADING_ROLES, LANDMARK_ROLES]
    for i, lhs in enumerate(per_role):
        for rhs in per_role[i + 1 :]:
            assert lhs.isdisjoint(rhs), f"{lhs} and {rhs} must be disjoint"

    # Sanity: every textbox/link/button is also classified as interactive.
    assert TEXTBOX_ROLES.issubset(INTERACTIVE_ROLES)
    assert LINK_ROLES.issubset(INTERACTIVE_ROLES)
    assert BUTTON_ROLES.issubset(INTERACTIVE_ROLES)
