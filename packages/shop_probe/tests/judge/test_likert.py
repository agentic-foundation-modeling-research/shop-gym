"""Tests for ``shop_probe.judge.likert`` (T7.2 — spec §5.9 + §7 M7).

The T7.2 gate from ``docs/impl/web_probe_implementation.md`` reads:

    Check: per-dimension Likert distributions in the report.

These tests pin the Likert judge wiring so reviewers can trust the v1.1
quality-dimension pipeline end-to-end:

* :class:`LikertJudge` golden-prompt contract — rendered system + user
  prompts match the shipped template byte-for-byte after substitution
  (no ad-hoc rewriting), and the threaded :class:`JudgeModelPin` reaches
  the LLM client unchanged (spec §5.5 guardrails).
* Spec §5.9 response-shape parsing for every branch — well-formed
  ratings, abstain-via-no-evidence, malformed JSON, missing dimension,
  out-of-range score, code-fence-wrapped JSON.
* Spec §5.5 guardrails: discard parse errors and missing-evidence calls;
  preserve the raw response on every outcome.
* :func:`compute_likert_distributions` aggregation — one distribution
  per :data:`LikertDimension`, in declaration order, agreeing with
  :func:`shop_probe.report.aggregate_likert_distributions`.
* :class:`LikertOutcome.to_call` — discarded outcomes return ``None``;
  healthy outcomes round-trip into a :class:`LikertCall`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from shop_probe.judge.likert import (
    LikertJudge,
    compute_likert_distributions,
)
from shop_probe.judge.prompts import LikertPromptSet, load_likert_prompts
from shop_probe.judge.tasks import JudgeTask
from shop_probe.report import (
    LIKERT_DIMENSIONS,
    JudgeModelPin,
    LikertCall,
    aggregate_likert_distributions,
)

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #


def _judge_task() -> JudgeTask:
    return JudgeTask(
        id="filter_pdp_variant_cart_locale",
        description=(
            "Filter the bestsellers collection, open the third PDP, "
            "switch variants, add 2 to cart, then change locale."
        ),
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


def _trajectory_blob() -> str:
    return (
        "step_01: navigate to /collections/*\n"
        "step_02: click filter[name=type]\n"
        "step_03: click product card 3\n"
        "snapshot_05: PDP gallery thumbnails\n"
        "screenshot_07: cart drawer\n"
    )


@dataclass(slots=True)
class _RecordingClient:
    """Stub :class:`LLMClient` mirroring tests/judge/test_llm.py.

    Captures system + user + pin per call so golden-prompt tests can assert
    byte-equal templating; supports either a fixed ``response`` or a
    sequence of canned responses consumed in order.
    """

    response: str = ""
    responses: list[str] = field(default_factory=lambda: [])
    calls: list[tuple[str, str, JudgeModelPin]] = field(default_factory=lambda: [])

    def complete(
        self,
        *,
        system: str,
        user: str,
        model_pin: JudgeModelPin,
    ) -> str:
        self.calls.append((system, user, model_pin))
        if self.responses:
            return self.responses.pop(0)
        return self.response


def _build_judge(
    *,
    response: str = "",
    responses: list[str] | None = None,
) -> tuple[LikertJudge, _RecordingClient, LikertPromptSet]:
    prompts = load_likert_prompts("v1")
    client = _RecordingClient(
        response=response,
        responses=list(responses) if responses is not None else [],
    )
    judge = LikertJudge(prompts=prompts, model_pin=_judge_model_pin(), client=client)
    return judge, client, prompts


def _well_formed_response(
    *,
    visual_coherence: int = 4,
    copy_realism: int = 3,
    error_plausibility: int = 5,
    evidence: list[dict[str, str]] | None = None,
) -> str:
    if evidence is None:
        evidence = [{"ref": "screenshot_07", "claim": "cart drawer feels real"}]
    return json.dumps(
        {
            "ratings": {
                "visual_coherence": visual_coherence,
                "copy_realism": copy_realism,
                "error_plausibility": error_plausibility,
            },
            "evidence": evidence,
            "rationale": "polished theme; copy plausible; cart errors realistic",
        }
    )


# --------------------------------------------------------------------------- #
# Golden-prompt contract.
# --------------------------------------------------------------------------- #


def test_likert_judge_renders_system_prompt_verbatim() -> None:
    judge, _, prompts = _build_judge()
    system, _ = judge.render(task=_judge_task(), anonymized_trajectory=_trajectory_blob())
    assert system == prompts.system_template


def test_likert_judge_renders_user_prompt_with_substituted_placeholders() -> None:
    judge, _, prompts = _build_judge()
    task = _judge_task()
    traj = _trajectory_blob()
    _, user = judge.render(task=task, anonymized_trajectory=traj)
    expected = prompts.render_likert(task_description=task.description, anonymized_trajectory=traj)
    assert user == expected
    assert "$task_description" not in user
    assert "$anonymized_trajectory" not in user
    assert task.description in user
    assert traj in user


def test_likert_judge_invokes_client_once_per_trajectory() -> None:
    judge, client, _ = _build_judge(response=_well_formed_response())
    judge.judge_trajectory(task=_judge_task(), anonymized_trajectory=_trajectory_blob())
    assert len(client.calls) == 1


def test_likert_judge_threads_model_pin_into_every_call() -> None:
    """Spec §5.5 guardrails: report header pin and call-time pin cannot drift."""
    judge, client, _ = _build_judge(response=_well_formed_response())
    judge.judge_trajectory(task=_judge_task(), anonymized_trajectory=_trajectory_blob())
    pin = client.calls[0][2]
    assert pin == _judge_model_pin()
    assert pin.temperature == 0.0
    assert pin.model == "gpt-5"


# --------------------------------------------------------------------------- #
# Outcome shape — well-formed response, code-fenced JSON, abstain-via-no-evidence.
# --------------------------------------------------------------------------- #


def test_likert_outcome_carries_full_prompt_and_response() -> None:
    """Spec §5.5 guardrails: save full prompt + full response per call."""
    response = _well_formed_response()
    judge, _, prompts = _build_judge(response=response)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory=_trajectory_blob())
    assert outcome.scores == {
        "visual_coherence": 4,
        "copy_realism": 3,
        "error_plausibility": 5,
    }
    assert outcome.evidence_cited is True
    assert outcome.discard_reason is None
    assert outcome.system_prompt == prompts.system_template
    assert _trajectory_blob() in outcome.user_prompt
    assert outcome.raw_response == response
    assert outcome.prompt_hash == prompts.content_hash
    assert outcome.model_pin == _judge_model_pin()


def test_likert_judge_strips_code_fences_around_json() -> None:
    fenced = "```json\n" + _well_formed_response() + "\n```"
    judge, _, _ = _build_judge(response=fenced)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.scores is not None
    assert outcome.discard_reason is None


def test_likert_judge_discards_response_with_no_evidence() -> None:
    response = _well_formed_response(evidence=[])
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.evidence_cited is False
    assert outcome.discard_reason == "no_evidence"


def test_likert_judge_discards_response_with_blank_evidence_ref() -> None:
    response = _well_formed_response(evidence=[{"ref": "   ", "claim": "x"}])
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.evidence_cited is False
    assert outcome.discard_reason == "no_evidence"


# --------------------------------------------------------------------------- #
# Parse failures & missing dimensions.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "[]",  # array, not object
        json.dumps({"ratings": "wrong type"}),
        json.dumps({}),  # missing ratings entirely
    ],
)
def test_likert_judge_flags_parse_errors(raw: str) -> None:
    judge, _, _ = _build_judge(response=raw)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.scores is None
    assert outcome.discard_reason == "parse_error"
    assert outcome.raw_response == raw


def test_likert_judge_flags_missing_dimension() -> None:
    response = json.dumps(
        {
            "ratings": {
                # error_plausibility deliberately missing.
                "visual_coherence": 4,
                "copy_realism": 3,
            },
            "evidence": [{"ref": "screenshot_03", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.discard_reason == "missing_dimension"
    assert outcome.scores is not None
    assert "error_plausibility" not in outcome.scores
    assert outcome.scores["visual_coherence"] == 4  # noqa: PLR2004


@pytest.mark.parametrize("score", [0, 6, -1, 99])
def test_likert_judge_treats_out_of_range_score_as_missing_dimension(score: int) -> None:
    response = json.dumps(
        {
            "ratings": {
                "visual_coherence": score,
                "copy_realism": 3,
                "error_plausibility": 4,
            },
            "evidence": [{"ref": "screenshot_03", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.discard_reason == "missing_dimension"
    assert outcome.scores is not None
    assert "visual_coherence" not in outcome.scores


def test_likert_judge_rejects_boolean_masquerading_as_score() -> None:
    """Booleans subclass int; the spec §5.9 schema rejects them explicitly."""
    response = json.dumps(
        {
            "ratings": {
                "visual_coherence": True,
                "copy_realism": 3,
                "error_plausibility": 4,
            },
            "evidence": [{"ref": "screenshot_03", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.discard_reason == "missing_dimension"


# --------------------------------------------------------------------------- #
# LikertOutcome.to_call.
# --------------------------------------------------------------------------- #


def test_likert_outcome_to_call_returns_none_for_discarded_outcomes() -> None:
    judge, _, _ = _build_judge(response="not json")
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory="t")
    assert outcome.discard_reason == "parse_error"
    assert outcome.to_call(task_id="t01", target_label="sandbox/x") is None


def test_likert_outcome_to_call_round_trips_for_healthy_outcomes() -> None:
    response = _well_formed_response()
    judge, _, prompts = _build_judge(response=response)
    outcome = judge.judge_trajectory(task=_judge_task(), anonymized_trajectory=_trajectory_blob())
    call = outcome.to_call(task_id="t01", target_label="sandbox/hardware")
    assert isinstance(call, LikertCall)
    assert call.task_id == "t01"
    assert call.target_label == "sandbox/hardware"
    assert call.visual_coherence == 4  # noqa: PLR2004
    assert call.copy_realism == 3  # noqa: PLR2004
    assert call.error_plausibility == 5  # noqa: PLR2004
    assert call.prompt_hash == prompts.content_hash
    assert call.response_text == response
    assert call.evidence_cited is True


# --------------------------------------------------------------------------- #
# Distribution aggregation — T7.2 check ("per-dimension Likert distributions
# in the report").
# --------------------------------------------------------------------------- #


def _call(*, vc: int, cr: int, ep: int, target: str = "sandbox/x") -> LikertCall:
    return LikertCall(
        task_id="t01",
        target_label=target,
        visual_coherence=vc,
        copy_realism=cr,
        error_plausibility=ep,
        evidence_cited=True,
        prompt_hash="c" * 64,
        response_text="{}",
    )


def test_compute_likert_distributions_matches_report_aggregator() -> None:
    """The judge module's helper must agree with the canonical aggregator."""
    calls = (
        _call(vc=5, cr=4, ep=3),
        _call(vc=4, cr=4, ep=2),
        _call(vc=3, cr=5, ep=4),
    )
    assert compute_likert_distributions(calls) == aggregate_likert_distributions(calls)


def test_compute_likert_distributions_emits_one_per_dimension_in_order() -> None:
    distributions = compute_likert_distributions((_call(vc=5, cr=4, ep=3), _call(vc=4, cr=4, ep=2)))
    assert tuple(d.dimension for d in distributions) == LIKERT_DIMENSIONS


def test_compute_likert_distributions_handles_empty_calls() -> None:
    distributions = compute_likert_distributions(())
    assert tuple(d.dimension for d in distributions) == LIKERT_DIMENSIONS
    for dist in distributions:
        assert dist.n_calls == 0
        assert dist.counts == {}
        assert dist.mean is None


def test_compute_likert_distributions_records_histogram_and_mean() -> None:
    calls = (
        _call(vc=5, cr=4, ep=3),
        _call(vc=4, cr=4, ep=2),
        _call(vc=4, cr=5, ep=2),
    )
    distributions = {d.dimension: d for d in compute_likert_distributions(calls)}
    assert distributions["visual_coherence"].counts == {4: 2, 5: 1}
    assert distributions["visual_coherence"].mean == pytest.approx((5 + 4 + 4) / 3)
    assert distributions["copy_realism"].counts == {4: 2, 5: 1}
    assert distributions["copy_realism"].mean == pytest.approx((4 + 4 + 5) / 3)
    assert distributions["error_plausibility"].counts == {2: 2, 3: 1}
    assert distributions["error_plausibility"].mean == pytest.approx((3 + 2 + 2) / 3)
