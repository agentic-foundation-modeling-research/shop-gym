"""Pinned single-judge wiring (T4.6 — spec §5.5 step 5 + guardrails).

The blinded pairwise judge (spec §5.5) is the axis-C instrument. T4.6 owns
the *wiring* layer that ties together the four pieces below and produces a
:class:`shop_probe.report.JudgeCall`-shaped outcome for one
:class:`shop_probe.judge.swap.Presentation`:

1. The pinned model identity (:class:`shop_probe.report.JudgeModelPin`)
   embedded in the report header per spec §5.5 guardrails.
2. The frozen prompt template (:class:`shop_probe.judge.prompts.JudgePromptSet`)
   loaded from ``judge/prompts/<version>/`` per T4.7.
3. A caller-supplied :class:`LLMClient` that performs the actual model call.
   Production wiring uses an OpenAI flagship model (e.g. ``gpt-5``,
   temperature 0); tests pass stubs.
4. The judge-task description and pre-anonymized trajectory pair from
   T4.4 / T4.5.

Spec §5.5 guardrails this module enforces:

* Force the system + user prompts through the pinned template (no
  ad-hoc rewriting). The rendered prompts are returned alongside the
  outcome so callers can persist them per the "save full prompt"
  guardrail.
* Temperature, model, model version are threaded into every call from
  the pinned :class:`JudgeModelPin`; the report header value and the
  call-time value cannot drift.
* The raw response is returned verbatim. Parse failures are non-fatal:
  the outcome carries a ``discard_reason`` and the call is dropped at
  scoring time.
* Force evidence citation: a non-abstain pick that fails to cite at
  least one trajectory ``ref`` is discarded per spec §5.5 guardrails
  ("calls without evidence are discarded").

Position-bias handling (spec §5.5 step 6) and ``swap_consistent`` /
``truth`` aggregation live one layer up in
:mod:`shop_probe.judge.swap` — this module is concerned with one
presentation per call. The :class:`PinnedJudge.as_judge_callable` helper
adapts to the :class:`shop_probe.judge.swap.JudgeCallable` Protocol so
:func:`shop_probe.judge.swap.evaluate_swap_consistency` can drive it
unchanged.

The module is import-safe — no I/O at import time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, Protocol, cast

from shop_probe.judge.prompts import JudgePromptSet
from shop_probe.judge.swap import Presentation
from shop_probe.judge.tasks import JudgeTask
from shop_probe.report import JudgeModelPin, JudgePick

_VALID_PICKS: Final[frozenset[str]] = frozenset({"A", "B", "abstain"})
"""The three values :data:`shop_probe.report.JudgePick` accepts (spec §5.5 step 5)."""

_VALID_EVIDENCE_TRAJECTORIES: Final[frozenset[str]] = frozenset({"A", "B"})
"""Trajectory tags allowed inside an evidence citation (spec §8.3 prompt)."""


class LLMClient(Protocol):
    """Stub-friendly interface for the pinned judge LLM.

    Production callers wrap an OpenAI client behind this interface so the
    rest of the judge pipeline stays vendor-neutral; tests pass a recording
    stub.

    Implementations MUST:

    * Use ``model_pin.model`` / ``model_pin.model_version`` to select the
      exact model revision; never fall back to a different revision when
      the pinned one is unavailable (raise instead).
    * Send ``system`` as the system message and ``user`` as the (only)
      user turn. Do not append automated retries — spec §5.5 guardrails
      require ``temperature=0`` and one shot per pairwise call.
    * Return the raw response text verbatim, with no surrounding metadata
      stripping. Parse + validation lives in :class:`PinnedJudge`.
    """

    def complete(
        self,
        *,
        system: str,
        user: str,
        model_pin: JudgeModelPin,
    ) -> str:
        """Run one pairwise judge invocation.

        Args:
            system: Rendered system-prompt body
                (:attr:`JudgePromptSet.system_template`).
            user: Rendered user-prompt body
                (:meth:`JudgePromptSet.render_pairwise` output).
            model_pin: Pinned model + version + temperature; passed
                explicitly so the client cannot silently drift from
                the report header.

        Returns:
            The raw response text from the judge model.
        """
        ...


@dataclass(frozen=True, slots=True)
class PinnedJudgeOutcome:
    """One pairwise judge call's outcome on a single presentation.

    Returned by :meth:`PinnedJudge.judge_presentation`. The outcome
    captures every artefact the spec §5.5 guardrails require to be
    saved per call (``system_prompt``, ``user_prompt``, ``raw_response``)
    plus the parsed pick + evidence flag the swap-consistency layer
    consumes (spec §5.5 step 6).

    A non-``None`` :attr:`discard_reason` flags a call that must be
    dropped from scoring. The discard reasons in v1 are:

    * ``"parse_error"`` — the response was not valid JSON of the
      expected shape (spec §8.3).
    * ``"no_evidence"`` — the response chose ``"A"`` or ``"B"`` but
      did not cite any trajectory reference (spec §5.5 guardrails:
      "calls without evidence are discarded").

    ``"abstain"`` is *not* a discard — it is a recorded outcome with
    no contribution to the pick distribution. Callers that need to
    drop abstentions do so at the scoring layer.

    Attributes:
        pick: ``"A"``, ``"B"``, or ``"abstain"`` if the response parsed.
            ``None`` only when ``discard_reason == "parse_error"``.
        confidence: Self-reported confidence in ``[0, 1]``. ``0.0`` on
            parse failure.
        evidence_cited: ``True`` iff the response listed at least one
            evidence row with a non-empty ``ref``.
        system_prompt: Rendered system prompt sent to the LLM.
        user_prompt: Rendered user prompt sent to the LLM.
        raw_response: Full response text from the LLM (verbatim).
        prompt_hash: Content hash of the prompt template used (matches
            :attr:`JudgePromptSet.content_hash`); pinned per call.
        model_pin: The :class:`JudgeModelPin` threaded into the LLM call.
        discard_reason: ``None`` for healthy calls; one of the literals
            documented above for dropped calls.
    """

    pick: JudgePick | None
    confidence: float
    evidence_cited: bool
    system_prompt: str
    user_prompt: str
    raw_response: str
    prompt_hash: str
    model_pin: JudgeModelPin
    discard_reason: str | None


@dataclass(frozen=True, slots=True)
class PinnedJudge:
    """Pinned single-judge wiring for the blinded pairwise judge (spec §5.5).

    Composes the frozen prompt template, the pinned model identity, and a
    caller-supplied :class:`LLMClient`. The result is callable via
    :meth:`judge_presentation` (one presentation in, one
    :class:`PinnedJudgeOutcome` out) or via :meth:`as_judge_callable`
    (adapter to the :class:`shop_probe.judge.swap.JudgeCallable`
    Protocol so :func:`evaluate_swap_consistency` can drive it).

    Attributes:
        prompts: Frozen prompt template loaded by T4.7.
        model_pin: Pinned model identity embedded in the report header.
        client: Caller-supplied LLM client (production: OpenAI flagship,
            tests: stub).
    """

    prompts: JudgePromptSet
    model_pin: JudgeModelPin
    client: LLMClient

    def render(
        self,
        *,
        presentation: Presentation,
        task: JudgeTask,
        trajectory_a: str,
        trajectory_b: str,
    ) -> tuple[str, str]:
        """Render the system + user prompts for one presentation.

        Spec §5.5 step 5 mandates one *identical* prompt for experimental
        and control conditions; this helper guarantees the rendered text
        contains no condition-conditional branches by routing every call
        through :meth:`JudgePromptSet.render_pairwise`.

        Args:
            presentation: The pair + swap state. Carried into the outcome
                only — the prompt body itself never names the swap state
                (spec §5.5 step 6).
            task: The judge-diagnostic task whose ``description`` enters
                the user prompt.
            trajectory_a: Anonymized trajectory shown in slot ``"A"``.
                Resolution to canonical members happens upstream via
                :attr:`Presentation.position_a`.
            trajectory_b: Anonymized trajectory shown in slot ``"B"``.

        Returns:
            ``(system_prompt, user_prompt)`` — both ready for the LLM.
        """
        # Touch ``presentation`` so callers cannot pass a mismatched arg
        # without it being part of the contract; the value itself is not
        # encoded in the prompt body per spec §5.5 step 5.
        del presentation
        user_prompt = self.prompts.render_pairwise(
            task_description=task.description,
            anonymized_trajectory_a=trajectory_a,
            anonymized_trajectory_b=trajectory_b,
        )
        return self.prompts.system_template, user_prompt

    def judge_presentation(
        self,
        presentation: Presentation,
        *,
        task: JudgeTask,
        trajectory_a: str,
        trajectory_b: str,
    ) -> PinnedJudgeOutcome:
        """Run one pairwise judge call on a single presentation.

        Drives :attr:`client` exactly once with the rendered system + user
        prompts (spec §5.5 step 5: one shot, ``temperature=0``). The raw
        response is parsed against the spec §8.3 JSON shape; parse
        failures and missing-evidence picks are flagged via
        :attr:`PinnedJudgeOutcome.discard_reason` so swap aggregation
        can drop them per spec §5.5 guardrails.

        Args:
            presentation: The pair + swap state. Used only for the
                returned outcome's bookkeeping; the prompt body does not
                encode it (spec §5.5 step 6).
            task: Judge-diagnostic task from
                ``judge/tasks/<version>.yaml``.
            trajectory_a: Anonymized trajectory in slot ``"A"``.
            trajectory_b: Anonymized trajectory in slot ``"B"``.

        Returns:
            A :class:`PinnedJudgeOutcome` capturing the rendered prompts,
            the raw response, the parsed pick, and the evidence + discard
            flags.
        """
        system_prompt, user_prompt = self.render(
            presentation=presentation,
            task=task,
            trajectory_a=trajectory_a,
            trajectory_b=trajectory_b,
        )
        raw_response = self.client.complete(
            system=system_prompt,
            user=user_prompt,
            model_pin=self.model_pin,
        )
        parsed = _parse_response(raw_response)
        if parsed is None:
            return PinnedJudgeOutcome(
                pick=None,
                confidence=0.0,
                evidence_cited=False,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=raw_response,
                prompt_hash=self.prompts.content_hash,
                model_pin=self.model_pin,
                discard_reason="parse_error",
            )
        pick, confidence, evidence_cited = parsed
        discard_reason: str | None = None
        if pick != "abstain" and not evidence_cited:
            discard_reason = "no_evidence"
        return PinnedJudgeOutcome(
            pick=pick,
            confidence=confidence,
            evidence_cited=evidence_cited,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw_response=raw_response,
            prompt_hash=self.prompts.content_hash,
            model_pin=self.model_pin,
            discard_reason=discard_reason,
        )

    def as_judge_callable(
        self,
        *,
        task: JudgeTask,
        trajectory_a: str,
        trajectory_b: str,
    ) -> _JudgeCallable:
        """Adapt to :class:`shop_probe.judge.swap.JudgeCallable`.

        :func:`shop_probe.judge.swap.evaluate_swap_consistency` consumes a
        ``Callable[[Presentation], JudgePick]``. Production wiring binds
        the task + trajectory pair into a closure so the swap layer can
        drive the pinned judge unchanged. Discarded calls (parse error or
        no evidence) surface as ``"abstain"`` per spec §5.5 guardrails:
        :func:`shop_probe.judge.swap.is_swap_consistent` already drops
        abstentions, so this maps the discard semantics onto the existing
        consistency contract without duplication.

        Args:
            task: Pinned judge-diagnostic task for the closure.
            trajectory_a: Anonymized trajectory in slot ``"A"``.
            trajectory_b: Anonymized trajectory in slot ``"B"``.

        Returns:
            A callable suitable for
            :func:`shop_probe.judge.swap.evaluate_swap_consistency`.
        """

        def _call(presentation: Presentation) -> JudgePick:
            outcome = self.judge_presentation(
                presentation,
                task=task,
                trajectory_a=trajectory_a,
                trajectory_b=trajectory_b,
            )
            if outcome.discard_reason is not None:
                return "abstain"
            if outcome.pick is None:
                # Defensive: parse-success guarantees a non-None pick. Map the
                # impossible-here case to abstain so the swap layer drops it.
                return "abstain"
            return outcome.pick

        return _call


# Local Protocol alias used only as a return annotation for
# `as_judge_callable`. Re-defining here (rather than importing
# `shop_probe.judge.swap.JudgeCallable`) keeps llm.py free of cycles
# while giving the type checker a precise signature.
class _JudgeCallable(Protocol):
    def __call__(self, presentation: Presentation) -> JudgePick: ...


def _parse_response(text: str) -> tuple[JudgePick, float, bool] | None:
    """Parse a judge response per spec §8.3.

    The spec §8.3 prompt asks for JSON with ``pick`` + ``confidence`` +
    ``evidence`` + ``rationale``. Models occasionally wrap that in
    ``\u200b```json`` … `````` fences; this parser tolerates that single
    deviation and rejects everything else.

    Returns:
        ``(pick, confidence, evidence_cited)`` on success; ``None`` if the
        response is not parseable into the spec §8.3 shape.
    """
    body = _strip_code_fences(text.strip())
    try:
        payload: object = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    # ``json.loads`` already returns ``dict[str, Any]``-shaped data here,
    # but pyright in strict mode tracks the wider ``dict[Unknown, Unknown]``
    # narrowed from ``object``. Re-typing through a ``cast`` avoids the
    # downstream Unknown propagation without weakening the runtime checks
    # that follow.
    payload_dict = cast("dict[str, object]", payload)
    pick = payload_dict.get("pick")
    if not isinstance(pick, str) or pick not in _VALID_PICKS:
        return None
    raw_confidence = payload_dict.get("confidence")
    # Booleans subclass int in Python; reject them explicitly so
    # ``"confidence": true`` cannot masquerade as ``1.0``.
    if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
        return None
    confidence = float(raw_confidence)
    if not 0.0 <= confidence <= 1.0:
        return None
    evidence_cited = _has_evidence(payload_dict.get("evidence"))
    # ``pick`` is one of the three :data:`JudgePick` literals — narrow for the
    # type checker.
    narrowed_pick: JudgePick = cast("JudgePick", pick)
    return narrowed_pick, confidence, evidence_cited


def _strip_code_fences(text: str) -> str:
    """Strip a single surrounding ```...``` fence if present.

    No-op for already-clean JSON. Only strips one outer fence — nested
    fences fall through to :func:`json.loads` and trigger a parse error.
    """
    if not text.startswith("```"):
        return text
    newline_idx = text.find("\n")
    if newline_idx == -1:
        return text
    inner = text[newline_idx + 1 :].rstrip()
    if inner.endswith("```"):
        inner = inner[:-3].rstrip()
    return inner


def _has_evidence(evidence: object) -> bool:
    """Return ``True`` iff at least one evidence row cites a trajectory ref.

    Spec §5.5 guardrails require evidence citation on every non-abstain
    pick. The shape per §8.3 is ``[{"trajectory": "A"|"B", "ref": "...",
    "claim": "..."}]``; we accept any row with a non-empty ``ref`` string
    pointing at a valid trajectory tag, since the production prompt only
    instructs the model to cite, not to follow a strict JSON schema for
    each entry.
    """
    if not isinstance(evidence, list):
        return False
    evidence_list = cast("list[object]", evidence)
    for entry in evidence_list:
        if not isinstance(entry, dict):
            continue
        entry_dict = cast("dict[str, object]", entry)
        ref = entry_dict.get("ref")
        trajectory = entry_dict.get("trajectory")
        if not isinstance(ref, str) or not ref.strip():
            continue
        if trajectory not in _VALID_EVIDENCE_TRAJECTORIES:
            continue
        return True
    return False
