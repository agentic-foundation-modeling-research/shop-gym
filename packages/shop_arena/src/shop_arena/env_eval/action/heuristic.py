"""Action-layer vocabulary + role/action heuristic (BrowserGym ``HighLevelActionSet``).

This module owns the EnvEval action layer's *versioned* contracts (spec §5.4):

* :data:`ACTION_SUBSETS` — the closed list of BrowserGym
  :class:`~browsergym.core.action.highlevel.HighLevelActionSet` subsets EnvEval
  measures against.  These mirror the subsets ShopGuru's agents use so the
  vocabulary EnvEval emits is the vocabulary the agents will eventually train
  with.
* :data:`HEURISTIC_VERSION` — bumped whenever the role→action mapping or the
  vocabulary derivation changes shape.  The version is recorded both in
  :func:`shop_arena.env_eval.schema.manifest` output and in every
  ``action/<bucket>.action_space.json`` artifact so consumers can detect
  drift across runs.
* :func:`discover_vocabulary` — derives the action-name vocabulary by
  introspecting ``HighLevelActionSet(subsets=…).action_set.keys()``.  Returns
  a deterministic, sorted tuple so the artifact is byte-stable across
  invocations and across machines.

The role→action mapping and scroll detection layered on top of these
primitives are composed by :func:`compute_action_space`, which renders
the per-page ``action/<bucket>.action_space.json`` artifact described
in spec §5.4.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final, cast

from browsergym.core.action.highlevel import HighLevelActionSet

__all__ = [
    "ACTION_SUBSETS",
    "CHOICE_TARGET_ROLES",
    "CLICKABLE_ROLES",
    "HEURISTIC_VERSION",
    "NAME_MAX_LENGTH",
    "ROLE_TO_ACTIONS",
    "SELECT_ROLES",
    "TEXT_INPUT_ROLES",
    "compute_action_space",
    "discover_vocabulary",
    "is_page_scrollable",
]

#: BrowserGym ``HighLevelActionSet`` subsets EnvEval probes.  Spec §5.4
#: pins this to ``("chat", "infeas", "bid", "nav", "tab")`` — the same
#: subsets ShopGuru agents use during evaluation.  Stored as a tuple so the
#: list is hashable and unmodifiable at runtime; downstream code converts to
#: a list only when handing it to :class:`HighLevelActionSet`.
ACTION_SUBSETS: Final[tuple[str, ...]] = ("chat", "infeas", "bid", "nav", "tab")

#: Version of the role→action heuristic this module implements.  Bumped on
#: any change to :data:`ACTION_SUBSETS`, the role/action mapping, the
#: vocabulary derivation rule, hidden-node filtering, or target categories
#: (see spec §5.4).  Recorded in every action artifact so a shop's emitted
#: action space remains traceable to the heuristic that produced it.
HEURISTIC_VERSION: Final[str] = "0.2"

#: Maximum length of an element's accessible name in the action artifact.
#: Spec §5.4: "its role and accessible name (truncated to 80 chars)".
#: Truncation keeps the JSON small on text-heavy product pages and
#: matches the artifact width agents see at evaluation time.
NAME_MAX_LENGTH: Final[int] = 80


def discover_vocabulary(
    subsets: tuple[str, ...] = ACTION_SUBSETS,
) -> tuple[str, ...]:
    """Return the high-level action names exposed by the configured subsets.

    The vocabulary is read directly from
    :class:`~browsergym.core.action.highlevel.HighLevelActionSet`'s
    ``action_set`` registry — the same registry the agents call into — so
    EnvEval's recorded vocabulary stays in lockstep with the runtime
    surface.  The returned tuple is sorted to keep
    ``action/<bucket>.action_space.json`` byte-stable across runs.

    Args:
        subsets: BrowserGym subsets to combine.  Defaults to
            :data:`ACTION_SUBSETS`; tests may pass alternative subsets to
            assert the discovery rule rather than the spec'd value.

    Returns:
        Sorted tuple of unique high-level action names (for example
        ``("click", "fill", "goto", …)``).
    """
    # ``HighLevelActionSet`` types ``subsets`` as a private ``Literal[...]``
    # alias which is not exported; cast keeps pyright strict-mode happy
    # without weakening the public signature.
    action_set = HighLevelActionSet(subsets=cast("Any", list(subsets))).action_set
    return tuple(sorted(action_set.keys()))


#: Roles whose primary affordance is a discrete click — ``click``,
#: ``hover``, and ``dblclick`` are all valid attempts an agent can make.
#: Closed enum mirrors the ARIA controls EnvEval already counts in
#: :data:`shop_arena.env_eval.observation.axtree_stats.INTERACTIVE_ROLES`
#: minus the text/select/range controls handled below.  The spec §5.4
#: table writes "button, link, menuitem, clickable controls"; we expand
#: the trailing phrase explicitly so the mapping stays auditable.
CLICKABLE_ROLES: frozenset[str] = frozenset(
    {
        "button",
        "link",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "tab",
        "checkbox",
        "radio",
        "switch",
    }
)

#: Roles that accept free-form text — ``fill`` writes the value,
#: ``clear`` empties it, ``press`` sends a keystroke (Enter to submit).
#: Spec §5.4 row "textbox, searchbox, text-like inputs".
TEXT_INPUT_ROLES: frozenset[str] = frozenset({"textbox", "searchbox"})

#: Roles backed by a discrete option list — ``select_option`` is the
#: only meaningful BrowserGym verb.  Spec §5.4 row "combobox, listbox,
#: option controls".
SELECT_ROLES: frozenset[str] = frozenset({"combobox", "listbox", "option"})

#: Roles/properties that indicate a discrete choice target regardless of
#: whether BrowserGym drives it with ``select_option`` or a click.  This is
#: a category metric, not a BrowserGym action verb.
CHOICE_TARGET_ROLES: frozenset[str] = frozenset(
    {
        "checkbox",
        "combobox",
        "listbox",
        "option",
        "radio",
    }
)

_CLICK_ACTIONS: Final[tuple[str, ...]] = ("click", "dblclick", "hover")
_TEXT_ACTIONS: Final[tuple[str, ...]] = ("clear", "fill", "press")
_SELECT_ACTIONS: Final[tuple[str, ...]] = ("select_option",)
_CHOICE_BUTTON_CONTEXT_TERMS: Final[tuple[str, ...]] = (
    "available colors",
    "color",
    "colour",
    "finish",
    "option",
    "rating",
    "size",
    "variant",
)

#: Closed role → counted-action mapping (spec §5.4 table).  Each value is
#: a sorted tuple so the ``elements`` block in ``action_space.json``
#: stays byte-stable.  Roles outside this map (``slider``, ``spinbutton``,
#: landmarks, generic, …) contribute no per-target counts — only the
#: vocabulary block records that those verbs exist.  Wrapped in
#: ``MappingProxyType`` so accidental mutation by a caller fails loudly.
ROLE_TO_ACTIONS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        **dict.fromkeys(CLICKABLE_ROLES, _CLICK_ACTIONS),
        **dict.fromkeys(TEXT_INPUT_ROLES, _TEXT_ACTIONS),
        **dict.fromkeys(SELECT_ROLES, _SELECT_ACTIONS),
    }
)


def _node_property(node: Mapping[str, Any], name: str) -> object:
    """Return one CDP-style property value, or ``None`` when absent."""
    raw_props: object = node.get("properties", [])
    if not isinstance(raw_props, list):
        return None
    for prop in cast("list[object]", raw_props):
        if not isinstance(prop, Mapping):
            continue
        prop_map = cast("Mapping[str, object]", prop)
        if prop_map.get("name") != name:
            continue
        value = prop_map.get("value")
        if isinstance(value, Mapping):
            return cast("Mapping[str, object]", value).get("value")
        return value
    return None


def _node_has_property(node: Mapping[str, Any], name: str) -> bool:
    """Return whether a CDP-style property entry exists on ``node``."""
    raw_props: object = node.get("properties", [])
    if not isinstance(raw_props, list):
        return False
    for prop in cast("list[object]", raw_props):
        if isinstance(prop, Mapping) and cast("Mapping[str, object]", prop).get("name") == name:
            return True
    return False


def _node_is_hidden(node: Mapping[str, Any]) -> bool:
    """Return whether ``node`` is hidden from the actionable UI surface."""
    if node.get("hidden") is True:
        return True
    if _node_property(node, "hidden") is True:
        return True
    return _node_has_property(node, "hiddenRoot")


def _node_is_scrollable(node: Mapping[str, Any]) -> bool:
    """Return ``True`` when an axtree node carries a ``scrollable`` flag.

    BrowserGym's merged axtree may surface scrollability either as a
    direct ``scrollable`` boolean (some merged-tree formatters lift it
    onto the node) or as a CDP-style ``properties`` entry of the form
    ``{"name": "scrollable", "value": {"value": True}}``.  Both are
    accepted; everything else returns ``False`` so a malformed property
    list cannot crash the run.
    """
    if node.get("scrollable") is True:
        return True
    return _node_property(node, "scrollable") is True


def is_page_scrollable(
    axtree: Mapping[str, Any],
    *,
    scroll_height: int | None = None,
    viewport_height: int | None = None,
) -> bool:
    """Return whether the page should count toward the ``scroll`` action.

    Spec §5.4: "any ``scrollable`` node OR document scrollHeight >
    viewport".  A page is considered scrollable when **either**

    * the merged axtree contains at least one node with
      ``scrollable: True`` (or a ``properties`` entry equivalent), or
    * the caller supplies a ``scroll_height`` and ``viewport_height``
      pair — typically ``page.evaluate('document.documentElement.scrollHeight')``
      and ``page.viewport_size['height']`` — and the document is taller
      than the viewport.

    The function is pure: it never touches Playwright or the network.
    Live integration in ``compute_action_space`` will read the heights
    from the active page and pass them in.

    Args:
        axtree: BrowserGym/CDP merged-axtree object.  ``axtree['nodes']``
            is consulted for the per-node ``scrollable`` signal; other
            shapes are tolerated as ``False``.
        scroll_height: Document scroll height in CSS pixels, or ``None``
            when the caller cannot read it.
        viewport_height: Viewport height in CSS pixels, or ``None`` when
            the caller cannot read it.

    Returns:
        ``True`` when the page is scrollable per the spec rule, else
        ``False``.

    Raises:
        TypeError: ``axtree`` is not a mapping.
    """
    if not isinstance(axtree, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"axtree must be a mapping, got {type(axtree).__name__}")
    raw_nodes: object = axtree.get("nodes", [])
    if isinstance(raw_nodes, list):
        for node in cast("list[object]", raw_nodes):
            if isinstance(node, Mapping) and _node_is_scrollable(cast("Mapping[str, Any]", node)):
                return True
    return (
        scroll_height is not None
        and viewport_height is not None
        and scroll_height > viewport_height
    )


# ---------------------------------------------------------------------------
# compute_action_space (spec §5.4 artifact composition)
# ---------------------------------------------------------------------------


def _node_role(node: Mapping[str, Any]) -> str:
    """Return the node's role string, or ``""`` when missing/malformed."""
    role: object = node.get("role")
    if not isinstance(role, Mapping):
        return ""
    value = cast("Mapping[str, object]", role).get("value")
    return value if isinstance(value, str) else ""


def _node_name(node: Mapping[str, Any]) -> str:
    """Return the node's accessible-name string, or ``""`` when absent."""
    name: object = node.get("name")
    if not isinstance(name, Mapping):
        return ""
    value = cast("Mapping[str, object]", name).get("value")
    return value if isinstance(value, str) else ""


def _node_bid(node: Mapping[str, Any]) -> str | None:
    """Return the BrowserGym id attached to ``node``, or ``None`` when absent."""
    raw: object = node.get("browsergym_id")
    return raw if isinstance(raw, str) and raw else None


def _node_id(node: Mapping[str, Any]) -> str | None:
    """Return the CDP node id attached to ``node``, or ``None`` when absent."""
    raw: object = node.get("nodeId")
    return raw if isinstance(raw, str) and raw else None


def _child_ids(node: Mapping[str, Any]) -> list[str]:
    """Return string-typed child ids for ``node``."""
    raw: object = node.get("childIds", [])
    if not isinstance(raw, list):
        return []
    return [child_id for child_id in cast("list[object]", raw) if isinstance(child_id, str)]


def _build_node_tables(
    nodes: list[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    """Return ``nodeId`` lookup tables for choice-context checks."""
    by_id: dict[str, Mapping[str, Any]] = {}
    parent_by_id: dict[str, str] = {}
    for node in nodes:
        node_id = _node_id(node)
        if node_id is not None:
            by_id[node_id] = node
    for node in nodes:
        parent_id = _node_id(node)
        if parent_id is None:
            continue
        for child_id in _child_ids(node):
            if child_id in by_id and child_id not in parent_by_id:
                parent_by_id[child_id] = parent_id
    return by_id, parent_by_id


def _choice_context_text(
    node: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    parent_by_id: Mapping[str, str],
) -> str:
    """Return normalized local/ancestor text used for button-choice checks."""
    node_id = _node_id(node)
    parts = [_node_name(node)]
    seen: set[str] = set()
    for _ in range(4):
        if node_id is None or node_id in seen:
            break
        seen.add(node_id)
        parent_id = parent_by_id.get(node_id)
        if parent_id is None:
            break
        parent = by_id.get(parent_id)
        if parent is None:
            break
        parts.append(_node_name(parent))
        node_id = parent_id
    return " ".join(" ".join(part.casefold().split()) for part in parts if part)


def _is_choice_target(
    node: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    parent_by_id: Mapping[str, str],
) -> bool:
    """Return whether ``node`` is a discrete choice target/control."""
    role = _node_role(node)
    if role in CHOICE_TARGET_ROLES:
        return True
    if role != "button":
        return False

    name = " ".join(_node_name(node).casefold().split())
    if _node_property(node, "hasPopup") == "listbox":
        return True
    if name.startswith(("filter", "filters", "sort")):
        return True
    if _node_property(node, "pressed") in {True, False, "true", "false", "mixed"}:
        context = _choice_context_text(node, by_id, parent_by_id)
        return any(term in context for term in _CHOICE_BUTTON_CONTEXT_TERMS)
    return False


def _truncate_name(name: str, *, name_max_length: int) -> str:
    """Strip and truncate an accessible name to ``name_max_length`` chars."""
    stripped = name.strip()
    if len(stripped) <= name_max_length:
        return stripped
    return stripped[:name_max_length]


def _measure_page_scroll(page: Any) -> tuple[int | None, int | None]:
    """Read ``(scroll_height, viewport_height)`` from a Playwright-page-like object.

    Best-effort reads: any failure to evaluate JS or read the viewport is
    folded into ``None`` so :func:`is_page_scrollable` can fall back to the
    axtree ``scrollable`` signal alone (spec §5.4).  Tests pass ``None`` to
    skip the read entirely.
    """
    if page is None:
        return None, None
    scroll_height: int | None = None
    try:
        raw = page.evaluate("document.documentElement.scrollHeight")
    except Exception:  # 3p ``evaluate()`` may surface arbitrary playwright errors
        raw = None
    if isinstance(raw, bool):
        scroll_height = None
    elif isinstance(raw, int):
        scroll_height = raw
    elif isinstance(raw, float):
        scroll_height = int(raw)
    viewport_height: int | None = None
    viewport = getattr(page, "viewport_size", None)
    if isinstance(viewport, Mapping):
        height = cast("Mapping[str, object]", viewport).get("height")
        if isinstance(height, bool):
            pass
        elif isinstance(height, int):
            viewport_height = height
        elif isinstance(height, float):
            viewport_height = int(height)
    return scroll_height, viewport_height


def compute_action_space(
    axtree: Mapping[str, Any],
    dom_object: Mapping[str, Any] | None,
    page: Any,
    *,
    name_max_length: int = NAME_MAX_LENGTH,
) -> dict[str, Any]:
    """Compose the per-page ``action_space.json`` artifact (spec §5.4).

    Walks the BrowserGym merged axtree, skips hidden nodes, applies the
    closed :data:`ROLE_TO_ACTIONS` heuristic to every visible node whose
    role has a counted-actions row, derives non-action target categories
    such as ``choice``, augments the result with the global ``scroll``
    signal, and packages the output as a JSON-ready dict:

    .. code-block:: json

        {
          "vocabulary": ["click", "fill", "hover", "goto", "send_msg_to_user"],
          "by_action": {"click": 78, "fill": 4},
          "by_category": {"choice": 12},
          "elements": [
            {"bid": "a12", "role": "button", "name": "Add to cart",
             "actions": ["click", "dblclick", "hover"]}
          ],
          "subsets": ["chat", "infeas", "bid", "nav", "tab"],
          "heuristic_version": "0.2"
        }

    Determinism contract:

    * ``vocabulary`` is the sorted output of :func:`discover_vocabulary` so
      the artifact is byte-stable across machines and BrowserGym minor
      versions.
    * ``elements`` preserves the axtree node order (CDP DOM order); each
      ``actions`` tuple is the sorted :data:`ROLE_TO_ACTIONS` entry, so the
      list is reproducible across runs against the same axtree.
    * ``by_action`` is sorted by key and only contains verbs with at least
      one counted target.  ``scroll`` is added with value ``1`` exactly when
      :func:`is_page_scrollable` returns ``True`` for the supplied axtree +
      page metrics.
    * ``by_category`` is sorted by key and contains target categories that
      are useful for environment-quality comparisons but are not BrowserGym
      action verbs.
    * ``subsets`` mirrors :data:`ACTION_SUBSETS` in spec order (not
      sorted) so cohort comparisons read identically across runs.

    Args:
        axtree: BrowserGym/CDP merged-axtree object.  Required.
        dom_object: BrowserGym DOM snapshot.  Reserved for v0.x DOM-derived
            heuristics; unused in v0.2 and accepted as ``None``.
        page: Playwright-page-like object exposing ``evaluate("...")`` and
            ``viewport_size``.  Used solely to read
            ``document.documentElement.scrollHeight`` + viewport height
            for the "scrollHeight > viewport" branch of the scroll rule.
            Pass ``None`` (tests, replay) to fall back to the axtree
            ``scrollable``-node signal alone.
        name_max_length: Override for :data:`NAME_MAX_LENGTH`.  Tests pass
            a smaller value to assert truncation rather than the spec
            constant.

    Returns:
        JSON-ready action-space artifact.

    Raises:
        TypeError: ``axtree`` is not a mapping or its ``nodes`` is not a list.
    """
    del dom_object  # reserved for v0.x extensions; unused in v0.2.

    if not isinstance(axtree, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"axtree must be a mapping, got {type(axtree).__name__}")
    raw_nodes: object = axtree.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise TypeError(
            f"axtree['nodes'] must be a list, got {type(raw_nodes).__name__}",
        )

    raw_node_list = cast("list[object]", raw_nodes)
    nodes = [
        cast("Mapping[str, Any]", raw_node)
        for raw_node in raw_node_list
        if isinstance(raw_node, Mapping)
    ]
    by_id, parent_by_id = _build_node_tables(nodes)
    elements: list[dict[str, Any]] = []
    by_action: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for node in nodes:
        if _node_is_hidden(node):
            continue
        role = _node_role(node)
        actions = ROLE_TO_ACTIONS.get(role)
        is_choice = _is_choice_target(node, by_id, parent_by_id)
        if actions is None and not is_choice:
            continue
        if is_choice:
            by_category["choice"] = by_category.get("choice", 0) + 1
        if actions is None:
            continue
        elements.append(
            {
                "bid": _node_bid(node),
                "role": role,
                "name": _truncate_name(_node_name(node), name_max_length=name_max_length),
                "actions": list(actions),
            },
        )
        for verb in actions:
            by_action[verb] = by_action.get(verb, 0) + 1

    scroll_height, viewport_height = _measure_page_scroll(page)
    if is_page_scrollable(
        axtree,
        scroll_height=scroll_height,
        viewport_height=viewport_height,
    ):
        by_action["scroll"] = 1

    return {
        "vocabulary": list(discover_vocabulary()),
        "by_action": dict(sorted(by_action.items())),
        "by_category": dict(sorted(by_category.items())),
        "elements": elements,
        "subsets": list(ACTION_SUBSETS),
        "heuristic_version": HEURISTIC_VERSION,
    }
