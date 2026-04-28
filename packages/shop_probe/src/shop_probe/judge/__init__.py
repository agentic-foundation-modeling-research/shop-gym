"""Axis C: blinded pairwise LLM judge over agent trajectories."""

from shop_probe.judge.agent import DEFAULT_AGENTS_MD, run_judge_agent
from shop_probe.judge.anonymize import (
    REDACTED_BRAND,
    REDACTED_HOST,
    REDACTED_THEME,
    AnonymizationPlan,
    anonymize_trajectory,
    hash_token,
)
from shop_probe.judge.llm import (
    LLMClient,
    PinnedJudge,
    PinnedJudgeOutcome,
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
from shop_probe.judge.swap import (
    JudgeCallable,
    Presentation,
    SwapConsistencyResult,
    evaluate_swap_consistency,
    is_swap_consistent,
    presentations_for,
    swap_drop_rate,
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
    "REQUIRED_PAIRWISE_PLACEHOLDERS",
    "AnonymizationPlan",
    "JudgeCallable",
    "JudgePromptLoadError",
    "JudgePromptSet",
    "JudgeTask",
    "JudgeTaskInteraction",
    "JudgeTaskLoadError",
    "JudgeTaskSet",
    "JudgeTaskSurface",
    "LLMClient",
    "PairCondition",
    "PairwisePair",
    "PinnedJudge",
    "PinnedJudgeOutcome",
    "Presentation",
    "SwapConsistencyResult",
    "Trajectory",
    "TrajectoryAction",
    "TrajectoryObservation",
    "TrajectoryStatus",
    "TrajectoryStep",
    "anonymize_trajectory",
    "build_control_pairs",
    "build_experimental_pairs",
    "build_task_pairs",
    "evaluate_swap_consistency",
    "hash_token",
    "is_swap_consistent",
    "load_judge_prompts",
    "load_judge_tasks",
    "load_judge_tasks_bytes",
    "presentations_for",
    "real_shop_pool",
    "run_judge_agent",
    "swap_drop_rate",
]
