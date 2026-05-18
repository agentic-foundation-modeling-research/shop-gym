"""Deterministic axtree text renderer for the ``*.axtree.txt`` debug artifact.

EnvEval owns this small renderer (spec §5.3): BrowserGym ships its own
``flatten_axtree_to_str`` but its output shape is tied to the exploration
agent's needs and changes between minor versions.  For the ``*.axtree.txt``
debug artifact we want a tight, byte-stable view that:

* is a function of the structured axtree dict alone — no Playwright, no
  filesystem, no environment;
* indents nodes one tab per visible depth so the file diffs nicely against
  itself across runs;
* surfaces the BrowserGym ``bid`` (when present) so an engineer can cross
  reference the action-space JSON;
* drops only the noise that pollutes every page: empty ``generic`` wrappers,
  ``LineBreak`` nodes, and ``StaticText`` whose value is already in the
  parent's accessible name (CDP composes accessible names from descendant
  text, so the duplicate is structural).

The renderer is intentionally narrower than BrowserGym's flattener — it
exposes no toggles, has no ``extra_properties`` integration, and never
mutates input.  That keeps the M1 debug artifact deterministic for fixture
tests and replay runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

__all__ = [
    "IGNORED_AXTREE_ROLES",
    "render_axtree_text",
]


#: Roles dropped wholesale from the rendered output.  ``LineBreak`` adds no
#: signal in a textual view (it only matters for layout); BrowserGym's
#: ``flatten_axtree_to_str`` skips it for the same reason.
IGNORED_AXTREE_ROLES: frozenset[str] = frozenset({"LineBreak"})


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


def _bid(node: Mapping[str, Any]) -> str | None:
    """Return the BrowserGym id attached to ``node`` (str), or ``None``."""
    raw: object = node.get("browsergym_id")
    return raw if isinstance(raw, str) and raw else None


def _child_ids(node: Mapping[str, Any]) -> list[str]:
    """Return the node's child id list (str-typed), tolerating bad data."""
    raw: object = node.get("childIds")
    if not isinstance(raw, list):
        return []
    raw_list = cast("list[object]", raw)
    return [c for c in raw_list if isinstance(c, str)]


def _format_line(node: Mapping[str, Any]) -> str:
    """Render a single node as ``[bid] role 'name'`` (bid + name optional)."""
    role = _role(node)
    name = _name(node).strip()
    bid = _bid(node)

    body = f"{role} {name!r}" if name else role
    if bid is not None:
        return f"[{bid}] {body}"
    return body


def _should_skip(node: Mapping[str, Any], parent_name: str) -> bool:
    """Decide whether ``node`` is hidden from the rendered output.

    A skipped node still recurses into its children at the parent's depth,
    which lets us collapse anonymous wrappers without flattening real
    structure.

    Args:
        node: The current axtree node.
        parent_name: Accessible name of the visible ancestor — used to
            collapse redundant ``StaticText`` whose value already appears
            in the parent's name (CDP composes accessible names from
            descendant text, so the duplicate is structural noise).

    Returns:
        ``True`` if the node should be omitted from the rendered output.
    """
    role = _role(node)
    if role in IGNORED_AXTREE_ROLES:
        return True
    name = _name(node)
    # ``generic`` wrappers without a name carry no information of their own;
    # CDP emits one per `<div>`/`<span>`.  Keep them when they have a name
    # (e.g. an aria-labelled section) so structure stays visible.
    if role == "generic" and not name:
        return True
    # Drop static text that the parent's accessible name already contains —
    # this is the same de-duplication BrowserGym applies, and it removes the
    # bulk of the noise on text-heavy pages.
    return role == "StaticText" and bool(name) and name in parent_name


def render_axtree_text(axtree: Mapping[str, Any]) -> str:
    """Render a BrowserGym merged-axtree object as a deterministic text tree.

    The output is one node per line, tab-indented by visible depth, in the
    DFS order of ``childIds`` (the same order BrowserGym emits).  Every line
    has the shape::

        [bid] role 'name'

    where ``[bid]`` is omitted when the node has no ``browsergym_id`` and
    ``'name'`` is omitted when the accessible name is empty.

    The renderer is pure: it does not consult Playwright, the network, or
    the environment, and it never mutates ``axtree``.  Cycles introduced by
    repeated child ids are broken by a visited set so a malformed tree
    cannot hang the run.

    Args:
        axtree: Parsed merged-axtree dict — the value returned by
            BrowserGym's ``extract_merged_axtree`` (or any equivalent
            CDP-shaped payload with ``nodes``/``role``/``name``/``childIds``).

    Returns:
        Rendered text tree without a trailing newline.  An empty tree (or
        an axtree whose root is missing) yields an empty string so the
        debug artifact stays byte-stable for the unavailable case.

    Raises:
        TypeError: ``axtree`` is not a mapping or its ``nodes`` is not a
            list.  Per-node malformations (missing role/name/childIds) are
            tolerated and rendered as their best-effort string.
    """
    if not isinstance(axtree, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"axtree must be a mapping, got {type(axtree).__name__}")
    raw_nodes: object = axtree.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise TypeError(f"axtree['nodes'] must be a list, got {type(raw_nodes).__name__}")

    raw_list = cast("list[object]", raw_nodes)
    nodes: list[Mapping[str, Any]] = [n for n in raw_list if isinstance(n, Mapping)]
    if not nodes:
        return ""

    by_id: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        node_id = node.get("nodeId")
        if isinstance(node_id, str):
            by_id[node_id] = node

    root_id = nodes[0].get("nodeId")
    if not isinstance(root_id, str) or root_id not in by_id:
        return ""

    lines: list[str] = []
    visited: set[str] = set()

    def _walk(node_id: str, depth: int, parent_name: str) -> None:
        """Depth-first walk; ``depth`` is the visible (post-skip) depth."""
        if node_id in visited:
            return
        visited.add(node_id)
        node = by_id.get(node_id)
        if node is None:
            return
        skip = _should_skip(node, parent_name)
        if not skip:
            lines.append("\t" * depth + _format_line(node))
        child_depth = depth if skip else depth + 1
        # Skipped nodes do not become the parent_name context for their
        # children — that role belongs to the last visible ancestor.
        next_parent_name = parent_name if skip else _name(node)
        for child_id in _child_ids(node):
            if child_id == node_id:
                continue
            if child_id not in by_id:
                continue
            _walk(child_id, child_depth, next_parent_name)

    _walk(root_id, 0, "")
    return "\n".join(lines)
