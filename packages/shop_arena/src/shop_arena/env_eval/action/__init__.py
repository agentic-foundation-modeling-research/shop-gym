"""Action layer: BrowserGym ``HighLevelActionSet`` vocabulary + role/action heuristic.

Spec §5.4. The single submodule today is :mod:`heuristic`, which owns the
versioned ``ACTION_SUBSETS`` / ``HEURISTIC_VERSION`` constants, the
``ROLE_TO_ACTIONS`` mapping, scroll detection, and the
``compute_action_space`` composition that produces the per-page
``action/<bucket>.action_space.json`` artifact.

Future submodules (vocabulary discovery, role tables, scroll heuristics,
…) plug in alongside ``heuristic.py`` and are re-exported here so the
``shop_arena.env_eval.action`` import surface stays stable.
"""

from __future__ import annotations

from shop_arena.env_eval.action.heuristic import (
    ACTION_SUBSETS,
    CHOICE_TARGET_ROLES,
    CLICKABLE_ROLES,
    HEURISTIC_VERSION,
    NAME_MAX_LENGTH,
    ROLE_TO_ACTIONS,
    SELECT_ROLES,
    TEXT_INPUT_ROLES,
    compute_action_space,
    discover_vocabulary,
    is_page_scrollable,
)

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
