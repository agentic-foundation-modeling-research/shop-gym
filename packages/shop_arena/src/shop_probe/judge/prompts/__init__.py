"""Axis-C pairwise judge prompt templates (spec §5.5 step 5, §8.3, §5.8).

The prompt templates ship as ``system.md`` + ``pairwise.md`` per
version (e.g. ``v1/``); :func:`load_judge_prompts` loads them, validates
required placeholders, and computes the content hash that pins the
template revision into every :class:`shop_probe.report.JudgeCall`.
"""

from shop_probe.judge.prompts.loader import (
    JudgePromptLoadError,
    compute_content_hash,
    compute_likert_content_hash,
    load_judge_prompts,
    load_likert_prompts,
)
from shop_probe.judge.prompts.schema import (
    REQUIRED_LIKERT_PLACEHOLDERS,
    REQUIRED_PAIRWISE_PLACEHOLDERS,
    JudgePromptSet,
    LikertPromptSet,
)

__all__ = [
    "REQUIRED_LIKERT_PLACEHOLDERS",
    "REQUIRED_PAIRWISE_PLACEHOLDERS",
    "JudgePromptLoadError",
    "JudgePromptSet",
    "LikertPromptSet",
    "compute_content_hash",
    "compute_likert_content_hash",
    "load_judge_prompts",
    "load_likert_prompts",
]
