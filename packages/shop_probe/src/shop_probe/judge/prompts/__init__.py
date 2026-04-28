"""Axis-C pairwise judge prompt templates (spec §5.5 step 5, §8.3, §5.8).

The prompt templates ship as ``system.md`` + ``pairwise.md`` per
version (e.g. ``v1/``); :func:`load_judge_prompts` loads them, validates
required placeholders, and computes the content hash that pins the
template revision into every :class:`shop_probe.report.JudgeCall`.
"""

from shop_probe.judge.prompts.loader import (
    JudgePromptLoadError,
    compute_content_hash,
    load_judge_prompts,
)
from shop_probe.judge.prompts.schema import (
    REQUIRED_PAIRWISE_PLACEHOLDERS,
    JudgePromptSet,
)

__all__ = [
    "REQUIRED_PAIRWISE_PLACEHOLDERS",
    "JudgePromptLoadError",
    "JudgePromptSet",
    "compute_content_hash",
    "load_judge_prompts",
]
