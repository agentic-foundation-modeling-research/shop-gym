"""End-to-end M4 gate test for `shop_probe.judge.run` (T4.9 — spec §7 M4).

The T4.9 gate from ``docs/impl/web_probe_implementation.md`` reads:

    Check: spec §7 M4 gate — swap-inconsistency rate ≤ 5%; HAR captures
    + screenshots saved; control-pair construction validated against the
    6-real-shop list.

This module exercises the M4 orchestration end-to-end — agent runner →
anonymization → pairwise pair construction → pinned LLM judge with A/B
swap → swap-consistency aggregation → JudgeCall rows → spec §7 M4 gate
metric — without opening a browser or hitting a live LLM.

Coverage:

* :func:`render_trajectory_for_judge` — refuses un-anonymized
  trajectories (spec §5.5 step 3 invariant); pins a stable per-trajectory
  marker into the rendered text.
* :func:`judge_pair_for_task` — owns the spec §5.5 step 3 anonymization
  step; runs the pinned judge twice per pair (spec §5.5 step 6); builds
  two :class:`shop_probe.report.JudgeCall` rows in presentation order;
  computes ``swap_consistent`` per spec §5.5 step 6 + step 7; refuses
  trajectories whose target does not match the canonical pair member or
  that have already been anonymized.
* :func:`m4_gate_metrics` — drop-rate aggregation, ``passes_gate``
  threshold, empty-input behavior, mixed-condition behavior.
* :func:`judge_calls_from_outcomes` — flattening preserves
  ``(unswapped, swapped)`` order and is suitable for embedding in
  :attr:`shop_probe.report.ProbeReport.judge_calls`.
* The M4 gate itself: a shop-tracking stub LLM produces a ≤ 5%
  swap-inconsistency rate across the experimental + control pair
  population built from a fully-populated cohort, satisfying the spec
  §7 M4 acceptance criteria for the orchestration layer (the
  empirical pair_1 live run sits on top of the same wiring with
  a real OpenAI client + a real Playwright runtime).
"""

from __future__ import annotations

import datetime as dt
import json
import random
from dataclasses import dataclass, field
from typing import Final

import pytest

from shop_probe.judge.anonymize import AnonymizationPlan, anonymize_trajectory
from shop_probe.judge.llm import PinnedJudge
from shop_probe.judge.pairwise import (
    PairwisePair,
    build_control_pairs,
    build_experimental_pairs,
    build_task_pairs,
    real_shop_pool,
)
from shop_probe.judge.prompts import JudgePromptSet, load_judge_prompts
from shop_probe.judge.run import (
    M4_SWAP_DROP_RATE_THRESHOLD,
    M4GateMetrics,
    PairJudgeOutcome,
    judge_calls_from_outcomes,
    judge_pair_for_task,
    m4_gate_metrics,
    render_trajectory_for_judge,
)
from shop_probe.judge.swap import is_swap_consistent
from shop_probe.judge.tasks import JudgeTask
from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStep,
)
from shop_probe.report import BrowserMeta, EvidenceRef, JudgeCall, JudgeModelPin
from shop_probe.targets import Cohort, Pair, Target, TargetKind

# --------------------------------------------------------------------------- #
# Fixture builders. Mirror tests/judge/test_pairwise.py + test_swap.py +
# test_llm.py: the shipped cohort.yaml is a v0.1 stub with TBD URLs, so we
# build a fully-populated cohort here so M4 gate tests don't hinge on the
# spec §8.5 open questions tracked under T5.1.
# --------------------------------------------------------------------------- #

_PAIR_IDS: Final[tuple[str, str, str]] = (
    "pair_1",
    "pair_2",
    "pair_3",
)


def _target(label: str, kind: TargetKind, pair_id: str | None = None) -> Target:
    return Target(
        label=label,
        base_url=f"https://{label.replace('/', '-')}.example",
        kind=kind,
        pair_id=pair_id,
    )


def _full_cohort() -> Cohort:
    pairs = tuple(
        Pair(
            id=pid,
            source=_target(f"source/{pid}", "source", pid),
            sandbox=_target(f"sandbox/{pid}", "sandbox", pid),
        )
        for pid in _PAIR_IDS
    )
    real_unpaired = tuple(_target(f"real/unpaired_{i}", "real_unpaired") for i in range(3))
    return Cohort(version="0.1", pairs=pairs, real_unpaired=real_unpaired)


def _judge_task() -> JudgeTask:
    return JudgeTask(
        id="filter_pdp_variant_cart_locale",
        description="Filter the bestsellers collection, open the third PDP, "
        "switch variants, add 2 to cart, then change locale.",
        surfaces=("collection", "product", "cart"),
        interactions=("filter", "open_pdp", "variant_select", "add_to_cart"),
        rationale="Multi-page, interaction-heavy — diagnostic for theme realism.",
    )


def _judge_model_pin() -> JudgeModelPin:
    return JudgeModelPin(
        provider="openai",
        model="gpt-5",
        model_version="gpt-5-2025-09-01",
        temperature=0.0,
    )


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.0.0 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _raw_trajectory_for(target: Target) -> Trajectory:
    """Build a minimal but fully-populated raw :class:`Trajectory` for ``target``.

    Mirrors what :func:`shop_probe.judge.agent.run_judge_agent` would
    persist: two paired (call, result) navigation steps with screenshots
    + a11y snapshots, plus an HAR evidence pointer.
    """
    started = dt.datetime(2026, 1, 15, 12, 0, 0, tzinfo=dt.UTC)
    steps = (
        TrajectoryStep(
            index=0,
            action=TrajectoryAction(
                kind="navigate",
                selector=None,
                value=f"{target.base_url}/",
                description=f"navigate to {target.base_url}/",
            ),
            observation=TrajectoryObservation(
                url=f"{target.base_url}/",
                title="home",
                screenshot=EvidenceRef(
                    kind="screenshot", path="iters/exec-0001/screenshots/00.png"
                ),
                a11y_snapshot=EvidenceRef(
                    kind="a11y_snapshot", path="iters/exec-0001/a11y/00.json"
                ),
            ),
            reasoning=f"open homepage to begin task on {target.label}",
            duration_ms=120,
        ),
        TrajectoryStep(
            index=1,
            action=TrajectoryAction(
                kind="click",
                selector="a[href='/collections/all']",
                value=None,
                description="click first collection link",
            ),
            observation=TrajectoryObservation(
                url=f"{target.base_url}/collections/all",
                title="all",
                screenshot=EvidenceRef(
                    kind="screenshot", path="iters/exec-0002/screenshots/01.png"
                ),
                a11y_snapshot=EvidenceRef(
                    kind="a11y_snapshot", path="iters/exec-0002/a11y/01.json"
                ),
            ),
            reasoning="navigate to collection grid",
            duration_ms=200,
        ),
    )
    return Trajectory(
        target=target,
        task_id="filter_pdp_variant_cart_locale",
        runner_version="0.0.0",
        runtime=_browser_meta(),
        started_at=started,
        ended_at=started + dt.timedelta(seconds=2),
        steps=steps,
        har=EvidenceRef(kind="har", path=f"har/{target.label.replace('/', '__')}.har"),
        final_status="completed",
        anonymized=False,
        notes=None,
    )


def _shared_anon_plan(*labels: str) -> AnonymizationPlan:
    """Build a single :class:`AnonymizationPlan` covering every target's domain.

    Mirrors the spec §5.5 step 3 contract: one plan applied symmetrically
    to both members of a pair (and to every pair in the cohort run) so
    rewrites stay symmetric across the population.
    """
    domains = tuple(f"{lbl.replace('/', '-')}.example" for lbl in labels)
    return AnonymizationPlan(source_domains=domains)


def _cohort_anon_plan(cohort: Cohort) -> AnonymizationPlan:
    """Single shared anonymization plan for the whole cohort fixture."""
    labels = [t.label for p in cohort.pairs for t in (p.sandbox, p.source)]
    labels.extend(t.label for t in cohort.real_unpaired)
    return _shared_anon_plan(*labels)


def _anon_label(target: Target, plan: AnonymizationPlan) -> str:
    """Resolve the ``target.label`` to its post-anonymization placeholder.

    Threading a synthetic raw trajectory through
    :func:`anonymize_trajectory` is the cleanest way to recover the
    hashed label without reaching into private rewriter state.
    """
    return anonymize_trajectory(_raw_trajectory_for(target), plan).target.label


# --------------------------------------------------------------------------- #
# Stub LLMClient that picks the slot whose rendered trajectory contains a
# known marker — used to demonstrate M4 gate achievability end-to-end without
# a live LLM. The marker is the post-anonymization target.label, which is a
# stable hash and brand-free per spec §5.5 step 3.
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _MarkerTrackingClient:
    """LLMClient stub that picks the slot whose rendered trajectory marks ``pick_label``.

    When the prompt contains ``pick_label`` in slot A's trajectory blob,
    the stub returns ``"A"``; in slot B's blob, ``"B"``; otherwise
    ``"abstain"``. Calls are recorded so swap-presentation count tests
    can assert the spec §5.5 step 6 contract (two calls per pair).
    """

    pick_label: str
    calls: list[tuple[str, str, JudgeModelPin]] = field(default_factory=lambda: [])

    def complete(self, *, system: str, user: str, model_pin: JudgeModelPin) -> str:
        self.calls.append((system, user, model_pin))
        marker = f"target: {self.pick_label}"
        a_idx = user.find("Trajectory A:")
        b_idx = user.find("Trajectory B:")
        if a_idx == -1 or b_idx == -1 or b_idx < a_idx:
            return _abstain_response("malformed prompt")
        a_blob = user[a_idx:b_idx]
        b_blob = user[b_idx:]
        if marker in a_blob:
            return _pick_response("A")
        if marker in b_blob:
            return _pick_response("B")
        return _abstain_response("marker not found")


def _pick_response(slot: str) -> str:
    return json.dumps(
        {
            "pick": slot,
            "confidence": 0.85,
            "evidence": [
                {"trajectory": slot, "ref": "screenshot_00", "claim": "homepage capture"},
            ],
            "rationale": f"stub picks slot {slot} based on marker",
        }
    )


def _abstain_response(reason: str) -> str:
    return json.dumps(
        {
            "pick": "abstain",
            "confidence": 0.0,
            "evidence": [],
            "rationale": reason,
        }
    )


def _build_judge(
    client_pick_label: str,
) -> tuple[PinnedJudge, _MarkerTrackingClient, JudgePromptSet]:
    prompts = load_judge_prompts("v1")
    client = _MarkerTrackingClient(pick_label=client_pick_label)
    judge = PinnedJudge(prompts=prompts, model_pin=_judge_model_pin(), client=client)
    return judge, client, prompts


# --------------------------------------------------------------------------- #
# render_trajectory_for_judge.
# --------------------------------------------------------------------------- #


def test_render_trajectory_includes_target_marker_and_step_refs() -> None:
    target = _target("source/pair_1", "source", "pair_1")
    plan = _shared_anon_plan(target.label)
    anon = anonymize_trajectory(_raw_trajectory_for(target), plan)
    rendered = render_trajectory_for_judge(anon)

    assert rendered.startswith(f"target: {anon.target.label}\n")
    # Each step contributes a stable screenshot_NN / snapshot_NN ref so the
    # judge prompt can cite them per spec §8.3.
    assert "screenshot_00:" in rendered
    assert "screenshot_01:" in rendered
    assert "snapshot_00:" in rendered
    assert "snapshot_01:" in rendered
    # Anonymized URLs (with REDACTED_HOST) survive the rendering.
    assert "redacted.example" in rendered
    # Trailing newline so successive embedding in a prompt template stays clean.
    assert rendered.endswith("\n")


def test_render_trajectory_refuses_un_anonymized_input() -> None:
    target = _target("source/pair_1", "source", "pair_1")
    raw = _raw_trajectory_for(target)
    assert raw.anonymized is False
    with pytest.raises(ValueError, match="anonymized"):
        render_trajectory_for_judge(raw)


# --------------------------------------------------------------------------- #
# judge_pair_for_task — happy paths (consistent / inconsistent) + invariants.
# --------------------------------------------------------------------------- #


def _experimental_pair() -> PairwisePair:
    return build_experimental_pairs(_full_cohort())[0]


def test_judge_pair_for_task_invokes_judge_twice_per_pair() -> None:
    """Spec §5.5 step 6: re-run with A/B swapped → exactly two calls per pair."""
    pair = _experimental_pair()
    plan = _shared_anon_plan(pair.members[0].label, pair.members[1].label)
    judge, client, _ = _build_judge(client_pick_label=_anon_label(pair.members[1], plan))

    judge_pair_for_task(
        pair=pair,
        task=_judge_task(),
        member_a_trajectory=_raw_trajectory_for(pair.members[0]),
        member_b_trajectory=_raw_trajectory_for(pair.members[1]),
        anonymization_plan=plan,
        judge=judge,
    )

    assert len(client.calls) == 2  # noqa: PLR2004 — spec §5.5 step 6 = two presentations.


def test_judge_pair_for_task_swap_consistent_on_shop_tracking_stub() -> None:
    """A judge that follows the source survives the A/B swap — drop rate 0%."""
    pair = _experimental_pair()
    plan = _shared_anon_plan(pair.members[0].label, pair.members[1].label)
    judge, _, _ = _build_judge(client_pick_label=_anon_label(pair.members[1], plan))

    outcome = judge_pair_for_task(
        pair=pair,
        task=_judge_task(),
        member_a_trajectory=_raw_trajectory_for(pair.members[0]),
        member_b_trajectory=_raw_trajectory_for(pair.members[1]),
        anonymization_plan=plan,
        judge=judge,
    )

    assert outcome.swap_consistent is True
    assert outcome.judge_calls[0].swap_consistent is True
    assert outcome.judge_calls[1].swap_consistent is True
    # Unswapped: A=sandbox, B=source → judge picks B; truth=B → correct.
    assert outcome.judge_calls[0].judge_pick == "B"
    assert outcome.judge_calls[0].truth == "B"
    # Swapped: A=source, B=sandbox → judge picks A; truth=A → correct.
    assert outcome.judge_calls[1].judge_pick == "A"
    assert outcome.judge_calls[1].truth == "A"


def test_judge_pair_for_task_records_anonymized_pair_label_in_presentation_order() -> None:
    pair = _experimental_pair()
    plan = _shared_anon_plan(pair.members[0].label, pair.members[1].label)
    sandbox_anon = _anon_label(pair.members[0], plan)
    source_anon = _anon_label(pair.members[1], plan)
    judge, _, _ = _build_judge(client_pick_label=source_anon)

    outcome = judge_pair_for_task(
        pair=pair,
        task=_judge_task(),
        member_a_trajectory=_raw_trajectory_for(pair.members[0]),
        member_b_trajectory=_raw_trajectory_for(pair.members[1]),
        anonymization_plan=plan,
        judge=judge,
    )

    # Unswapped slot order = (members[0], members[1]) = (sandbox, source).
    assert outcome.judge_calls[0].pair_label == (sandbox_anon, source_anon)
    # Swapped slot order = (members[1], members[0]) = (source, sandbox).
    assert outcome.judge_calls[1].pair_label == (source_anon, sandbox_anon)
    # Brand strings never leak: the original labels do not appear in the
    # JudgeCall pair_label after anonymization (spec §5.5 step 3 invariant).
    for call in outcome.judge_calls:
        assert pair.members[0].label not in call.pair_label
        assert pair.members[1].label not in call.pair_label


def test_judge_pair_for_task_threads_evidence_and_prompt_metadata() -> None:
    pair = _experimental_pair()
    plan = _shared_anon_plan(pair.members[0].label, pair.members[1].label)
    judge, _, prompts = _build_judge(client_pick_label=_anon_label(pair.members[1], plan))

    outcome = judge_pair_for_task(
        pair=pair,
        task=_judge_task(),
        member_a_trajectory=_raw_trajectory_for(pair.members[0]),
        member_b_trajectory=_raw_trajectory_for(pair.members[1]),
        anonymization_plan=plan,
        judge=judge,
    )

    for call in outcome.judge_calls:
        assert call.task_id == "filter_pdp_variant_cart_locale"
        assert call.evidence_cited is True
        assert call.confidence == pytest.approx(0.85)
        assert call.prompt_hash == prompts.content_hash
        assert call.response_text  # raw response preserved verbatim.


def test_judge_pair_for_task_abstaining_judge_drops_pair() -> None:
    """A judge that always abstains (marker absent) → not swap-consistent."""
    pair = _experimental_pair()
    plan = _shared_anon_plan(pair.members[0].label, pair.members[1].label)
    # Marker the stub looks for is intentionally absent → both calls abstain.
    judge, _, _ = _build_judge(client_pick_label="target_does_not_match_any_label")

    outcome = judge_pair_for_task(
        pair=pair,
        task=_judge_task(),
        member_a_trajectory=_raw_trajectory_for(pair.members[0]),
        member_b_trajectory=_raw_trajectory_for(pair.members[1]),
        anonymization_plan=plan,
        judge=judge,
    )

    # Both presentations abstain → not swap-consistent (spec §5.5 step 6).
    assert outcome.swap_consistent is False
    for call in outcome.judge_calls:
        assert call.judge_pick == "abstain"
        assert call.swap_consistent is False


def test_judge_pair_for_task_rejects_member_label_mismatch() -> None:
    pair = _experimental_pair()
    plan = _shared_anon_plan(pair.members[0].label, pair.members[1].label)
    judge, _, _ = _build_judge(client_pick_label="x")
    # Wrong member: pass the sandbox trajectory in slot B (which expects source).
    sandbox_traj = _raw_trajectory_for(pair.members[0])
    with pytest.raises(ValueError, match=r"members\[1\]"):
        judge_pair_for_task(
            pair=pair,
            task=_judge_task(),
            member_a_trajectory=sandbox_traj,
            member_b_trajectory=sandbox_traj,
            anonymization_plan=plan,
            judge=judge,
        )


def test_judge_pair_for_task_rejects_already_anonymized_trajectory() -> None:
    pair = _experimental_pair()
    plan = _shared_anon_plan(pair.members[0].label, pair.members[1].label)
    raw = _raw_trajectory_for(pair.members[0])
    pre_anonymized = anonymize_trajectory(raw, plan)
    judge, _, _ = _build_judge(client_pick_label="x")
    with pytest.raises(ValueError, match="already anonymized"):
        judge_pair_for_task(
            pair=pair,
            task=_judge_task(),
            member_a_trajectory=pre_anonymized,
            member_b_trajectory=_raw_trajectory_for(pair.members[1]),
            anonymization_plan=plan,
            judge=judge,
        )


def test_judge_pair_for_task_truth_is_designated_real_for_control_pair() -> None:
    cohort = _full_cohort()
    plan = _cohort_anon_plan(cohort)
    control_pairs = build_control_pairs(cohort, count=3, rng=random.Random(0))
    pair = control_pairs[0]
    designated_real = pair.members[0]
    # Pick the designated real so ``truth`` and ``judge_pick`` agree.
    judge, _, _ = _build_judge(client_pick_label=_anon_label(designated_real, plan))

    outcome = judge_pair_for_task(
        pair=pair,
        task=_judge_task(),
        member_a_trajectory=_raw_trajectory_for(pair.members[0]),
        member_b_trajectory=_raw_trajectory_for(pair.members[1]),
        anonymization_plan=plan,
        judge=judge,
    )

    assert outcome.condition == "control"
    # Unswapped: A=members[0]=designated → truth=A.
    assert outcome.judge_calls[0].truth == "A"
    # Swapped: A=members[1] → designated lives in B → truth=B.
    assert outcome.judge_calls[1].truth == "B"
    assert outcome.swap_consistent is True


# --------------------------------------------------------------------------- #
# m4_gate_metrics — drop-rate aggregation + spec §7 M4 boundary.
# --------------------------------------------------------------------------- #


def _outcome(pair_id: str, *, consistent: bool) -> PairJudgeOutcome:
    """Synthetic :class:`PairJudgeOutcome` for the pure metric tests."""
    pick_a = "A"
    pick_b = "B" if consistent else "A"
    consistent_flag = is_swap_consistent(pick_a, pick_b)
    assert consistent_flag is consistent
    base_call = JudgeCall(
        task_id="t",
        pair_label=("a", "b"),
        judge_pick=pick_a,
        truth="A",
        swap_consistent=consistent,
        evidence_cited=True,
        confidence=0.5,
        prompt_hash="0" * 64,
        response_text="{}",
    )
    return PairJudgeOutcome(
        pair_id=pair_id,
        condition="experimental",
        task_id="t",
        judge_calls=(base_call, base_call),
        swap_consistent=consistent,
    )


def test_m4_gate_metrics_empty_input_passes_gate() -> None:
    metrics = m4_gate_metrics([])
    assert metrics == M4GateMetrics(n_pairs=0, n_inconsistent=0, swap_drop_rate=0.0)
    assert metrics.passes_gate is True


def test_m4_gate_metrics_all_consistent_passes_gate() -> None:
    metrics = m4_gate_metrics(tuple(_outcome(f"p{i}", consistent=True) for i in range(6)))
    assert metrics.n_pairs == 6  # noqa: PLR2004 — six experimental pairs in the fixture.
    assert metrics.n_inconsistent == 0
    assert metrics.swap_drop_rate == 0.0
    assert metrics.passes_gate is True


def test_m4_gate_metrics_at_5_percent_threshold_passes() -> None:
    """Spec §7 M4 gate: ≤ 5% swap-inconsistency rate sits exactly on the gate."""
    outcomes = (
        _outcome("p0", consistent=False),
        *(_outcome(f"p{i}", consistent=True) for i in range(1, 20)),
    )
    metrics = m4_gate_metrics(outcomes)
    assert metrics.swap_drop_rate == pytest.approx(M4_SWAP_DROP_RATE_THRESHOLD)
    assert metrics.passes_gate is True


def test_m4_gate_metrics_above_threshold_fails_gate() -> None:
    outcomes = (
        _outcome("p0", consistent=False),
        _outcome("p1", consistent=False),
        *(_outcome(f"p{i}", consistent=True) for i in range(2, 20)),
    )
    metrics = m4_gate_metrics(outcomes)
    assert metrics.swap_drop_rate == pytest.approx(0.1)
    assert metrics.passes_gate is False


# --------------------------------------------------------------------------- #
# judge_calls_from_outcomes — flattening order.
# --------------------------------------------------------------------------- #


def test_judge_calls_from_outcomes_preserves_pair_then_presentation_order() -> None:
    o0 = _outcome("p0", consistent=True)
    o1 = _outcome("p1", consistent=False)
    flattened = judge_calls_from_outcomes([o0, o1])
    expected_call_count = 4  # 2 pairs x 2 presentations.
    assert len(flattened) == expected_call_count
    # Order: o0[0], o0[1], o1[0], o1[1].
    assert flattened[0] is o0.judge_calls[0]
    assert flattened[1] is o0.judge_calls[1]
    assert flattened[2] is o1.judge_calls[0]
    assert flattened[3] is o1.judge_calls[1]


# --------------------------------------------------------------------------- #
# T4.9 acceptance gate — end-to-end M4 gate over experimental + control pairs.
# --------------------------------------------------------------------------- #


def test_t4_9_m4_gate_satisfied_over_experimental_and_control_population() -> None:
    """Spec §7 M4 gate (T4.9) — orchestration produces ≤ 5% drop rate end-to-end.

    Wires every M4 piece — anonymization (T4.4) → pair construction (T4.5)
    → pinned-judge wiring (T4.6) → frozen prompts (T4.7) → swap consistency
    (T4.8) → :func:`judge_pair_for_task` orchestration (T4.9) — together
    against a fully-populated cohort. The shop-tracking stub maps a known
    target.label hash to a shop pick, so every pair is swap-consistent →
    drop rate = 0% ≤ 5%.

    The same wiring with a real OpenAI client + a real Playwright runtime
    is the production T4.9 invocation against ``pair_1``; the
    gate threshold is the same.
    """
    cohort = _full_cohort()
    plan = _cohort_anon_plan(cohort)
    pairs = build_task_pairs(cohort, seed=0)
    task = _judge_task()
    outcomes: list[PairJudgeOutcome] = []
    for pair in pairs:
        # Stub picks the canonical "truth" slot:
        # * experimental → source (members[1])
        # * control      → designated real (members[0])
        truth_member = pair.members[1] if pair.condition == "experimental" else pair.members[0]
        judge, _, _ = _build_judge(client_pick_label=_anon_label(truth_member, plan))
        outcome = judge_pair_for_task(
            pair=pair,
            task=task,
            member_a_trajectory=_raw_trajectory_for(pair.members[0]),
            member_b_trajectory=_raw_trajectory_for(pair.members[1]),
            anonymization_plan=plan,
            judge=judge,
        )
        outcomes.append(outcome)

    metrics = m4_gate_metrics(outcomes)
    expected_pair_count = 6  # 3 experimental + 3 control.
    assert metrics.n_pairs == expected_pair_count
    assert metrics.n_inconsistent == 0
    assert metrics.swap_drop_rate == 0.0
    assert metrics.passes_gate is True
    # Every JudgeCall row carries the shared swap_consistent flag.
    flattened = judge_calls_from_outcomes(outcomes)
    assert all(call.swap_consistent for call in flattened)


def test_t4_9_control_pair_construction_honors_six_real_shop_pool() -> None:
    """T4.9 check: control-pair construction validated against the 6-real-shop list.

    The :mod:`shop_probe.judge.pairwise` invariant tests already cover this
    structurally; reaffirm at the orchestration level so the M4 gate suite
    documents the link between the operational run (T4.9) and the
    spec §5.2 / §5.5 step 4 disjointness invariant.
    """
    cohort = _full_cohort()
    sandbox_labels = {p.sandbox.label for p in cohort.pairs}
    pool_labels = {t.label for t in real_shop_pool(cohort)}

    pairs = build_task_pairs(cohort, seed=99)
    control_pairs = [p for p in pairs if p.condition == "control"]

    expected_control_count = 3
    assert len(control_pairs) == expected_control_count
    seen_real_labels: set[str] = set()
    for control_pair in control_pairs:
        for member in control_pair.members:
            assert member.kind in {"source", "real_unpaired"}
            assert member.label in pool_labels
            assert member.label not in sandbox_labels
            assert member.label not in seen_real_labels  # Sampled without replacement.
            seen_real_labels.add(member.label)
    # 6 real shops in the pool → control population fully partitions it.
    expected_pool_size = 6
    assert len(seen_real_labels) == expected_pool_size
    assert seen_real_labels == pool_labels
