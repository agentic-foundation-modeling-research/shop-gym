"""Axis A — v1.3 agent-driven advanced tier.

Replaces the deterministic v1.2 ``advanced`` probes with a generic
agent + judge runner driven by inline ``agent_task`` blocks on
``level: agent_driven`` rubric entries.

See ``docs/specs/shop_arena/web_probe_v1_3_agent_driven.md`` for the
spec; ``docs/impl/web_probe_v1_3_agent_driven_implementation.md`` for
the implementation plan.

This module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from shop_probe.agent.config import AgentRuntimeConfig, AgentRuntimeName
from shop_probe.agent.runner import run_agent_task

__all__ = [
    "AgentRuntimeConfig",
    "AgentRuntimeName",
    "run_agent_task",
]
