"""Axis-C judge task list (spec §5.5 step 1, §5.5.1, §5.8).

The task list is intentionally separate from the 108-task ShopGuru
benchmark per spec §5.5.1: ShopGuru measures *behavioural* fidelity
while these tasks are tuned for *judge diagnosticity* (visually rich,
multi-page, interaction-heavy).
"""

from shop_probe.judge.tasks.loader import (
    JudgeTaskLoadError,
    compute_content_hash,
    load_judge_tasks,
    load_judge_tasks_bytes,
)
from shop_probe.judge.tasks.schema import (
    JudgeTask,
    JudgeTaskInteraction,
    JudgeTaskSet,
    JudgeTaskSurface,
)

__all__ = [
    "JudgeTask",
    "JudgeTaskInteraction",
    "JudgeTaskLoadError",
    "JudgeTaskSet",
    "JudgeTaskSurface",
    "compute_content_hash",
    "load_judge_tasks",
    "load_judge_tasks_bytes",
]
