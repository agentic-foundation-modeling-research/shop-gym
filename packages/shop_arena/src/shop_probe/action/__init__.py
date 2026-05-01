"""``action`` family — what the agent can do.

Two subfamilies:

* :mod:`shop_probe.action.space` — mechanical, deterministic action-space
  metrics (per modality).
* :mod:`shop_probe.action.control_slots` — single-modality LLM judge over
  canonical control slots per page type.
"""

from __future__ import annotations

from shop_probe.action.control_slots import judge_control_slots
from shop_probe.action.space import compute_action_space

__all__ = ["compute_action_space", "judge_control_slots"]
