"""Capture-judge call: one provider Messages-style API request over a page bundle.

For each ``level: capture_judge`` rubric entry the dispatcher slices the
per-shop bundle by :attr:`CaptureJudgeTask.pages`, attaches the
screenshot + accessibility-tree JSON for every applicable
:class:`PageCapture`, and asks the model the rubric's
structural-affordance question. The model is asked to return
``{"passed": bool, "reasoning": str}``; malformed output falls back to
a regex match so a single sloppy response cannot crash a cohort run.

The provider is selected by an explicit prefix on the model id:
``anthropic:<id>`` routes through the Anthropic Messages API,
``openai:<id>`` routes through OpenAI Chat Completions. Unprefixed ids
are rejected at startup so typos surface immediately.

Cost computation projects per-call token usage to USD via a per-model
rate table keyed on the full prefixed id, so providers cannot collide.
The module is import-safe: provider SDK clients are constructed lazily
inside :func:`run_capture_judge`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import random
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shop_probe.agent.env import (
    JudgeProvider,
    load_agent_env,
    require_credentials,
)
from shop_probe.capture.bundle import PageCapture

_RATE_TABLE: Final[dict[str, tuple[float, float]]] = {
    # Anthropic — USD per million tokens (input, output).
    "anthropic:claude-opus-4-7": (15.0, 75.0),
    "anthropic:claude-sonnet-4-6": (3.0, 15.0),
    "anthropic:claude-haiku-4-5": (1.0, 5.0),
    # OpenAI — USD per million tokens (input, output).
    "openai:gpt-5": (1.25, 10.0),
    "openai:gpt-5-mini": (0.25, 2.0),
    "openai:gpt-5-nano": (0.05, 0.40),
    "openai:gpt-4.1": (2.0, 8.0),
    "openai:gpt-4.1-mini": (0.40, 1.60),
    "openai:gpt-4o": (2.50, 10.0),
    "openai:gpt-4o-mini": (0.15, 0.60),
}
"""Per-prefixed-model rate table (USD per million tokens)."""

_DEFAULT_RATE: Final[tuple[float, float]] = (15.0, 75.0)
"""Fallback rate (top-tier) for models not in :data:`_RATE_TABLE`."""

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
        cost_usd: Estimated USD cost of the underlying API call.
        model_id: The full prefixed model id the judge ran against
            (e.g. ``"anthropic:claude-haiku-4-5"``).
    """

    passed: bool
    reasoning: str
    cost_usd: float
    model_id: str


def _split_provider(model_id: str) -> tuple[JudgeProvider, str]:
    """Split a prefixed model id into ``(provider, model)``.

    Args:
        model_id: A string of the form ``"<provider>:<model>"``, where
            ``<provider>`` is ``"anthropic"`` or ``"openai"``.

    Returns:
        A ``(provider, model)`` tuple with the provider prefix stripped.

    Raises:
        ValueError: When the prefix is missing or the provider is not
            recognized.
    """
    head, sep, tail = model_id.partition(":")
    if not sep or not tail:
        msg = (
            f"--capture-judge-model {model_id!r}: must be "
            "'anthropic:<id>' or 'openai:<id>'"
        )
        raise ValueError(msg)
    if head == "anthropic":
        return "anthropic", tail
    if head == "openai":
        return "openai", tail
    msg = (
        f"--capture-judge-model {model_id!r}: unknown provider {head!r}; "
        "must be 'anthropic' or 'openai'"
    )
    raise ValueError(msg)


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


def _compute_cost(prefixed_model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = _RATE_TABLE.get(prefixed_model, _DEFAULT_RATE)
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0


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


def _judge_question_text(judge_prompt: str) -> str:
    """Final user-facing question appended after the screenshot/a11y blocks."""
    return (
        f"Rubric question:\n{judge_prompt}\n\n"
        "Decide whether the storefront exposes the affordance described "
        "above. You are looking at static page captures — judge structural "
        "presence, not interaction. Respond with a single-line JSON object "
        'exactly of the form {"passed": <true|false>, "reasoning": '
        '"<one short sentence>"}. Do not wrap the response in Markdown.'
    )


# --------------------------------------------------------------------------- #
# Anthropic provider.
# --------------------------------------------------------------------------- #


def _encode_image_anthropic(path: Path) -> dict[str, object]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": data,
        },
    }


def _build_content_anthropic(
    captures: tuple[PageCapture, ...],
    bundle_root: Path,
    judge_prompt: str,
) -> list[dict[str, object]]:
    """Assemble the Anthropic Messages content list for one capture-judge call."""
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
        content.append(_encode_image_anthropic(screenshot_path))
        content.append(
            {
                "type": "text",
                "text": (
                    f"{capture.page_ref} accessibility tree:\n```json\n"
                    f"{_read_a11y_text(a11y_path)}\n```"
                ),
            }
        )
    content.append({"type": "text", "text": _judge_question_text(judge_prompt)})
    return content


def _extract_text_anthropic(message: object) -> str:
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


async def _messages_create_with_retry_anthropic(
    client: object,
    *,
    model: str,
    max_tokens: int,
    messages: list[dict[str, object]],
) -> object:
    """Anthropic ``messages.create`` with bounded exponential-backoff retry.

    Retries on 429 / transient transport errors / 5xx; other 4xx errors
    propagate immediately so we don't paper over real misconfiguration.
    """
    from anthropic import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        RateLimitError,
    )

    last_exc: BaseException | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return await client.messages.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportAttributeAccessIssue]
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


async def _run_anthropic(
    captures: tuple[PageCapture, ...],
    bundle_root: Path,
    judge_prompt: str,
    *,
    prefixed_model: str,
    bare_model: str,
    client: object | None,
) -> JudgeVerdict:
    """Issue one Anthropic Messages call over a bundle slice."""
    if client is None:
        from anthropic import AsyncAnthropic

        load_agent_env()
        require_credentials("anthropic")
        client = AsyncAnthropic()

    content = _build_content_anthropic(captures, bundle_root, judge_prompt)
    response = await _messages_create_with_retry_anthropic(
        client,
        model=bare_model,
        max_tokens=_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": content}],
    )

    raw = _extract_text_anthropic(response)
    passed, reasoning, _fallback = _parse_verdict(raw)

    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cost_usd = _compute_cost(prefixed_model, input_tokens, output_tokens)

    return JudgeVerdict(
        passed=passed,
        reasoning=reasoning,
        cost_usd=cost_usd,
        model_id=prefixed_model,
    )


# --------------------------------------------------------------------------- #
# OpenAI provider.
# --------------------------------------------------------------------------- #


def _encode_image_openai(path: Path) -> dict[str, object]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{data}"},
    }


def _build_content_openai(
    captures: tuple[PageCapture, ...],
    bundle_root: Path,
    judge_prompt: str,
) -> list[dict[str, object]]:
    """Assemble the OpenAI Chat Completions content list."""
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
        content.append(_encode_image_openai(screenshot_path))
        content.append(
            {
                "type": "text",
                "text": (
                    f"{capture.page_ref} accessibility tree:\n```json\n"
                    f"{_read_a11y_text(a11y_path)}\n```"
                ),
            }
        )
    content.append({"type": "text", "text": _judge_question_text(judge_prompt)})
    return content


def _extract_text_openai(response: object) -> str:
    choices: object = getattr(response, "choices", None) or []
    if not isinstance(choices, list):
        return ""
    if not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    # Some SDK versions return a list of content parts.
    if isinstance(content, list):
        out: list[str] = []
        parts: list[object] = list(content)  # pyright: ignore[reportUnknownArgumentType]
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                out.append(text)
        return "\n".join(out).strip()
    return ""


async def _chat_completions_create_with_retry_openai(
    client: object,
    *,
    model: str,
    max_completion_tokens: int,
    messages: list[dict[str, object]],
) -> object:
    """OpenAI ``chat.completions.create`` with bounded retry on transient errors.

    Uses ``max_completion_tokens`` (not the deprecated ``max_tokens``)
    so the call is compatible with gpt-5 / o-series models, which
    reject ``max_tokens`` outright.
    """
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        RateLimitError,
    )

    last_exc: BaseException | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return await client.chat.completions.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportAttributeAccessIssue]
                model=model,
                max_completion_tokens=max_completion_tokens,
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


async def _run_openai(
    captures: tuple[PageCapture, ...],
    bundle_root: Path,
    judge_prompt: str,
    *,
    prefixed_model: str,
    bare_model: str,
    client: object | None,
) -> JudgeVerdict:
    """Issue one OpenAI Chat Completions call over a bundle slice."""
    if client is None:
        from openai import AsyncOpenAI

        load_agent_env()
        require_credentials("openai")
        client = AsyncOpenAI()

    content = _build_content_openai(captures, bundle_root, judge_prompt)
    response = await _chat_completions_create_with_retry_openai(
        client,
        model=bare_model,
        max_completion_tokens=_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": content}],
    )

    raw = _extract_text_openai(response)
    passed, reasoning, _fallback = _parse_verdict(raw)

    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    cost_usd = _compute_cost(prefixed_model, input_tokens, output_tokens)

    return JudgeVerdict(
        passed=passed,
        reasoning=reasoning,
        cost_usd=cost_usd,
        model_id=prefixed_model,
    )


# --------------------------------------------------------------------------- #
# Public dispatcher.
# --------------------------------------------------------------------------- #


@contextlib.asynccontextmanager
async def open_judge_client(model: str) -> AsyncIterator[object]:
    """Open one provider SDK client for the lifetime of a target's eval.

    The async HTTP pool inside ``AsyncAnthropic`` / ``AsyncOpenAI`` must
    be closed on the same event loop that opened it; otherwise the GC
    finalizer fires after :func:`asyncio.run` has torn down the loop and
    raises ``RuntimeError('Event loop is closed')``. Constructing the
    client per :func:`run_capture_judge` call inside an
    :func:`asyncio.run`-driven CLI leaks one such client per call, so we
    surface the lifecycle to the caller as an async context manager.

    Args:
        model: Provider-prefixed model id (``"anthropic:<id>"`` or
            ``"openai:<id>"``). Used only to pick the right SDK class.

    Yields:
        A fully-constructed ``AsyncAnthropic`` or ``AsyncOpenAI``
        instance. Pass it to :func:`run_capture_judge` via the
        ``client`` keyword argument.

    Raises:
        ValueError: When ``model`` is missing the provider prefix or
            specifies an unknown provider.
        AgentEnvError: When required credentials are absent.
    """
    provider, _ = _split_provider(model)
    load_agent_env()
    require_credentials(provider)
    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        async with AsyncAnthropic() as client:
            yield client
        return
    from openai import AsyncOpenAI

    async with AsyncOpenAI() as client:
        yield client


async def run_capture_judge(
    captures: tuple[PageCapture, ...],
    bundle_root: Path,
    judge_prompt: str,
    *,
    model: str,
    client: object | None = None,
) -> JudgeVerdict:
    """Issue one capture-judge call, dispatched by the model's provider prefix.

    For each applicable :class:`PageCapture` we attach the screenshot
    and the aria-snapshot JSON; we then ask the judge the rubric's
    structural-affordance question and parse the response into the
    closed :class:`JudgeVerdict` shape.

    When **every** capture in ``captures`` has ``applicable=False``,
    the function short-circuits with
    ``JudgeVerdict(passed=False, reasoning="bundle pages unavailable",
    cost_usd=0.0, model_id=model)`` — **no provider call is issued**.

    Args:
        captures: Bundle slice the rubric entry asked for, in
            :data:`PageRef` order. ``applicable=False`` rows are
            dropped from the prompt; an entirely-inapplicable slice
            short-circuits.
        bundle_root: Directory under which the bundle's per-page files
            live (typically ``evidence_root / "_bundle"``).
        judge_prompt: The rubric entry's
            ``CaptureJudgeTask.judge_prompt`` verbatim.
        model: The full prefixed model id, e.g.
            ``"anthropic:claude-haiku-4-5"`` or ``"openai:gpt-4o-mini"``.
        client: Optional pre-built provider client; tests inject a stub
            here. ``None`` constructs a client lazily so the module
            stays import-safe.

    Returns:
        A populated :class:`JudgeVerdict`. ``model_id`` is the full
        prefixed string for traceability.

    Raises:
        ValueError: When ``model`` is missing the provider prefix or
            specifies an unknown provider.
    """
    provider, bare_model = _split_provider(model)

    applicable = tuple(c for c in captures if c.applicable)
    if not applicable:
        return JudgeVerdict(
            passed=False,
            reasoning="bundle pages unavailable",
            cost_usd=0.0,
            model_id=model,
        )

    if provider == "anthropic":
        return await _run_anthropic(
            applicable,
            bundle_root,
            judge_prompt,
            prefixed_model=model,
            bare_model=bare_model,
            client=client,
        )
    return await _run_openai(
        applicable,
        bundle_root,
        judge_prompt,
        prefixed_model=model,
        bare_model=bare_model,
        client=client,
    )
