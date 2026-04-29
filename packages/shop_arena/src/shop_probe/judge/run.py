"""Per-shop Turing-test classification (``web_probe_patch.md``).

Replaces the prior pairwise + swap-consistency orchestrator. The new
judge is a per-shop classifier: shown the evidence for one shop, it
predicts whether the shop is ``sandbox`` or ``real`` (or abstains).
Group-level accuracy is computed at stage 2 by
:func:`shop_probe.fidelity.compute_bench_comparison`.

This module is intentionally minimal. It defines:

* :data:`ClassifierFn` — callable shape an LLM-backed (or stub) classifier
  must satisfy.
* :func:`classify_trajectory` — render an anonymized
  :class:`~shop_probe.judge.trajectory.Trajectory` and invoke a
  classifier, returning one closed
  :class:`~shop_probe.report.JudgeCall`.
* :func:`classify_shop` — convenience helper that runs a classifier
  ``samples`` times against the same trajectory and returns the
  resulting :class:`JudgeCall` rows in input order.

Production wiring (LLM client, prompt rendering, cost accounting) is left
to a follow-on patch — the spec patch's "Open questions" section calls
out the per-shop sample budget as TBD and reserves the wiring choices.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from shop_probe.judge.trajectory import Trajectory, TrajectoryStep
from shop_probe.report import JudgeCall


@dataclass(frozen=True, slots=True)
class ClassifierResult:
    """Closed return type for a classifier callable.

    Attributes:
        predicted_label: One of ``"sandbox"``, ``"real"``, or
            ``"abstain"``.
        prompt_hash: 64-char hex SHA-256 of the prompt template used.
        response: Full raw response text from the model.
        latency_ms: Wall-clock latency for the LLM call, in milliseconds.
        cost_usd: Estimated USD cost for the call.
        model_id: Pinned model identifier used for the call.
    """

    predicted_label: str
    prompt_hash: str
    response: str
    latency_ms: float
    cost_usd: float
    model_id: str


ClassifierFn = Callable[[str], ClassifierResult]
"""Per-shop classifier signature.

The argument is the rendered (anonymized) trajectory text; the return
value is a :class:`ClassifierResult` carrying the decision plus metadata
needed to construct a :class:`shop_probe.report.JudgeCall`.
"""


def render_trajectory_for_judge(trajectory: Trajectory) -> str:
    """Render an anonymized :class:`Trajectory` to plain text for the judge prompt.

    Format pins:

    * One header line: ``target: <anonymized_name>``.
    * One ``step_NN: <description>`` line per step plus per-step
      screenshot / snapshot path lines. Indices are zero-padded so
      ``"screenshot_07"`` is a literal substring.

    Anonymization (spec §5.5 step 3) MUST run before this rendering — the
    closed :class:`Trajectory` carries the ``anonymized`` flag and this
    function refuses to render an un-anonymized trajectory.

    Args:
        trajectory: An anonymized :class:`Trajectory`.

    Returns:
        Plain-text rendering of the trajectory, terminated with a single
        trailing newline.

    Raises:
        ValueError: ``trajectory.anonymized`` is ``False``.
    """
    if not trajectory.anonymized:
        msg = (
            "render_trajectory_for_judge requires an anonymized trajectory; "
            f"got anonymized={trajectory.anonymized!r} on {trajectory.target.name!r}"
        )
        raise ValueError(msg)
    lines: list[str] = [f"target: {trajectory.target.name}"]
    for step in trajectory.steps:
        lines.extend(_render_step(step))
    return "\n".join(lines) + "\n"


def _render_step(step: TrajectoryStep) -> list[str]:
    """Render one :class:`TrajectoryStep` as a sub-block."""
    head = f"step_{step.index:02d}: {step.action.description}"
    if step.observation.url is not None:
        head = f"{head} -> {step.observation.url}"
    out = [
        head,
        f"  screenshot_{step.index:02d}: {step.observation.screenshot.path}",
        f"  snapshot_{step.index:02d}: {step.observation.a11y_snapshot.path}",
    ]
    if step.reasoning:
        out.append(f"  reasoning: {step.reasoning}")
    return out


def classify_trajectory(
    trajectory: Trajectory,
    classifier: ClassifierFn,
) -> JudgeCall:
    """Render ``trajectory`` and ask ``classifier`` to label it.

    Args:
        trajectory: An anonymized :class:`Trajectory` for one shop.
        classifier: A :data:`ClassifierFn` (LLM-backed or stub).

    Returns:
        A closed :class:`JudgeCall` carrying the classifier's decision
        plus the metadata it reported.

    Raises:
        ValueError: The classifier returned a ``predicted_label`` outside
            ``{"sandbox", "real", "abstain"}``.
    """
    rendered = render_trajectory_for_judge(trajectory)
    result = classifier(rendered)
    if result.predicted_label not in {"sandbox", "real", "abstain"}:
        msg = (
            f"classify_trajectory: classifier returned invalid "
            f"predicted_label={result.predicted_label!r}"
        )
        raise ValueError(msg)
    return JudgeCall(
        predicted_label=result.predicted_label,  # type: ignore[arg-type]
        prompt_hash=result.prompt_hash,
        response=result.response,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        model_id=result.model_id,
    )


def classify_shop(
    trajectory: Trajectory,
    classifier: ClassifierFn,
    *,
    samples: int,
) -> tuple[JudgeCall, ...]:
    """Run ``classifier`` on ``trajectory`` ``samples`` times.

    Args:
        trajectory: An anonymized :class:`Trajectory` for one shop.
        classifier: A :data:`ClassifierFn`.
        samples: Number of independent calls to make. Must be ``≥ 1``.

    Returns:
        :class:`JudgeCall` rows in invocation order.

    Raises:
        ValueError: ``samples`` is less than 1.
    """
    if samples < 1:
        msg = f"classify_shop: samples must be >= 1 (got {samples})"
        raise ValueError(msg)
    return tuple(classify_trajectory(trajectory, classifier) for _ in range(samples))


def judge_calls_from_results(results: Sequence[ClassifierResult]) -> tuple[JudgeCall, ...]:
    """Project a sequence of :class:`ClassifierResult` rows into :class:`JudgeCall` rows.

    Convenience helper for callers that already have decisions in hand
    (e.g. tests, replay).
    """
    out: list[JudgeCall] = []
    for r in results:
        if r.predicted_label not in {"sandbox", "real", "abstain"}:
            msg = f"judge_calls_from_results: invalid predicted_label={r.predicted_label!r}"
            raise ValueError(msg)
        out.append(
            JudgeCall(
                predicted_label=r.predicted_label,  # type: ignore[arg-type]
                prompt_hash=r.prompt_hash,
                response=r.response,
                latency_ms=r.latency_ms,
                cost_usd=r.cost_usd,
                model_id=r.model_id,
            )
        )
    return tuple(out)
