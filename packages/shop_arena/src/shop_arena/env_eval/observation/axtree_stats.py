"""Deterministic statistics over a BrowserGym merged-axtree object.

This module computes the closed-enum role counts plus tree shape and visible
content character count that populate
``shop_arena.env_eval.schema.metrics.AxtreeStats`` (spec §5.3).  The function
is pure: it takes the axtree dict that BrowserGym returns from
``extract_merged_axtree`` (or any equivalent CDP-shaped payload) and returns
the validated ``AxtreeStats`` value. It does **not** call Playwright, the LLM,
or the filesystem.

The role enum is closed — only the roles listed below are counted.  Roles not
in the enum (``generic``, ``StaticText``, ``Iframe``, ``WebArea``, …) still
count toward ``node_count`` but contribute to no per-role bucket.  This keeps
``AxtreeStats`` stable across BrowserGym minor versions and across shops that
use bespoke ARIA roles.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from shop_arena.env_eval.schema.metrics import AxtreeStats

__all__ = [
    "BUTTON_ROLES",
    "HEADING_ROLES",
    "IMAGE_ROLES",
    "INTERACTIVE_ROLES",
    "LANDMARK_ROLES",
    "LINK_ROLES",
    "SEMANTIC_DEPTH_IGNORED_ROLES",
    "TEXTBOX_ROLES",
    "compute_axtree_stats",
]

#: Roles counted by :class:`AxtreeStats.interactive_count`.  Mirrors the
#: spec §5.3 sentence "button, link, textbox, combobox, checkbox, radio,
#: menuitem, …" with the additional ARIA controls an agent can actually
#: drive (``searchbox``, ``switch``, ``slider``, ``spinbutton``, ``tab``,
#: ``option``, ``menuitemcheckbox``, ``menuitemradio``).  Closed so a typo
#: in upstream CDP role naming surfaces as a count drift, not as silent
#: re-classification.
INTERACTIVE_ROLES: frozenset[str] = frozenset(
    {
        "button",
        "link",
        "textbox",
        "searchbox",
        "combobox",
        "checkbox",
        "radio",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "switch",
        "slider",
        "spinbutton",
        "tab",
        "option",
    }
)

#: Roles counted by :class:`AxtreeStats.link_count`.
LINK_ROLES: frozenset[str] = frozenset({"link"})

#: Roles counted by :class:`AxtreeStats.button_count`.
BUTTON_ROLES: frozenset[str] = frozenset({"button"})

#: Roles counted by :class:`AxtreeStats.textbox_count` — both ``textbox``
#: and ``searchbox`` (CDP folds search inputs into ``searchbox``).
TEXTBOX_ROLES: frozenset[str] = frozenset({"textbox", "searchbox"})

#: Roles counted by :class:`AxtreeStats.image_count`.  CDP normally emits
#: ``image``; we accept ``img`` for safety on older Chromium builds.
IMAGE_ROLES: frozenset[str] = frozenset({"image", "img"})

#: Roles counted by :class:`AxtreeStats.heading_count`.
HEADING_ROLES: frozenset[str] = frozenset({"heading"})

#: ARIA landmark roles counted by :class:`AxtreeStats.landmark_count`.
LANDMARK_ROLES: frozenset[str] = frozenset(
    {
        "banner",
        "navigation",
        "main",
        "complementary",
        "contentinfo",
        "region",
        "search",
        "form",
    }
)

#: Roles collapsed when computing :class:`AxtreeStats.semantic_max_depth`.
#: These roles are either presentational containers or text-layout leaves that
#: inflate raw AXTree depth without adding an agent-relevant UI layer.
SEMANTIC_DEPTH_IGNORED_ROLES: frozenset[str] = frozenset(
    {
        "none",
        "presentation",
        "generic",
        "Section",
        "StaticText",
        "InlineTextBox",
        "LineBreak",
        "LabelText",
        "ListMarker",
        "IframePresentational",
    }
)


def _role(node: Mapping[str, Any]) -> str:
    """Return the node's role string, or ``""`` when missing/malformed."""
    role: object = node.get("role")
    if not isinstance(role, Mapping):
        return ""
    value = cast("Mapping[str, object]", role).get("value")
    return value if isinstance(value, str) else ""


def _name(node: Mapping[str, Any]) -> str:
    """Return the node's accessible-name string, or ``""`` when absent."""
    name: object = node.get("name")
    if not isinstance(name, Mapping):
        return ""
    value = cast("Mapping[str, object]", name).get("value")
    return value if isinstance(value, str) else ""


def _child_ids(node: Mapping[str, Any]) -> list[str]:
    """Return the node's child id list (str-typed), tolerating missing data."""
    raw: object = node.get("childIds")
    if not isinstance(raw, list):
        return []
    raw_list = cast("list[object]", raw)
    return [c for c in raw_list if isinstance(c, str)]


def _max_depth_from_root(
    nodes: list[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> int:
    """Compute the deepest path length starting at the first node.

    The merged AXTree convention places the document root at index ``0``
    (``RootWebArea``).  We walk ``childIds`` iteratively and guard against
    cycles so a malformed tree cannot hang the run.

    Args:
        nodes: All nodes from the axtree (used only to locate the root).
        by_id: ``nodeId`` → node mapping for O(1) child lookup.

    Returns:
        Depth of the deepest path from the root in number of edges
        (root-only tree → ``0``).  Returns ``0`` when ``nodes`` is empty.
    """
    if not nodes:
        return 0
    root_id = nodes[0].get("nodeId")
    if not isinstance(root_id, str) or root_id not in by_id:
        return 0

    # Iterative DFS with a visited set so a self-referential or duplicated
    # childId does not cause infinite recursion.
    max_depth = 0
    stack: list[tuple[str, int]] = [(root_id, 0)]
    visited: set[str] = set()
    while stack:
        node_id, depth = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        max_depth = max(max_depth, depth)
        node = by_id.get(node_id)
        if node is None:
            continue
        for child_id in _child_ids(node):
            if child_id == node_id or child_id in visited:
                continue
            if child_id not in by_id:
                continue
            stack.append((child_id, depth + 1))
    return max_depth


def _is_semantic_depth_role(role: str) -> bool:
    """Return whether ``role`` contributes one semantic depth step."""
    return bool(role) and role not in SEMANTIC_DEPTH_IGNORED_ROLES


def _semantic_max_depth_from_root(
    nodes: list[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> int:
    """Compute deepest path after collapsing presentational/text roles.

    Args:
        nodes: All nodes from the axtree (used only to locate the root).
        by_id: ``nodeId`` → node mapping for O(1) child lookup.

    Returns:
        Deepest path from the root after collapsing roles in
        :data:`SEMANTIC_DEPTH_IGNORED_ROLES`. The root contributes ``0`` so a
        root-only tree returns ``0``. Returns ``0`` when ``nodes`` is empty.
    """
    if not nodes:
        return 0
    root_id = nodes[0].get("nodeId")
    if not isinstance(root_id, str) or root_id not in by_id:
        return 0

    max_depth = 0
    stack: list[tuple[str, int]] = [(root_id, 0)]
    visited: set[str] = set()
    while stack:
        node_id, depth = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        max_depth = max(max_depth, depth)
        node = by_id.get(node_id)
        if node is None:
            continue
        for child_id in _child_ids(node):
            if child_id == node_id or child_id in visited:
                continue
            child = by_id.get(child_id)
            if child is None:
                continue
            child_depth = depth + int(_is_semantic_depth_role(_role(child)))
            stack.append((child_id, child_depth))
    return max_depth


def _tally_role(role: str, counts: dict[str, int]) -> None:
    """Increment the relevant per-role buckets in ``counts`` for ``role``.

    A node may bump several buckets at once: e.g. ``button`` bumps both
    ``interactive`` and ``button``.  Buckets are mutated in place to keep
    :func:`compute_axtree_stats` linear in the node list and shallow in
    cyclomatic complexity.
    """
    if role in INTERACTIVE_ROLES:
        counts["interactive"] += 1
    if role in LINK_ROLES:
        counts["link"] += 1
    if role in BUTTON_ROLES:
        counts["button"] += 1
    if role in TEXTBOX_ROLES:
        counts["textbox"] += 1
    if role in IMAGE_ROLES:
        counts["image"] += 1
    if role in HEADING_ROLES:
        counts["heading"] += 1
    if role in LANDMARK_ROLES:
        counts["landmark"] += 1


def compute_axtree_stats(axtree: Mapping[str, Any]) -> AxtreeStats:
    """Compute :class:`AxtreeStats` from a BrowserGym merged-axtree object.

    The input is the dict returned by
    :func:`browsergym.core.observation.extract_merged_axtree`, i.e.
    ``{"nodes": [{"nodeId": ..., "role": {"value": ...}, "name": {"value": ...},
    "childIds": [...]}, ...]}``.  Statistics are computed deterministically:

    * ``node_count`` is the length of the ``nodes`` list (the simplified
      merged tree as BrowserGym emits it; spec §5.3).
    * Per-role counters use the closed role frozensets exported above.
    * ``max_depth`` is the deepest path from the root in edges, walked
      iteratively with cycle detection.
    * ``semantic_max_depth`` is the deepest path after collapsing
      presentational/text wrapper roles.
    * ``content_character_count`` is the number of characters in every
      non-empty normalized accessible name.

    Args:
        axtree: Parsed BrowserGym/CDP merged-axtree object.

    Returns:
        Validated :class:`AxtreeStats` value (closed schema, ``ge=0`` on
        every counter).

    Raises:
        TypeError: ``axtree`` is not a mapping or its ``nodes`` is not a
            list.  All other malformations (missing roles, missing names,
            non-string child ids) are tolerated and counted as zero.
    """
    if not isinstance(axtree, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"axtree must be a mapping, got {type(axtree).__name__}")
    raw_nodes: object = axtree.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise TypeError(f"axtree['nodes'] must be a list, got {type(raw_nodes).__name__}")

    nodes: list[Mapping[str, Any]] = [n for n in raw_nodes if isinstance(n, Mapping)]  # pyright: ignore[reportUnknownVariableType]
    by_id: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        node_id = node.get("nodeId")
        if isinstance(node_id, str):
            by_id[node_id] = node

    node_count = len(nodes)

    counts: dict[str, int] = {
        "interactive": 0,
        "link": 0,
        "button": 0,
        "textbox": 0,
        "image": 0,
        "heading": 0,
        "landmark": 0,
    }
    content_characters = 0

    for node in nodes:
        role = _role(node)
        _tally_role(role, counts)
        content_characters += len(" ".join(_name(node).split()))

    max_depth = _max_depth_from_root(nodes, by_id)
    semantic_max_depth = _semantic_max_depth_from_root(nodes, by_id)

    return AxtreeStats(
        node_count=node_count,
        interactive_count=counts["interactive"],
        link_count=counts["link"],
        button_count=counts["button"],
        textbox_count=counts["textbox"],
        image_count=counts["image"],
        heading_count=counts["heading"],
        landmark_count=counts["landmark"],
        max_depth=max_depth,
        semantic_max_depth=semantic_max_depth,
        content_character_count=content_characters,
    )
