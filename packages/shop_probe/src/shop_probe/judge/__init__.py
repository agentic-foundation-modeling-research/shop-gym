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
from shop_probe.judge.kappa import (
    CrossJudgeAgreement,
    compute_cross_judge_kappa,
)
from shop_probe.judge.likert import (
    LikertJudge,
    LikertOutcome,
    compute_likert_distributions,
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
    REQUIRED_LIKERT_PLACEHOLDERS,
    REQUIRED_PAIRWISE_PLACEHOLDERS,
    JudgePromptLoadError,
    JudgePromptSet,
    LikertPromptSet,
    load_judge_prompts,
    load_likert_prompts,
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
    "REQUIRED_LIKERT_PLACEHOLDERS",
    "REQUIRED_PAIRWISE_PLACEHOLDERS",
    "AnonymizationPlan",
    "CrossJudgeAgreement",
    "JudgeCallable",
    "JudgePromptLoadError",
    "JudgePromptSet",
    "JudgeTask",
    "JudgeTaskInteraction",
    "JudgeTaskLoadError",
    "JudgeTaskSet",
    "JudgeTaskSurface",
    "LLMClient",
    "LikertJudge",
    "LikertOutcome",
    "LikertPromptSet",
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
    "compute_cross_judge_kappa",
    "compute_likert_distributions",
    "evaluate_swap_consistency",
    "hash_token",
    "is_swap_consistent",
    "load_judge_prompts",
    "load_judge_tasks",
    "load_judge_tasks_bytes",
    "load_likert_prompts",
    "presentations_for",
    "real_shop_pool",
    "run_judge_agent",
    "swap_drop_rate",
]
