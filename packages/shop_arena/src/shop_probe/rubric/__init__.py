"""Capability-coverage rubric (axis A): schema, loader, and frozen YAML."""

from shop_probe.rubric.loader import (
    RubricLoadError,
    compute_content_hash,
    load_rubric,
    load_rubric_bytes,
)
from shop_probe.rubric.schema import (
    AgentTaskInline,
    CaptureJudgeTask,
    PageRef,
    Rubric,
    RubricCategory,
    RubricEntry,
    RubricLevel,
)

__all__ = [
    "AgentTaskInline",
    "CaptureJudgeTask",
    "PageRef",
    "Rubric",
    "RubricCategory",
    "RubricEntry",
    "RubricLevel",
    "RubricLoadError",
    "compute_content_hash",
    "load_rubric",
    "load_rubric_bytes",
]
