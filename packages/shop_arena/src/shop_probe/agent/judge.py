"""Vision completion judge for the v1.3 agent-driven advanced tier (T3.1).

Issues a single Anthropic Messages API request that combines two screenshots
(BEFORE / AFTER labels), the harness trajectory rendered as compact text,
and the inline ``judge_prompt`` from a ``level: agent_driven`` rubric entry.
The model is asked to return JSON ``{"passed": bool, "reasoning": str}``;
malformed output falls back to a ``passed:\\s*(true|false)`` regex match so
a single sloppy response cannot crash a cohort run.

Cost computation mirrors :mod:`shop_probe.judge.run` (``ClassifierResult``
exposes the same ``cost_usd`` / ``model_id`` fields the report aggregates).
The Anthropic ``Message.usage`` object reports
``usage.input_tokens`` / ``usage.output_tokens``; we multiply by a per-model
rate table to project a USD figure.

The module is import-safe: ``anthropic`` is imported lazily inside
:func:`run_completion_judge` so importing this module does not create an
:class:`~anthropic.AsyncAnthropic` client (which reads ``ANTHROPIC_API_KEY``
from the environment) at import time.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from anthropic import AsyncAnthropic

_RATE_TABLE: Final[dict[str, tuple[float, float]]] = {
    # USD per million tokens: (input, output). Source: Anthropic public
    # pricing for the models referenced by the v1.3 implementation plan.
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}
"""Per-model rate table (USD per million tokens, ``(input, output)``)."""

_DEFAULT_RATE: Final[tuple[float, float]] = (15.0, 75.0)
"""Fallback rate (Opus tier) for models not in :data:`_RATE_TABLE`."""

_PASSED_FALLBACK_RE: Final[re.Pattern[str]] = re.compile(
    r'"?passed"?\s*[:=]\s*(true|false)',
    re.IGNORECASE,
)
"""Regex used when the model returns prose instead of valid JSON.

Matches both bare (``passed: true``) and JSON-style (``"passed": false``)
forms. Case-insensitive so ``True`` / ``False`` literals also parse.
"""

_JSON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"\{[^{}]*\}",
    re.DOTALL,
)
"""Best-effort match for a single brace-delimited JSON object in the body.

The judge prompt instructs the model to emit a one-line JSON object, but
fenced code blocks and stray prose are common; this pattern lets us
recover from both without a full JSON-aware parser.
"""

_MAX_OUTPUT_TOKENS: Final[int] = 512
"""Cap on judge response length.

The verdict shape is two short fields (``passed`` + one-sentence
``reasoning``); 512 tokens is well above the expected envelope and below
any per-request rate limit we care about.
"""


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Closed return type for the vision completion judge.

    Attributes:
        passed: ``True`` iff the agent completed the rubric task as judged
            from the BEFORE / AFTER screenshots and the trajectory.
        reasoning: One-sentence explanation. When the parser fell back from
            JSON to a regex match, the string is prefixed with
            ``"[fallback parse]"`` so callers can surface the degradation
            in their notes.
        cost_usd: Estimated USD cost of the underlying Messages API call,
            derived from ``usage.input_tokens`` / ``usage.output_tokens``
            via :data:`_RATE_TABLE`.
        model_id: Pinned model identifier the judge ran against. Echoed
            verbatim into ``ProbeOutcome.extra`` so the report can group
            costs by model.
    """

    passed: bool
    reasoning: str
    cost_usd: float
    model_id: str


def _encode_image(path: Path) -> dict[str, object]:
    """Render ``path`` as an Anthropic ``image`` content block.

    Args:
        path: PNG screenshot the runner persisted under ``ctx.evidence_root``.

    Returns:
        A content-block dict with a base64-encoded ``image/png`` source,
        ready to drop into a :class:`MessageParam` content list.
    """
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": data,
        },
    }


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Project ``(input_tokens, output_tokens)`` to USD via :data:`_RATE_TABLE`.

    Args:
        model: Anthropic model id (e.g. ``"claude-opus-4-7"``).
        input_tokens: ``usage.input_tokens`` from the Messages response.
        output_tokens: ``usage.output_tokens`` from the Messages response.

    Returns:
        Estimated USD cost. Models outside :data:`_RATE_TABLE` fall back to
        Opus rates so a misconfigured ``--agent-judge-model`` flag never
        underreports cost.
    """
    in_rate, out_rate = _RATE_TABLE.get(model, _DEFAULT_RATE)
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0


def _extract_text(message: object) -> str:
    """Concatenate the text blocks on an Anthropic :class:`Message`.

    The Messages API returns ``content`` as a list of typed blocks; only
    ``type == "text"`` blocks carry the verdict body. We walk them
    defensively (``getattr``) so a stub ``Message`` shape in tests doesn't
    have to mirror every Anthropic SDK attribute.

    Args:
        message: The :class:`anthropic.types.Message` (or test stub).

    Returns:
        Concatenated text, stripped of leading / trailing whitespace.
    """
    raw_blocks: object = getattr(message, "content", None) or []
    out: list[str] = []
    if not isinstance(raw_blocks, list):
        return ""
    blocks: list[object] = list(raw_blocks)  # pyright: ignore[reportUnknownArgumentType]
    for block in blocks:
        kind = getattr(block, "type", None)
        if kind != "text":
            continue
        text = getattr(block, "text", "")
        if isinstance(text, str):
            out.append(text)
    return "\n".join(out).strip()


def _parse_verdict(text: str) -> tuple[bool, str, bool]:
    """Parse the judge response body into ``(passed, reasoning, fallback)``.

    Tries strict JSON first (the prompt asks for a one-line object); on
    failure scans for an embedded ``{...}`` block; on failure runs the
    :data:`_PASSED_FALLBACK_RE` regex over the raw text. The third tuple
    element flags whether the regex fallback fired so callers can surface
    the degradation in ``reasoning``.

    Args:
        text: Concatenated text blocks from the Messages response.

    Returns:
        ``(passed, reasoning, fallback_used)``. When neither parser
        recovers a verdict, ``passed`` is ``False`` and ``reasoning``
        carries the raw body so the operator can debug.
    """
    candidates: list[str] = [text]
    for match in _JSON_BLOCK_RE.findall(text):
        candidates.append(match)
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "passed" in obj:
            obj_dict: dict[object, object] = obj  # pyright: ignore[reportUnknownVariableType]
            passed = bool(obj_dict["passed"])
            raw_reasoning = obj_dict.get("reasoning", "")
            reasoning = str(raw_reasoning) if raw_reasoning is not None else ""
            return passed, reasoning, False
    match = _PASSED_FALLBACK_RE.search(text)
    if match is not None:
        passed = match.group(1).lower() == "true"
        return passed, f"[fallback parse] {text.strip()}", True
    return False, f"[unparseable judge response] {text.strip()}", True


def _build_user_content(
    *,
    before_shot: Path,
    after_shot: Path,
    trajectory_text: str,
    judge_prompt: str,
) -> list[dict[str, object]]:
    """Assemble the user-message content list for the judge call.

    Layout (order matters — the model reads top-to-bottom):

    1. Text label ``BEFORE``.
    2. Base64 ``image/png`` block — pre-action state.
    3. Text label ``AFTER``.
    4. Base64 ``image/png`` block — post-action state.
    5. Compact trajectory rendering inside a fenced code block.
    6. The rubric entry's ``judge_prompt`` verbatim.
    7. Closing instruction asking for ``{"passed": bool, "reasoning": str}``.
    """
    return [
        {
            "type": "text",
            "text": "BEFORE screenshot — storefront state before the agent acted:",
        },
        _encode_image(before_shot),
        {
            "type": "text",
            "text": "AFTER screenshot — storefront state after the agent acted:",
        },
        _encode_image(after_shot),
        {
            "type": "text",
            "text": (f"Agent trajectory (compact text rendering):\n```\n{trajectory_text}\n```"),
        },
        {
            "type": "text",
            "text": (
                f"Rubric question:\n{judge_prompt}\n\n"
                "Decide whether the agent completed the task. Respond with a "
                "single-line JSON object exactly of the form "
                '{"passed": <true|false>, "reasoning": "<one short sentence>"}. '
                "Do not wrap the response in Markdown."
            ),
        },
    ]


async def run_completion_judge(
    before_shot: Path,
    after_shot: Path,
    trajectory_text: str,
    judge_prompt: str,
    *,
    model: str = "claude-opus-4-7",
    client: AsyncAnthropic | None = None,
) -> JudgeVerdict:
    """Run the vision completion judge for one agent-driven probe.

    Issues a single Anthropic Messages API call combining both screenshots,
    the trajectory text, and the rubric ``judge_prompt``; parses the model
    response into a closed :class:`JudgeVerdict` with cost projected from
    ``usage.input_tokens`` / ``usage.output_tokens``.

    Args:
        before_shot: Absolute path to the BEFORE PNG captured before the
            agent acted.
        after_shot: Absolute path to the AFTER PNG; usually the last
            :class:`harness.trajectory.ScreenshotStep` in the harness run,
            falling back to ``before_shot`` when the agent emitted none.
        trajectory_text: Compact text rendering of the harness trajectory
            (per-iteration goals + tool calls + final URLs).
        judge_prompt: The rubric entry's ``agent_task.judge_prompt``,
            embedded verbatim so the judge sees the same question the
            rubric author wrote.
        model: Anthropic model id. Defaults to ``"claude-opus-4-7"``;
            ``--agent-judge-model`` (M6) feeds an alternate value.
        client: Optional pre-built :class:`AsyncAnthropic` client. Tests
            inject a stub here; production callers leave it ``None`` so we
            construct a fresh client lazily (which reads
            ``ANTHROPIC_API_KEY`` from the environment).

    Returns:
        A :class:`JudgeVerdict`. ``passed`` reflects the model's decision
        (or the regex fallback when the response is malformed);
        ``cost_usd`` is the per-call USD estimate.
    """
    if client is None:
        # Lazy construction keeps this module import-safe (the ``AsyncAnthropic``
        # constructor reads ``ANTHROPIC_API_KEY`` from the environment).
        client = AsyncAnthropic()

    content = _build_user_content(
        before_shot=before_shot,
        after_shot=after_shot,
        trajectory_text=trajectory_text,
        judge_prompt=judge_prompt,
    )
    response = await client.messages.create(
        model=model,
        max_tokens=_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": content}],  # type: ignore[arg-type]
    )

    raw = _extract_text(response)
    passed, reasoning, _fallback = _parse_verdict(raw)

    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cost_usd = _compute_cost(model, input_tokens, output_tokens)

    return JudgeVerdict(
        passed=passed,
        reasoning=reasoning,
        cost_usd=cost_usd,
        model_id=model,
    )
