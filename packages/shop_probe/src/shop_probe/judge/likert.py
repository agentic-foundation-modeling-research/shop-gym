"""Likert quality-dimension judge wiring (T7.2 — spec §5.9 + §7 M7).

The blinded pairwise judge (spec §5.5) is the v1 axis-C instrument; v1.1
adds a complementary **single-trajectory Likert quality judge** (spec §5.9)
that scores each anonymized trajectory on three orthogonal quality
dimensions:

* ``visual_coherence`` — theme consistency and layout polish.
* ``copy_realism`` — product copy and microcopy realism.
* ``error_plausibility`` — failure-mode plausibility.

This module mirrors :mod:`shop_probe.judge.llm` but for the Likert
template: it composes the frozen template, the pinned model identity, and
a caller-supplied :class:`shop_probe.judge.llm.LLMClient`, parses the
spec §5.9 JSON response shape, applies the spec §5.5 guardrails ("calls
without evidence are discarded"), and produces report-shaped artifacts
the report writer can consume directly.

Spec §5.5 guardrails this module enforces (uniformly with the pairwise
judge):

* Force the system + user prompts through the pinned template — no
  ad-hoc rewriting. The rendered prompts are returned alongside the
  outcome so callers can persist them per the "save full prompt"
  guardrail.
* Temperature, model, model version are threaded into every call from
  the pinned :class:`shop_probe.report.JudgeModelPin`.
* The raw response is returned verbatim. Parse failures are non-fatal:
  the outcome carries a ``discard_reason`` and is dropped at scoring
  time.
* Force evidence citation: a successful parse with no cited evidence is
  discarded per spec §5.5 guardrails ("calls without evidence are
  discarded").

The module is import-safe — no I/O at import time.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, cast

from shop_probe.judge.llm import LLMClient
from shop_probe.judge.prompts import LikertPromptSet
from shop_probe.judge.tasks import JudgeTask
from shop_probe.report import (
    LIKERT_DIMENSIONS,
    JudgeModelPin,
    LikertCall,
    LikertDimension,
    LikertDistribution,
    aggregate_likert_distributions,
)

_LIKERT_SCORE_RANGE: Final[tuple[int, int]] = (1, 5)
"""Allowed Likert score range, inclusive (spec §5.9)."""


@dataclass(frozen=True, slots=True)
class LikertOutcome:
    """One Likert judge call's outcome on a single trajectory.

    Returned by :meth:`LikertJudge.judge_trajectory`. The outcome captures
    every artefact the spec §5.5 guardrails require to be saved per call
    (``system_prompt``, ``user_prompt``, ``raw_response``) plus the parsed
    per-dimension scores and evidence flag the report aggregation
    consumes.

    A non-``None`` :attr:`discard_reason` flags a call that must be
    dropped from scoring. The discard reasons in v1.1 are:

    * ``"parse_error"`` — the response was not valid JSON of the
      expected spec §5.9 shape.
    * ``"missing_dimension"`` — the response parsed but did not include a
      score for every :data:`LikertDimension` (spec §5.9 requires all
      three).
    * ``"no_evidence"`` — the response parsed but did not cite any
      trajectory evidence (spec §5.5 guardrails: "calls without
      evidence are discarded").

    Attributes:
        scores: ``LikertDimension -> int`` parsed per-dimension scores in
            ``[1, 5]``. ``None`` only when ``discard_reason`` is
            ``"parse_error"``; on ``"missing_dimension"`` the dict
            holds whichever dimensions parsed successfully so the
            caller can debug.
        evidence_cited: ``True`` iff the response listed at least one
            evidence row with a non-empty ``ref``.
        system_prompt: Rendered system prompt sent to the LLM.
        user_prompt: Rendered user prompt sent to the LLM.
        raw_response: Full response text from the LLM (verbatim).
        prompt_hash: Content hash of the prompt template used (matches
            :attr:`LikertPromptSet.content_hash`); pinned per call.
        model_pin: The :class:`JudgeModelPin` threaded into the LLM call.
        discard_reason: ``None`` for healthy calls; one of the literals
            documented above for dropped calls.
    """

    scores: dict[LikertDimension, int] | None
    evidence_cited: bool
    system_prompt: str
    user_prompt: str
    raw_response: str
    prompt_hash: str
    model_pin: JudgeModelPin
    discard_reason: str | None

    def to_call(self, *, task_id: str, target_label: str) -> LikertCall | None:
        """Convert to a :class:`LikertCall` if the outcome is healthy.

        Returns ``None`` when ``discard_reason is not None`` so callers
        can filter dropped calls before constructing the report.

        Args:
            task_id: Identifier of the judge task that drove the call
                (matches :attr:`JudgeTask.id`).
            target_label: ``Target.label`` of the trajectory's source
                storefront.

        Returns:
            A :class:`LikertCall` row, or ``None`` if the call should be
            discarded.
        """
        if self.discard_reason is not None or self.scores is None:
            return None
        return LikertCall(
            task_id=task_id,
            target_label=target_label,
            visual_coherence=self.scores["visual_coherence"],
            copy_realism=self.scores["copy_realism"],
            error_plausibility=self.scores["error_plausibility"],
            evidence_cited=self.evidence_cited,
            prompt_hash=self.prompt_hash,
            response_text=self.raw_response,
        )


@dataclass(frozen=True, slots=True)
class LikertJudge:
    """Pinned single-judge wiring for the v1.1 Likert quality judge (spec §5.9).

    Composes the frozen Likert prompt template, the pinned model identity,
    and a caller-supplied :class:`LLMClient`. Production wiring uses an
    OpenAI flagship model (e.g. ``gpt-5``, ``temperature=0``); tests pass
    stubs.

    Attributes:
        prompts: Frozen Likert prompt template loaded by
            :func:`shop_probe.judge.prompts.load_likert_prompts`.
        model_pin: Pinned model identity embedded in the report header.
        client: Caller-supplied LLM client (production: OpenAI flagship,
            tests: stub).
    """

    prompts: LikertPromptSet
    model_pin: JudgeModelPin
    client: LLMClient

    def render(
        self,
        *,
        task: JudgeTask,
        anonymized_trajectory: str,
    ) -> tuple[str, str]:
        """Render the system + user prompts for one trajectory.

        Args:
            task: Judge-diagnostic task whose ``description`` enters the
                user prompt. Shared with the pairwise judge per spec
                §5.5 step 1.
            anonymized_trajectory: Anonymized trajectory text under
                review (spec §5.5 step 3 + §5.9).

        Returns:
            ``(system_prompt, user_prompt)`` — both ready for the LLM.
        """
        user_prompt = self.prompts.render_likert(
            task_description=task.description,
            anonymized_trajectory=anonymized_trajectory,
        )
        return self.prompts.system_template, user_prompt

    def judge_trajectory(
        self,
        *,
        task: JudgeTask,
        anonymized_trajectory: str,
    ) -> LikertOutcome:
        """Run one Likert judge call on a single trajectory.

        Drives :attr:`client` exactly once with the rendered system + user
        prompts (spec §5.5 step 5: one shot, ``temperature=0``). The raw
        response is parsed against the spec §5.9 JSON shape; parse
        failures, missing dimensions, and missing-evidence picks are
        flagged via :attr:`LikertOutcome.discard_reason` so report
        aggregation can drop them per spec §5.5 guardrails.

        Args:
            task: Judge-diagnostic task from
                ``judge/tasks/<version>.yaml``.
            anonymized_trajectory: Anonymized trajectory under review.

        Returns:
            A :class:`LikertOutcome` capturing the rendered prompts, the
            raw response, the parsed scores, and the evidence + discard
            flags.
        """
        system_prompt, user_prompt = self.render(
            task=task,
            anonymized_trajectory=anonymized_trajectory,
        )
        raw_response = self.client.complete(
            system=system_prompt,
            user=user_prompt,
            model_pin=self.model_pin,
        )
        parsed = _parse_response(raw_response)
        if parsed is None:
            return LikertOutcome(
                scores=None,
                evidence_cited=False,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=raw_response,
                prompt_hash=self.prompts.content_hash,
                model_pin=self.model_pin,
                discard_reason="parse_error",
            )
        scores, evidence_cited = parsed
        missing = tuple(d for d in LIKERT_DIMENSIONS if d not in scores)
        if missing:
            return LikertOutcome(
                scores=scores,
                evidence_cited=evidence_cited,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=raw_response,
                prompt_hash=self.prompts.content_hash,
                model_pin=self.model_pin,
                discard_reason="missing_dimension",
            )
        discard_reason: str | None = None
        if not evidence_cited:
            discard_reason = "no_evidence"
        return LikertOutcome(
            scores=scores,
            evidence_cited=evidence_cited,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw_response=raw_response,
            prompt_hash=self.prompts.content_hash,
            model_pin=self.model_pin,
            discard_reason=discard_reason,
        )


def compute_likert_distributions(
    calls: Sequence[LikertCall],
) -> tuple[LikertDistribution, ...]:
    """Aggregate :class:`LikertCall` rows into per-dimension distributions.

    Thin wrapper over :func:`shop_probe.report.aggregate_likert_distributions`
    so the Likert judge module exposes the full pipeline (call → outcome →
    report-shaped distribution) in one place. The wrapper exists for
    discoverability — the canonical aggregation logic stays on the report
    schema so it can be re-used without depending on the LLM judge.

    Args:
        calls: All :class:`LikertCall` rows for one report (post-discard).

    Returns:
        One :class:`LikertDistribution` per :data:`LikertDimension`.
    """
    return aggregate_likert_distributions(calls)


# --------------------------------------------------------------------------- #
# Internals — kept separate so unit tests can pin every parse branch directly.
# --------------------------------------------------------------------------- #


def _parse_response(text: str) -> tuple[dict[LikertDimension, int], bool] | None:
    """Parse a Likert judge response per spec §5.9.

    The spec §5.9 prompt asks for JSON with ``ratings`` (per-dimension
    scores) + ``evidence`` + ``rationale``. Models occasionally wrap that
    in ```` ```json `` … `` ``` ```` fences; this parser tolerates that
    single deviation and rejects everything else.

    Returns:
        ``(scores, evidence_cited)`` on success; ``None`` if the response
        is not parseable into the spec §5.9 shape. ``scores`` may be a
        proper subset of :data:`LIKERT_DIMENSIONS` — callers map that to
        a ``"missing_dimension"`` discard.
    """
    body = _strip_code_fences(text.strip())
    try:
        payload: object = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload_dict = cast("dict[str, object]", payload)
    raw_ratings = payload_dict.get("ratings")
    if not isinstance(raw_ratings, dict):
        return None
    ratings_dict = cast("dict[str, object]", raw_ratings)
    scores: dict[LikertDimension, int] = {}
    for dimension in LIKERT_DIMENSIONS:
        score = _coerce_score(ratings_dict.get(dimension))
        if score is None:
            continue
        scores[dimension] = score
    evidence_cited = _has_evidence(payload_dict.get("evidence"))
    return scores, evidence_cited


def _coerce_score(value: object) -> int | None:
    """Return ``value`` as an int in ``[1, 5]`` or ``None`` if invalid.

    Booleans subclass ``int`` in Python; reject them explicitly so
    ``"visual_coherence": true`` cannot masquerade as ``1``.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    lo, hi = _LIKERT_SCORE_RANGE
    if value < lo or value > hi:
        return None
    return value


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
    """Return ``True`` iff at least one evidence row carries a non-empty ``ref``.

    Spec §5.5 guardrails require evidence citation on every healthy call.
    The Likert template per spec §5.9 omits the ``trajectory`` field
    (single-trajectory call), so we only require a non-empty ``ref``
    string per row.
    """
    if not isinstance(evidence, list):
        return False
    evidence_list = cast("list[object]", evidence)
    for entry in evidence_list:
        if not isinstance(entry, dict):
            continue
        entry_dict = cast("dict[str, object]", entry)
        ref = entry_dict.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            continue
        return True
    return False
