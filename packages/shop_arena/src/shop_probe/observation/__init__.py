"""``observation`` family — what the agent perceives without acting.

Two subfamilies:

* :mod:`shop_probe.observation.shape` — mechanical, deterministic metrics
  on the agent's observation (per modality).
* :mod:`shop_probe.observation.info_slots` — single-modality LLM judge
  over canonical info slots per page type.
"""

from __future__ import annotations

from shop_probe.observation.info_slots import judge_info_slots
from shop_probe.observation.shape import compute_shape

__all__ = ["compute_shape", "judge_info_slots"]
