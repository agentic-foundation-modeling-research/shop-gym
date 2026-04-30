"""Capture-judge call: one Anthropic Messages API request over a page bundle.

For each ``level: capture_judge`` rubric entry the dispatcher slices the
per-shop bundle by :attr:`CaptureJudgeTask.pages`, attaches the screenshot
+ accessibility-tree JSON for every applicable :class:`PageCapture`, and
asks the model the rubric's structural-affordance question. The model is
asked to return ``{"passed": bool, "reasoning": str}``; malformed output
falls back to a regex match so a single sloppy response cannot crash a
cohort run.

Cost computation projects ``usage.input_tokens`` / ``usage.output_tokens``
to USD via a per-model rate table. The module is import-safe:
``anthropic`` is imported lazily inside :func:`run_capture_judge` so
importing this module does not create an :class:`AsyncAnthropic` client.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)

from shop_probe.agent.env import load_agent_env, require_anthropic_credentials
from shop_probe.capture.bundle import PageCapture

_RATE_TABLE: Final[dict[str, tuple[float, float]]] = {
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
"""Per-model rate table (USD per million tokens, ``(input, output)``)."""

_DEFAULT_RATE: Final[tuple[float, float]] = (15.0, 75.0)
"""Fallback rate (Opus tier) for models not in :data:`_RATE_TABLE`."""

_PASSED_FALLBACK_RE: Final[re.Pattern[str]] = re.compile(
    r'"?passed"?\s*[:=]\s*(true|false)',
    re.IGNORECASE,
)

_JSON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"\{[^{}]*\}",
    re.DOTALL,
)

_MAX_OUTPUT_TOKENS: Final[int] = 512
"""Cap on judge response length."""

_RETRY_MAX_ATTEMPTS: Final[int] = 8
"""Cap on Messages-API retry attempts before giving up."""

_RETRY_BASE_DELAY_S: Final[float] = 2.0
_RETRY_MAX_DELAY_S: Final[float] = 120.0


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Closed return type for the capture-judge call.

    Attributes:
        passed: ``True`` iff the storefront exposes the affordance the
            rubric asked about.
        reasoning: One-sentence explanation. When the parser fell back
            from JSON to regex, the string is prefixed with
            ``"[fallback parse]"`` so callers can surface the
            degradation in their notes.
        cost_usd: Estimated USD cost of the underlying Messages API
            call.
        model_id: Pinned model identifier the judge ran against.
    """

    passed: bool
    reasoning: str
    cost_usd: float
    model_id: str


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _retry_backoff(attempt: int) -> float:
    base = min(_RETRY_BASE_DELAY_S * (2**attempt), _RETRY_MAX_DELAY_S)
    return base * (0.5 + random.random())


async def _messages_create_with_retry(
    client: AsyncAnthropic,
    *,
    model: str,
    max_tokens: int,
    messages: list[dict[str, object]],
) -> object:
    """Call ``client.messages.create`` with bounded exponential-backoff retry.

    Retries on 429 / transient transport errors / 5xx; other 4xx errors
    propagate immediately so we don't paper over real misconfiguration.
    """
    last_exc: BaseException | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,  # type: ignore[arg-type]
            )
        except RateLimitError as exc:
            last_exc = exc
            delay = _retry_after_seconds(exc) or _retry_backoff(attempt)
        except (APIConnectionError, APITimeoutError) as exc:
            last_exc = exc
            delay = _retry_backoff(attempt)
        except APIStatusError as exc:
            if exc.status_code < 500:  # noqa: PLR2004 — HTTP semantics
                raise
            last_exc = exc
            delay = _retry_backoff(attempt)
        if attempt + 1 == _RETRY_MAX_ATTEMPTS:
            break
        await asyncio.sleep(min(delay, _RETRY_MAX_DELAY_S))
    assert last_exc is not None
    raise last_exc


def _encode_image(path: Path) -> dict[str, object]:
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
    in_rate, out_rate = _RATE_TABLE.get(model, _DEFAULT_RATE)
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0


def _extract_text(message: object) -> str:
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
    """Parse the judge response body into ``(passed, reasoning, fallback)``."""
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


def _read_a11y_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _build_capture_judge_content(
    captures: tuple[PageCapture, ...],
    bundle_root: Path,
    judge_prompt: str,
) -> list[dict[str, object]]:
    """Assemble the Messages-API content list for one capture-judge call."""
    content: list[dict[str, object]] = []
    for capture in captures:
        if capture.screenshot_rel is None or capture.accessibility_rel is None:
            continue
        screenshot_path = bundle_root / capture.screenshot_rel
        a11y_path = bundle_root / capture.accessibility_rel
        content.append(
            {
                "type": "text",
                "text": f"{capture.page_ref} ({capture.url}) — screenshot:",
            }
        )
        content.append(_encode_image(screenshot_path))
        content.append(
            {
                "type": "text",
                "text": (
                    f"{capture.page_ref} accessibility tree:\n```json\n"
                    f"{_read_a11y_text(a11y_path)}\n```"
                ),
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                f"Rubric question:\n{judge_prompt}\n\n"
                "Decide whether the storefront exposes the affordance described "
                "above. You are looking at static page captures — judge structural "
                "presence, not interaction. Respond with a single-line JSON object "
                'exactly of the form {"passed": <true|false>, "reasoning": '
                '"<one short sentence>"}. Do not wrap the response in Markdown.'
            ),
        }
    )
    return content


async def run_capture_judge(
    captures: tuple[PageCapture, ...],
    bundle_root: Path,
    judge_prompt: str,
    *,
    model: str = "claude-opus-4-7",
    client: AsyncAnthropic | None = None,
) -> JudgeVerdict:
    """Issue one Messages-API call over a capture-bundle slice.

    For each applicable :class:`PageCapture` we attach the screenshot
    and the aria-snapshot JSON; we then ask the judge the rubric's
    structural-affordance question and parse the response into the
    closed :class:`JudgeVerdict` shape.

    When **every** capture in ``captures`` has ``applicable=False``,
    the function short-circuits with
    ``JudgeVerdict(passed=False, reasoning="bundle pages unavailable",
    cost_usd=0.0, model_id=model)`` — **no Anthropic call is issued**.

    Args:
        captures: Bundle slice the rubric entry asked for, in
            :data:`PageRef` order. ``applicable=False`` rows are
            dropped from the prompt; an entirely-inapplicable slice
            short-circuits.
        bundle_root: Directory under which the bundle's per-page files
            live (typically ``evidence_root / "_bundle"``).
        judge_prompt: The rubric entry's
            ``CaptureJudgeTask.judge_prompt`` verbatim.
        model: Anthropic model id (default ``"claude-opus-4-7"``).
        client: Optional pre-built :class:`AsyncAnthropic` client; tests
            inject a stub here. ``None`` constructs a client lazily so
            the module stays import-safe.

    Returns:
        A populated :class:`JudgeVerdict`.
    """
    applicable = tuple(c for c in captures if c.applicable)
    if not applicable:
        return JudgeVerdict(
            passed=False,
            reasoning="bundle pages unavailable",
            cost_usd=0.0,
            model_id=model,
        )

    if client is None:
        load_agent_env()
        require_anthropic_credentials()
        client = AsyncAnthropic()

    content = _build_capture_judge_content(applicable, bundle_root, judge_prompt)
    response = await _messages_create_with_retry(
        client,
        model=model,
        max_tokens=_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": content}],
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
