"""Single-modality LLM judge for v1.0 info_slots and control_slots.

Each judge call sees **one** modality (a11y JSON or screenshot, never
both), so for any slot run on both modalities the runner issues two
calls and the cohort report can compute ``cross_modal_consistent`` per
spec §5.3.
"""

from __future__ import annotations

from shop_arena.probe.judge.client import judge_slot, open_judge_client, split_provider
from shop_arena.probe.judge.env import (
    MissingJudgeCredentialsError,
    load_agent_env,
    require_credentials,
)

__all__ = [
    "MissingJudgeCredentialsError",
    "judge_slot",
    "load_agent_env",
    "open_judge_client",
    "require_credentials",
    "split_provider",
]
