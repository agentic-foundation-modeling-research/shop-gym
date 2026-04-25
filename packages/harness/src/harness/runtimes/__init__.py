"""Runtime adapters for the plan + exec harness.

Each adapter implements the `AgentRuntime` Protocol from
`harness.runtimes.base` and is selected by name via a small registry
(populated in a later milestone).
"""

from __future__ import annotations

from harness.runtimes.base import AgentRuntime, RuntimeIterationResult

__all__ = ["AgentRuntime", "RuntimeIterationResult"]
