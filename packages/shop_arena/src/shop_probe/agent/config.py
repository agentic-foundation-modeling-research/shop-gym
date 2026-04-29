"""Runtime configuration for the v1.3 agent-driven advanced tier.

Implements the ``AgentRuntimeConfig`` value type referenced by spec
``docs/specs/shop_arena/web_probe_v1_3_agent_driven.md`` §5 and the
implementation plan ``docs/impl/web_probe_v1_3_agent_driven_implementation.md``
T1.2.

The dataclass is the single carrier of CLI ``--agent-*`` flags through to
the generic agent runner (``shop_probe.agent.runner.run_agent_task``) and
the completion judge (``shop_probe.agent.judge.run_completion_judge``).
Per-task overrides on the inline ``AgentTaskInline`` block (``step_budget``
/ ``timeout_s``) take precedence when set.

This module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AgentRuntimeName = Literal["claude_code", "pi"]
"""Supported agent runtime back-ends.

* ``claude_code`` — default; Anthropic Claude Code CLI runtime.
* ``pi`` — alternate; pi coding-agent runtime. Both auto-load the
  project-level ``playwright-browser`` skill.
"""


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    """Frozen runtime configuration for one agent-driven probe execution.

    Attributes:
        runtime: Which harness runtime back-end drives the agent loop.
            Defaults to ``"claude_code"``.
        model: Model id passed to the agent runtime for plan/exec turns.
            Defaults to ``"claude-opus-4-7"``.
        step_budget: Default max iterations for the harness plan/exec
            loop. Per-task overrides on ``AgentTaskInline.step_budget``
            take precedence when set.
        timeout_s: Default wall-clock budget (seconds) for one agent
            task run. Per-task overrides on ``AgentTaskInline.timeout_s``
            take precedence when set.
        judge_model: Model id used for the vision completion judge.
            Defaults to ``"claude-opus-4-7"``.
    """

    runtime: AgentRuntimeName = "claude_code"
    model: str = "claude-opus-4-7"
    step_budget: int = 15
    timeout_s: int = 180
    judge_model: str = "claude-opus-4-7"
