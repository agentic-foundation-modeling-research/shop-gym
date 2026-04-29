"""Axis C: per-shop Turing-test classifier (web_probe_patch.md)."""

from shop_probe.judge.agent import DEFAULT_AGENTS_MD, run_judge_agent
from shop_probe.judge.anonymize import (
    REDACTED_BRAND,
    REDACTED_HOST,
    REDACTED_THEME,
    AnonymizationPlan,
    anonymize_trajectory,
    hash_token,
)
from shop_probe.judge.run import (
    ClassifierFn,
    ClassifierResult,
    classify_shop,
    classify_trajectory,
    judge_calls_from_results,
    render_trajectory_for_judge,
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
    "DEFAULT_AGENTS_MD",
    "REDACTED_BRAND",
    "REDACTED_HOST",
    "REDACTED_THEME",
    "AnonymizationPlan",
    "ClassifierFn",
    "ClassifierResult",
    "JudgeTask",
    "JudgeTaskInteraction",
    "JudgeTaskLoadError",
    "JudgeTaskSet",
    "JudgeTaskSurface",
    "Trajectory",
    "TrajectoryAction",
    "TrajectoryObservation",
    "TrajectoryStatus",
    "TrajectoryStep",
    "anonymize_trajectory",
    "classify_shop",
    "classify_trajectory",
    "hash_token",
    "judge_calls_from_results",
    "load_judge_tasks",
    "load_judge_tasks_bytes",
    "render_trajectory_for_judge",
    "run_judge_agent",
]
