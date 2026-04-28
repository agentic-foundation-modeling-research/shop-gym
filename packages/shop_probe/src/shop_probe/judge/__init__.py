"""Axis C: blinded pairwise LLM judge over agent trajectories."""

from shop_probe.judge.anonymize import (
    REDACTED_BRAND,
    REDACTED_HOST,
    REDACTED_THEME,
    AnonymizationPlan,
    anonymize_trajectory,
    hash_token,
)
from shop_probe.judge.pairwise import (
    PairCondition,
    PairwisePair,
    build_control_pairs,
    build_experimental_pairs,
    build_task_pairs,
    real_shop_pool,
)
from shop_probe.judge.prompts import (
    REQUIRED_PAIRWISE_PLACEHOLDERS,
    JudgePromptLoadError,
    JudgePromptSet,
    load_judge_prompts,
)
from shop_probe.judge.tasks import (
    JudgeTask,
    JudgeTaskInteraction,
    JudgeTaskLoadError,
    JudgeTaskSet,
    JudgeTaskSurface,
    load_judge_tasks,
    load_judge_tasks_bytes,
)
from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStatus,
    TrajectoryStep,
)

__all__ = [
    "REDACTED_BRAND",
    "REDACTED_HOST",
    "REDACTED_THEME",
    "REQUIRED_PAIRWISE_PLACEHOLDERS",
    "AnonymizationPlan",
    "JudgePromptLoadError",
    "JudgePromptSet",
    "JudgeTask",
    "JudgeTaskInteraction",
    "JudgeTaskLoadError",
    "JudgeTaskSet",
    "JudgeTaskSurface",
    "PairCondition",
    "PairwisePair",
    "Trajectory",
    "TrajectoryAction",
    "TrajectoryObservation",
    "TrajectoryStatus",
    "TrajectoryStep",
    "anonymize_trajectory",
    "build_control_pairs",
    "build_experimental_pairs",
    "build_task_pairs",
    "hash_token",
    "load_judge_prompts",
    "load_judge_tasks",
    "load_judge_tasks_bytes",
    "real_shop_pool",
]
