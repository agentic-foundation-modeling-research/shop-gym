"""End-to-end orchestration for the M4 pairwise-judge gate (T4.9 — spec §7 M4).

The individual axis-C building blocks already live in this package:

* :mod:`shop_probe.judge.agent` (T4.2) records a :class:`Trajectory` per
  ``(target, task)`` invocation.
* :mod:`shop_probe.judge.anonymize` (T4.4) strips brand-y signal from a
  populated :class:`Trajectory`.
* :mod:`shop_probe.judge.pairwise` (T4.5) builds canonical experimental +
  control :class:`PairwisePair` populations from a :class:`Cohort`.
* :mod:`shop_probe.judge.llm` (T4.6) wraps the pinned LLM judge call.
* :mod:`shop_probe.judge.prompts` (T4.7) renders the frozen pairwise prompt.
* :mod:`shop_probe.judge.swap` (T4.8) reduces two presentations into one
  swap-consistency result and reports the drop rate.

T4.9 is the operational pass that ties them together for the M4 gate
(spec §7 M4: ``swap-inconsistency rate ≤ 5%``). One :class:`PairwisePair`
x one :class:`JudgeTask` produces one :class:`PairJudgeOutcome` carrying
two :class:`shop_probe.report.JudgeCall` rows (one per presentation
order) plus the shared ``swap_consistent`` flag. Aggregating those over
the pair population gives :class:`M4GateMetrics`, the closed summary the
spec §7 M4 gate is checked against.

The module is deliberately decoupled from any specific runtime / LLM:
production wiring passes a real :class:`shop_probe.judge.agent.AgentRuntime`
(whose Playwright session records the per-target HAR + screenshots
required by spec §7 M4) and a real OpenAI-backed
:class:`shop_probe.judge.llm.LLMClient`; tests pass stubs. The orchestrator
itself never opens a browser or touches the network — that boundary is
what keeps the M4 gate reproducible without live API access.

The module is import-safe; it performs no I/O at import time. On-disk
trajectory persistence is owned by :func:`shop_probe.judge.agent.run_judge_agent`
and the pinned-judge artefact persistence is owned by
:meth:`shop_probe.judge.llm.PinnedJudge.judge_presentation` (the raw
prompt + raw response live on each :class:`PinnedJudgeOutcome`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from shop_probe.judge.anonymize import AnonymizationPlan, anonymize_trajectory
from shop_probe.judge.llm import PinnedJudge, PinnedJudgeOutcome
from shop_probe.judge.pairwise import PairCondition, PairwisePair
from shop_probe.judge.swap import is_swap_consistent, presentations_for
from shop_probe.judge.tasks import JudgeTask
from shop_probe.judge.trajectory import Trajectory, TrajectoryStep
from shop_probe.report import JudgeCall, JudgePick, JudgeTruth
from shop_probe.targets import Target

M4_SWAP_DROP_RATE_THRESHOLD: Final[float] = 0.05
"""Spec §7 M4 gate: pairwise judge must drop ≤ 5% of pairs on swap."""

_ABSTAIN_PICK: Final[JudgePick] = "abstain"
"""Marker pick we record on a discarded :class:`PinnedJudgeOutcome`.

Spec §5.5 guardrails: parse-error and no-evidence calls are discarded
*from scoring*, but the report header still needs a pick literal so the
closed :class:`shop_probe.report.JudgeCall` schema validates. Mapping
discard → ``"abstain"`` matches what
:meth:`shop_probe.judge.llm.PinnedJudge.as_judge_callable` already does
for the swap-consistency layer; doing the same here keeps the two layers
aligned.
"""


def render_trajectory_for_judge(trajectory: Trajectory) -> str:
    """Render an anonymized :class:`Trajectory` to plain text for the judge prompt.

    The pairwise prompt template (spec §8.3) splices the rendered text
    inline. Format pins:

    * One header line: ``target: <anonymized_label>`` so the
      :class:`shop_probe.judge.llm.PinnedJudge` user prompt carries a
      stable per-trajectory marker the swap-aggregator can read.
    * One ``step_NN: <description>`` line per step plus per-step
      screenshot / snapshot path lines. Indices are zero-padded so
      ``"screenshot_07"`` (spec §8.3 example) is a literal substring.

    Anonymization (spec §5.5 step 3, T4.4) MUST run before this rendering
    — the closed :class:`Trajectory` carries the ``anonymized`` flag and
    this function refuses to render an un-anonymized trajectory so the
    judge wiring (T4.6) cannot accidentally leak brand strings.

    Args:
        trajectory: An anonymized :class:`Trajectory`. The schema's
            ``anonymized=True`` flag is required.

    Returns:
        Plain-text rendering of the trajectory, terminated with a single
        trailing newline.

    Raises:
        ValueError: ``trajectory.anonymized`` is ``False``.
    """
    if not trajectory.anonymized:
        msg = (
            f"render_trajectory_for_judge requires an anonymized trajectory; "
            f"got anonymized={trajectory.anonymized!r} on {trajectory.target.label!r}"
        )
        raise ValueError(msg)
    lines: list[str] = [f"target: {trajectory.target.label}"]
    for step in trajectory.steps:
        lines.extend(_render_step(step))
    return "\n".join(lines) + "\n"


def _render_step(step: TrajectoryStep) -> list[str]:
    """Render one :class:`TrajectoryStep` as a sub-block of the trajectory."""
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


@dataclass(frozen=True, slots=True)
class PairJudgeOutcome:
    """One :class:`PairwisePair` x one :class:`JudgeTask` outcome.

    Spec §5.5 step 5 + step 6: each pair is presented to the judge twice
    — canonical (``swap=False``) and swapped (``swap=True``). This
    dataclass carries the two resulting :class:`shop_probe.report.JudgeCall`
    rows plus the reduced ``swap_consistent`` flag from spec §5.5 step 6.

    Attributes:
        pair_id: Canonical pair id (matches
            :attr:`PairwisePair.pair_id`).
        condition: Pair population (see :data:`PairCondition`).
        task_id: Judge task id from ``judge/tasks/<version>.yaml``.
        judge_calls: ``(unswapped, swapped)`` :class:`JudgeCall` rows in
            presentation order. Both share ``swap_consistent`` per spec
            §5.5 step 6.
        swap_consistent: ``True`` iff the judge tracked the shop, not the
            slot (spec §5.5 step 6). Identical to
            ``judge_calls[0].swap_consistent`` and
            ``judge_calls[1].swap_consistent``.
    """

    pair_id: str
    condition: PairCondition
    task_id: str
    judge_calls: tuple[JudgeCall, JudgeCall]
    swap_consistent: bool


def judge_pair_for_task(
    *,
    pair: PairwisePair,
    task: JudgeTask,
    member_a_trajectory: Trajectory,
    member_b_trajectory: Trajectory,
    anonymization_plan: AnonymizationPlan,
    judge: PinnedJudge,
) -> PairJudgeOutcome:
    """Run one :class:`PairwisePair` x one :class:`JudgeTask` end-to-end.

    Drives :meth:`PinnedJudge.judge_presentation` twice — once on the
    canonical presentation, once on the A/B-swapped presentation per
    spec §5.5 step 6 — and reduces the two picks through
    :func:`shop_probe.judge.swap.is_swap_consistent`. Each presentation
    yields one :class:`shop_probe.report.JudgeCall` carrying the pinned
    prompt hash, the raw response, and the
    :data:`~shop_probe.report.JudgeTruth` slot for that presentation
    (per spec §5.5 step 7).

    The orchestrator owns the spec §5.5 step 3 anonymization step: the
    caller passes raw :class:`Trajectory` rows produced by the agent
    runner (T4.2) plus a shared :class:`AnonymizationPlan` (T4.4) and
    this function applies the plan to both members before rendering.
    A single shared plan keeps the rewrite symmetric across the pair
    (spec §5.5 step 3 invariant) so the judge cannot detect rewrite
    asymmetry instead of the storefront.

    The function never opens a browser or hits the network: every
    Playwright + LLM side effect lives in :class:`PinnedJudge.client`.

    Args:
        pair: Canonical pair built by :mod:`shop_probe.judge.pairwise`.
        task: Judge-diagnostic task whose ``description`` enters the
            user prompt (spec §5.5 step 1).
        member_a_trajectory: Raw :class:`Trajectory` for ``pair.members[0]``.
            ``target.label`` must match ``pair.members[0].label``;
            ``anonymized`` must be ``False`` (the orchestrator owns
            anonymization).
        member_b_trajectory: Raw :class:`Trajectory` for ``pair.members[1]``.
            Same invariants as ``member_a_trajectory``.
        anonymization_plan: Shared anonymization plan applied to both
            members (spec §5.5 step 3, T4.4).
        judge: Pinned LLM judge wiring from T4.6.

    Returns:
        A :class:`PairJudgeOutcome` with two :class:`JudgeCall` rows
        (unswapped, swapped) and the reduced ``swap_consistent`` flag.

    Raises:
        ValueError: A trajectory belongs to a target other than the
            corresponding canonical pair member, or has already been
            anonymized (the orchestrator owns that step).
    """
    _check_not_anonymized(member_a_trajectory)
    _check_not_anonymized(member_b_trajectory)
    _check_member(pair, member_a_trajectory, position=0)
    _check_member(pair, member_b_trajectory, position=1)

    anon_a = anonymize_trajectory(member_a_trajectory, anonymization_plan)
    anon_b = anonymize_trajectory(member_b_trajectory, anonymization_plan)
    rendered_a = render_trajectory_for_judge(anon_a)
    rendered_b = render_trajectory_for_judge(anon_b)

    unswapped, swapped = presentations_for(pair)
    unswapped_outcome = judge.judge_presentation(
        unswapped,
        task=task,
        trajectory_a=rendered_a,
        trajectory_b=rendered_b,
    )
    swapped_outcome = judge.judge_presentation(
        swapped,
        task=task,
        # Swap the slots: A=members[1], B=members[0] (spec §5.5 step 6).
        trajectory_a=rendered_b,
        trajectory_b=rendered_a,
    )

    unswapped_pick = _pick_for_swap_layer(unswapped_outcome)
    swapped_pick = _pick_for_swap_layer(swapped_outcome)
    consistent = is_swap_consistent(unswapped_pick, swapped_pick)

    truth_member = pair.members[1] if pair.condition == "experimental" else pair.members[0]
    unswapped_call = _build_judge_call(
        task_id=task.id,
        anon_pair_label=(anon_a.target.label, anon_b.target.label),
        outcome=unswapped_outcome,
        truth=_truth_for(position_a_member=pair.members[0], truth_member=truth_member),
        swap_consistent=consistent,
    )
    swapped_call = _build_judge_call(
        task_id=task.id,
        anon_pair_label=(anon_b.target.label, anon_a.target.label),
        outcome=swapped_outcome,
        truth=_truth_for(position_a_member=pair.members[1], truth_member=truth_member),
        swap_consistent=consistent,
    )
    return PairJudgeOutcome(
        pair_id=pair.pair_id,
        condition=pair.condition,
        task_id=task.id,
        judge_calls=(unswapped_call, swapped_call),
        swap_consistent=consistent,
    )


def _check_member(pair: PairwisePair, trajectory: Trajectory, *, position: int) -> None:
    """Reject trajectories whose target does not match the canonical pair member."""
    expected_label = pair.members[position].label
    if trajectory.target.label != expected_label:
        msg = (
            f"pair {pair.pair_id!r}: members[{position}].label is "
            f"{expected_label!r} but trajectory.target.label is "
            f"{trajectory.target.label!r}"
        )
        raise ValueError(msg)


def _check_not_anonymized(trajectory: Trajectory) -> None:
    """Reject already-anonymized trajectories — the orchestrator owns that step."""
    if trajectory.anonymized:
        msg = (
            f"trajectory for {trajectory.target.label!r} is already anonymized; "
            "judge_pair_for_task owns anonymization (spec §5.5 step 3) — pass the raw "
            "trajectory plus an AnonymizationPlan"
        )
        raise ValueError(msg)


def _pick_for_swap_layer(outcome: PinnedJudgeOutcome) -> JudgePick:
    """Map a :class:`PinnedJudgeOutcome` onto the swap-layer pick literal.

    Spec §5.5 guardrails: parse-error and no-evidence calls are discarded
    from scoring. Both surface as ``"abstain"`` to the swap aggregator,
    which already drops abstentions (see
    :func:`shop_probe.judge.swap.is_swap_consistent`).
    """
    if outcome.discard_reason is not None or outcome.pick is None:
        return _ABSTAIN_PICK
    return outcome.pick


def _build_judge_call(
    *,
    task_id: str,
    anon_pair_label: tuple[str, str],
    outcome: PinnedJudgeOutcome,
    truth: JudgeTruth,
    swap_consistent: bool,
) -> JudgeCall:
    """Project one :class:`PinnedJudgeOutcome` onto a closed :class:`JudgeCall`."""
    pick: JudgePick = _ABSTAIN_PICK if outcome.pick is None else outcome.pick
    return JudgeCall(
        task_id=task_id,
        pair_label=anon_pair_label,
        judge_pick=pick,
        truth=truth,
        swap_consistent=swap_consistent,
        evidence_cited=outcome.evidence_cited,
        confidence=outcome.confidence,
        prompt_hash=outcome.prompt_hash,
        response_text=outcome.raw_response,
    )


def _truth_for(*, position_a_member: Target, truth_member: Target) -> JudgeTruth:
    """Return the slot ("A" / "B") holding the designated truth member (spec §5.5 step 7).

    For experimental ``(sandbox, source)`` pairs the caller designates
    the source as the truth member — ``judge_accuracy_experimental`` is
    the fraction of calls where the judge picks the source.

    For control ``(real, real)`` pairs neither member is "synthetic";
    the caller designates ``pair.members[0]`` as the "real" slot so the
    closed :class:`shop_probe.report.JudgeCall` schema has a determinate
    ``truth`` literal. The resulting ``judge_accuracy_control`` is the
    noise floor (spec §5.2 + §5.5 step 7), interpreted as a deviation
    from chance, not a correctness rate.
    """
    if position_a_member.label == truth_member.label:
        return "A"
    return "B"


@dataclass(frozen=True, slots=True)
class M4GateMetrics:
    """Aggregated spec §7 M4 gate metrics over a pair population.

    The headline number is :attr:`swap_drop_rate` — the fraction of
    pairs the judge flipped on per-spec §5.5 step 6. Spec §7 M4 gates
    that on ``≤ 0.05`` (5%); :attr:`passes_gate` exposes that check
    directly so callers do not have to re-encode the threshold.

    Attributes:
        n_pairs: Number of pairs scored.
        n_inconsistent: Number of pairs whose pick flipped on swap.
        swap_drop_rate: ``n_inconsistent / n_pairs`` in ``[0.0, 1.0]``.
            Returns ``0.0`` for an empty input (no pairs run → no drops),
            matching :func:`shop_probe.judge.swap.swap_drop_rate`.
    """

    n_pairs: int
    n_inconsistent: int
    swap_drop_rate: float

    @property
    def passes_gate(self) -> bool:
        """``True`` iff the spec §7 M4 gate (≤ 5% drop rate) is met."""
        return self.swap_drop_rate <= M4_SWAP_DROP_RATE_THRESHOLD


def m4_gate_metrics(outcomes: Sequence[PairJudgeOutcome]) -> M4GateMetrics:
    """Aggregate :class:`PairJudgeOutcome` rows into the spec §7 M4 gate summary.

    The drop-rate denominator is the *pair* count (one row per
    ``(pair, task)`` invocation), not the call count, so it stays
    consistent with :func:`shop_probe.judge.swap.swap_drop_rate`. Both
    populations (experimental + control) contribute to the same rate —
    spec §7 M4 reports a single drop-rate noise floor.

    Args:
        outcomes: One :class:`PairJudgeOutcome` per ``(pair, task)``
            invocation.

    Returns:
        A :class:`M4GateMetrics` summary. Empty input → zeroed metrics
        with ``passes_gate=True`` (no pairs to flip on).
    """
    n = len(outcomes)
    if n == 0:
        return M4GateMetrics(n_pairs=0, n_inconsistent=0, swap_drop_rate=0.0)
    inconsistent = sum(1 for o in outcomes if not o.swap_consistent)
    return M4GateMetrics(
        n_pairs=n,
        n_inconsistent=inconsistent,
        swap_drop_rate=inconsistent / n,
    )


def judge_calls_from_outcomes(
    outcomes: Sequence[PairJudgeOutcome],
) -> tuple[JudgeCall, ...]:
    """Flatten :class:`PairJudgeOutcome` rows into a :class:`JudgeCall` tuple.

    Calls are emitted in input order, with each pair's two presentations
    (unswapped, swapped) emitted contiguously. The result is suitable
    for embedding in :attr:`shop_probe.report.ProbeReport.judge_calls`.
    """
    return tuple(call for outcome in outcomes for call in outcome.judge_calls)
