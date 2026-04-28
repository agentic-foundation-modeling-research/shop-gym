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
from shop_probe.judge.run import (
    M4_SWAP_DROP_RATE_THRESHOLD,
    M4GateMetrics,
    PairJudgeOutcome,
    judge_calls_from_outcomes,
    judge_pair_for_task,
    m4_gate_metrics,
    render_trajectory_for_judge,
)
from shop_probe.judge.scoring import JudgeAccuracy, score_judge_calls
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
    "M4_SWAP_DROP_RATE_THRESHOLD",
    "REDACTED_BRAND",
    "REDACTED_HOST",
    "REDACTED_THEME",
    "REQUIRED_LIKERT_PLACEHOLDERS",
    "REQUIRED_PAIRWISE_PLACEHOLDERS",
    "AnonymizationPlan",
    "CrossJudgeAgreement",
    "JudgeAccuracy",
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
    "M4GateMetrics",
    "PairCondition",
    "PairJudgeOutcome",
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
    "judge_calls_from_outcomes",
    "judge_pair_for_task",
    "load_judge_prompts",
    "load_judge_tasks",
    "load_judge_tasks_bytes",
    "load_likert_prompts",
    "m4_gate_metrics",
    "presentations_for",
    "real_shop_pool",
    "render_trajectory_for_judge",
    "run_judge_agent",
    "score_judge_calls",
    "swap_drop_rate",
]
