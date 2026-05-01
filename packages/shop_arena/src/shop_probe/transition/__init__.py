"""``transition`` family — scripted Playwright probes (modality-agnostic).

For each canonical control slot, a script attempts the action via a
role+name locator (the way an agent would) and records four bits:
``action_found``, ``action_executed``, ``state_changed``, and
``state_changed_as_expected``, plus a ``latency_ms`` measurement.
"""

from __future__ import annotations

from shop_probe.transition.runner import run_transitions

__all__ = ["run_transitions"]
