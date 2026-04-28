"""Tests for ``shop_probe.judge.llm`` (T4.6 — spec §5.5 step 5 + guardrails).

The T4.6 gate from ``docs/impl/web_probe_implementation.md`` reads:

    Check: golden-prompt unit test using a stub LLM; pin assertions in
    report header.

This module covers:

* The :class:`PinnedJudge` golden-prompt contract: rendered system + user
  prompts match the shipped template byte-for-byte after substitution
  (no ad-hoc rewriting), and the threaded :class:`JudgeModelPin` reaches
  the LLM client unchanged (spec §5.5 guardrails: pin model + version +
  temperature in the report metadata; do not let runtime drift from the
  pinned value).
* Spec §8.3 response-shape parsing for every branch — well-formed pick,
  abstain, malformed JSON, missing ``pick``, out-of-range ``confidence``,
  boolean masquerading as ``confidence``, code-fence-wrapped JSON.
* Spec §5.5 guardrails: discard non-abstain picks without an evidence
  citation; preserve the raw response on every outcome.
* Spec §5.5 step 5 prompt-identity invariant: the rendered prompts do
  not encode the swap state; one identical prompt template is used for
  experimental and control pairs.
* :meth:`PinnedJudge.as_judge_callable` adapts to the
  :class:`shop_probe.judge.swap.JudgeCallable` Protocol so the existing
  swap-consistency aggregator (T4.8) can drive it; discarded calls
  surface as ``"abstain"``.

Pinning to the report header (the second half of the T4.6 check) lives
in :mod:`tests.test_report` — see ``test_probe_report_pins_judge_model_in_header``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Final

import pytest

from shop_probe.judge.llm import (
    LLMClient,
    PinnedJudge,
    PinnedJudgeOutcome,
)
from shop_probe.judge.pairwise import build_experimental_pairs
from shop_probe.judge.prompts import JudgePromptSet, load_judge_prompts
from shop_probe.judge.swap import (
    Presentation,
    evaluate_swap_consistency,
)
from shop_probe.judge.tasks import JudgeTask
from shop_probe.report import JudgeModelPin
from shop_probe.targets import Cohort, Pair, Target, TargetKind

# --------------------------------------------------------------------------- #
# Fixture builders. Mirror tests/judge/test_pairwise.py + test_swap.py: the
# shipped cohort.yaml is a v0.1 stub, so we build a fully-populated cohort
# locally.
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


def _trajectory_blob(tag: str) -> str:
    return (
        f"step_01: navigate to /collections/* on traj_{tag}\n"
        f"step_02: click filter[name=type] on traj_{tag}\n"
        f"step_03: click product card 3 on traj_{tag}\n"
        f"snapshot_05: PDP gallery thumbnails on traj_{tag}\n"
        f"screenshot_07: cart drawer on traj_{tag}\n"
    )


@dataclass(slots=True)
class _RecordingClient:
    """Stub :class:`LLMClient` that records calls and returns canned responses.

    Captures the system + user prompt + pin per call so golden-prompt tests
    can assert byte-equal templating, and supports either a fixed
    ``response`` or a sequence of responses consumed in order.
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


def _experimental_presentation() -> Presentation:
    pair = build_experimental_pairs(_full_cohort())[0]
    return Presentation(pair=pair, swap=False)


def _swapped_presentation() -> Presentation:
    pair = build_experimental_pairs(_full_cohort())[0]
    return Presentation(pair=pair, swap=True)


def _build_judge(
    *,
    response: str = "",
    responses: list[str] | None = None,
) -> tuple[PinnedJudge, _RecordingClient, JudgePromptSet]:
    prompts = load_judge_prompts("v1")
    client = _RecordingClient(
        response=response,
        responses=list(responses) if responses is not None else [],
    )
    judge = PinnedJudge(prompts=prompts, model_pin=_judge_model_pin(), client=client)
    return judge, client, prompts


# --------------------------------------------------------------------------- #
# Golden-prompt contract — rendered system + user prompts match the shipped
# template byte-for-byte (T4.6 check).
# --------------------------------------------------------------------------- #


def test_pinned_judge_renders_system_prompt_verbatim() -> None:
    judge, _, prompts = _build_judge()
    system, _ = judge.render(
        presentation=_experimental_presentation(),
        task=_judge_task(),
        trajectory_a=_trajectory_blob("alpha"),
        trajectory_b=_trajectory_blob("beta"),
    )
    assert system == prompts.system_template


def test_pinned_judge_renders_user_prompt_with_substituted_placeholders() -> None:
    judge, _, prompts = _build_judge()
    task = _judge_task()
    traj_a = _trajectory_blob("alpha")
    traj_b = _trajectory_blob("beta")
    _, user = judge.render(
        presentation=_experimental_presentation(),
        task=task,
        trajectory_a=traj_a,
        trajectory_b=traj_b,
    )
    expected = prompts.render_pairwise(
        task_description=task.description,
        anonymized_trajectory_a=traj_a,
        anonymized_trajectory_b=traj_b,
    )
    assert user == expected
    # Placeholders are gone post-render; literal task + trajectory text is in.
    assert "$task_description" not in user
    assert "$anonymized_trajectory_a" not in user
    assert task.description in user
    assert traj_a in user
    assert traj_b in user


def test_pinned_judge_prompt_does_not_encode_swap_state() -> None:
    """Spec §5.5 step 5 + step 6: swap state must not enter the prompt body."""
    judge, _, _ = _build_judge()
    task = _judge_task()
    traj_a = _trajectory_blob("alpha")
    traj_b = _trajectory_blob("beta")
    unswapped = judge.render(
        presentation=_experimental_presentation(),
        task=task,
        trajectory_a=traj_a,
        trajectory_b=traj_b,
    )
    swapped = judge.render(
        presentation=_swapped_presentation(),
        task=task,
        trajectory_a=traj_a,
        trajectory_b=traj_b,
    )
    assert unswapped == swapped


def test_pinned_judge_invokes_client_once_per_presentation() -> None:
    response = json.dumps(
        {
            "pick": "A",
            "confidence": 0.7,
            "evidence": [
                {"trajectory": "A", "ref": "screenshot_07", "claim": "cart drawer"},
            ],
            "rationale": "drawer interaction looks production-grade",
        }
    )
    judge, client, _ = _build_judge(response=response)
    judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a=_trajectory_blob("alpha"),
        trajectory_b=_trajectory_blob("beta"),
    )
    assert len(client.calls) == 1


def test_pinned_judge_threads_model_pin_into_every_call() -> None:
    """Spec §5.5 guardrails: report header value and call-time value cannot drift."""
    response = json.dumps(
        {
            "pick": "B",
            "confidence": 0.55,
            "evidence": [{"trajectory": "B", "ref": "snapshot_12:L34", "claim": "PDP"}],
            "rationale": "x",
        }
    )
    judge, client, _ = _build_judge(response=response)
    judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a=_trajectory_blob("alpha"),
        trajectory_b=_trajectory_blob("beta"),
    )
    pin = client.calls[0][2]
    assert pin == _judge_model_pin()
    assert pin.temperature == 0.0
    assert pin.model == "gpt-5"


# --------------------------------------------------------------------------- #
# Outcome shape — well-formed pick, abstain, code-fenced JSON.
# --------------------------------------------------------------------------- #


def test_pinned_judge_outcome_carries_full_prompt_and_response() -> None:
    """Spec §5.5 guardrails: save full prompt + full response per call."""
    response = json.dumps(
        {
            "pick": "A",
            "confidence": 0.8,
            "evidence": [{"trajectory": "A", "ref": "screenshot_07", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, _, prompts = _build_judge(response=response)
    outcome = judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a=_trajectory_blob("alpha"),
        trajectory_b=_trajectory_blob("beta"),
    )
    assert outcome.pick == "A"
    assert outcome.confidence == 0.8  # noqa: PLR2004 — echoed verbatim from the canned response.
    assert outcome.evidence_cited is True
    assert outcome.discard_reason is None
    assert outcome.system_prompt == prompts.system_template
    assert _trajectory_blob("alpha") in outcome.user_prompt
    assert outcome.raw_response == response
    assert outcome.prompt_hash == prompts.content_hash
    assert outcome.model_pin == _judge_model_pin()


def test_pinned_judge_accepts_abstain_without_evidence() -> None:
    response = json.dumps(
        {
            "pick": "abstain",
            "confidence": 0.0,
            "evidence": [],
            "rationale": "insufficient signal",
        }
    )
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a=_trajectory_blob("alpha"),
        trajectory_b=_trajectory_blob("beta"),
    )
    assert outcome.pick == "abstain"
    assert outcome.evidence_cited is False
    # Abstain is a recorded outcome, not a discard.
    assert outcome.discard_reason is None


def test_pinned_judge_strips_code_fences_around_json() -> None:
    fenced_response = (
        "```json\n"
        + json.dumps(
            {
                "pick": "B",
                "confidence": 0.6,
                "evidence": [{"trajectory": "B", "ref": "snapshot_03", "claim": "x"}],
                "rationale": "y",
            }
        )
        + "\n```"
    )
    judge, _, _ = _build_judge(response=fenced_response)
    outcome = judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a="t_a",
        trajectory_b="t_b",
    )
    assert outcome.pick == "B"
    assert outcome.discard_reason is None


# --------------------------------------------------------------------------- #
# Spec §5.5 guardrails — discard calls without evidence; surface parse errors.
# --------------------------------------------------------------------------- #


def test_pinned_judge_discards_pick_without_evidence() -> None:
    """Spec §5.5 guardrails: calls without evidence are discarded."""
    response = json.dumps({"pick": "A", "confidence": 0.9, "evidence": [], "rationale": "vibes"})
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a="a",
        trajectory_b="b",
    )
    assert outcome.pick == "A"
    assert outcome.evidence_cited is False
    assert outcome.discard_reason == "no_evidence"


def test_pinned_judge_discards_pick_with_blank_evidence_ref() -> None:
    response = json.dumps(
        {
            "pick": "B",
            "confidence": 0.7,
            "evidence": [{"trajectory": "B", "ref": "   ", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a="a",
        trajectory_b="b",
    )
    assert outcome.evidence_cited is False
    assert outcome.discard_reason == "no_evidence"


def test_pinned_judge_discards_evidence_with_invalid_trajectory_tag() -> None:
    response = json.dumps(
        {
            "pick": "A",
            "confidence": 0.7,
            "evidence": [{"trajectory": "C", "ref": "screenshot_03", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, _, _ = _build_judge(response=response)
    outcome = judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a="a",
        trajectory_b="b",
    )
    assert outcome.evidence_cited is False
    assert outcome.discard_reason == "no_evidence"


@pytest.mark.parametrize(
    "raw",
    [
        # Not JSON.
        "this is not json at all",
        # JSON, but not a top-level object.
        "[1, 2, 3]",
        # Missing ``pick``.
        json.dumps({"confidence": 0.5, "evidence": [], "rationale": "x"}),
        # Invalid pick value.
        json.dumps({"pick": "C", "confidence": 0.5, "evidence": []}),
        # Out-of-range confidence.
        json.dumps({"pick": "A", "confidence": 1.5, "evidence": []}),
        # Boolean masquerading as confidence.
        json.dumps({"pick": "A", "confidence": True, "evidence": []}),
    ],
)
def test_pinned_judge_flags_malformed_response_as_parse_error(raw: str) -> None:
    judge, _, _ = _build_judge(response=raw)
    outcome = judge.judge_presentation(
        _experimental_presentation(),
        task=_judge_task(),
        trajectory_a="a",
        trajectory_b="b",
    )
    assert isinstance(outcome, PinnedJudgeOutcome)
    assert outcome.pick is None
    assert outcome.confidence == 0.0
    assert outcome.evidence_cited is False
    assert outcome.discard_reason == "parse_error"
    assert outcome.raw_response == raw  # raw response preserved verbatim.


# --------------------------------------------------------------------------- #
# Adapter to JudgeCallable (T4.8 swap-consistency aggregator drives this).
# --------------------------------------------------------------------------- #


def test_pinned_judge_as_judge_callable_returns_pick_on_healthy_response() -> None:
    response = json.dumps(
        {
            "pick": "A",
            "confidence": 0.7,
            "evidence": [{"trajectory": "A", "ref": "screenshot_01", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, _, _ = _build_judge(response=response)
    callable_ = judge.as_judge_callable(
        task=_judge_task(),
        trajectory_a="a",
        trajectory_b="b",
    )
    assert callable_(_experimental_presentation()) == "A"


def test_pinned_judge_as_judge_callable_maps_discard_to_abstain() -> None:
    """Discarded calls (no evidence / parse error) surface as abstain to the swap layer."""
    no_evidence = json.dumps({"pick": "B", "confidence": 0.7, "evidence": [], "rationale": "x"})
    judge, _, _ = _build_judge(response=no_evidence)
    callable_ = judge.as_judge_callable(task=_judge_task(), trajectory_a="a", trajectory_b="b")
    assert callable_(_experimental_presentation()) == "abstain"

    parse_error_judge, _, _ = _build_judge(response="not json")
    parse_callable = parse_error_judge.as_judge_callable(
        task=_judge_task(), trajectory_a="a", trajectory_b="b"
    )
    assert parse_callable(_experimental_presentation()) == "abstain"


def test_pinned_judge_drives_swap_consistency_via_existing_aggregator() -> None:
    """End-to-end: PinnedJudge.as_judge_callable composes with evaluate_swap_consistency."""
    # Two healthy calls — one slot-letter on each presentation; consistent.
    healthy_a = json.dumps(
        {
            "pick": "A",
            "confidence": 0.7,
            "evidence": [{"trajectory": "A", "ref": "screenshot_07", "claim": "x"}],
            "rationale": "y",
        }
    )
    healthy_b = json.dumps(
        {
            "pick": "B",
            "confidence": 0.7,
            "evidence": [{"trajectory": "B", "ref": "screenshot_07", "claim": "x"}],
            "rationale": "y",
        }
    )
    judge, client, _ = _build_judge(responses=[healthy_a, healthy_b])
    callable_ = judge.as_judge_callable(task=_judge_task(), trajectory_a="a", trajectory_b="b")

    pair = build_experimental_pairs(_full_cohort())[0]
    results = evaluate_swap_consistency([pair], callable_)

    assert len(client.calls) == 2  # noqa: PLR2004 — spec §5.5 step 6 = two presentations.
    assert results[0].consistent is True
    assert results[0].unswapped_pick == "A"
    assert results[0].swapped_pick == "B"


# --------------------------------------------------------------------------- #
# LLMClient Protocol smoke — anything matching the kw-only signature works.
# --------------------------------------------------------------------------- #


def test_llm_client_protocol_accepts_recording_stub() -> None:
    """The Protocol is structural; the test stub must satisfy it without inheriting."""
    client: LLMClient = _RecordingClient(response="{}")
    out = client.complete(system="s", user="u", model_pin=_judge_model_pin())
    assert out == "{}"
