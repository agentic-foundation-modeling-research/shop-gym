"""Single-modality judge call.

For each ``info_slot`` / ``control_slot`` rubric entry, the dispatcher
calls :func:`judge_slot` once **per modality** (a11y JSON or screenshot,
never both at once). The response is parsed into a closed
:class:`shop_probe.report.SlotVerdict`.

Provider routing follows the prefix on the model id: ``anthropic:<id>``
through Anthropic Messages, ``openai:<id>`` through OpenAI Chat
Completions. Cost computation projects token usage to USD via a per-model
rate table.

The module is import-safe: provider SDK clients are constructed lazily.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import random
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

from shop_probe.capture.bundle import PageCapture
from shop_probe.judge.env import (
    JudgeProvider,
    load_agent_env,
    require_credentials,
)
from shop_probe.report import SlotVerdict
from shop_probe.rubric.schema import Modality

_RATE_TABLE: Final[dict[str, tuple[float, float]]] = {
    "anthropic:claude-opus-4-7": (15.0, 75.0),
    "anthropic:claude-sonnet-4-6": (3.0, 15.0),
    "anthropic:claude-haiku-4-5": (1.0, 5.0),
    "openai:gpt-5": (1.25, 10.0),
    "openai:gpt-5-mini": (0.25, 2.0),
    "openai:gpt-5-nano": (0.05, 0.40),
    "openai:gpt-4.1": (2.0, 8.0),
    "openai:gpt-4.1-mini": (0.40, 1.60),
    "openai:gpt-4o": (2.50, 10.0),
    "openai:gpt-4o-mini": (0.15, 0.60),
}
"""USD per million tokens (input, output)."""

_DEFAULT_RATE: Final[tuple[float, float]] = (15.0, 75.0)

_MAX_OUTPUT_TOKENS: Final[int] = 512
_RETRY_MAX_ATTEMPTS: Final[int] = 8
_RETRY_BASE_DELAY_S: Final[float] = 2.0
_RETRY_MAX_DELAY_S: Final[float] = 120.0

_JSON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"\{.*?\}", re.DOTALL)


def split_provider(model_id: str) -> tuple[JudgeProvider, str]:
    """Split a prefixed model id into ``(provider, model)``.

    Args:
        model_id: ``"<provider>:<model>"`` where provider is
            ``"anthropic"`` or ``"openai"``.

    Raises:
        ValueError: When the prefix is missing or unrecognized.
    """
    head, sep, tail = model_id.partition(":")
    if not sep or not tail:
        msg = (
            f"--judge-model {model_id!r}: must be 'anthropic:<id>' or 'openai:<id>'"
        )
        raise ValueError(msg)
    if head == "anthropic":
        return "anthropic", tail
    if head == "openai":
        return "openai", tail
    msg = f"--judge-model {model_id!r}: unknown provider {head!r}"
    raise ValueError(msg)


@contextlib.asynccontextmanager
async def open_judge_client(model: str) -> AsyncIterator[object]:
    """Open one provider SDK client for the lifetime of a target's eval.

    The async HTTP pool inside ``AsyncAnthropic`` / ``AsyncOpenAI`` must
    be closed on the same event loop that opened it.
    """
    provider, _ = split_provider(model)
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


def _judge_question_text(prompt_body: str) -> str:
    """Wrap the rubric prompt body in the closing JSON instruction."""
    return (
        f"{prompt_body}\n\n"
        "Decide whether the storefront exposes the affordance described "
        "above. Respond with a single-line JSON object exactly of the form "
        '{"present": <true|false>, "name_used": "<text or null>", '
        '"evidence_locator": "<text or null>", "reasoning": "<one short sentence>"}. '
        "Do not wrap the response in Markdown."
    )


def _parse_verdict(
    text: str, *, judge_model: str, cost_usd: float
) -> SlotVerdict:
    """Parse a judge response into a :class:`SlotVerdict`."""
    candidates: list[str] = [text, *_JSON_BLOCK_RE.findall(text)]
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "present" in obj:
            obj_dict: dict[object, object] = obj  # pyright: ignore[reportUnknownVariableType]
            present = bool(obj_dict["present"])
            return SlotVerdict(
                present=present,
                name_used=_str_or_none(obj_dict.get("name_used")),
                evidence_locator=_str_or_none(obj_dict.get("evidence_locator")),
                reasoning=_str_or_none(obj_dict.get("reasoning")),
                judge_model=judge_model,
                judge_cost_usd=cost_usd,
            )
    return SlotVerdict(
        present=False,
        name_used=None,
        evidence_locator=None,
        reasoning=f"[unparseable judge response] {text.strip()[:200]}",
        judge_model=judge_model,
        judge_cost_usd=cost_usd,
    )


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    return str(value)


# --------------------------------------------------------------------------- #
# Anthropic provider.
# --------------------------------------------------------------------------- #


def _build_content_anthropic(
    capture: PageCapture,
    *,
    bundle_root: Path,
    modality: Modality,
    prompt_body: str,
) -> list[dict[str, object]]:
    """Assemble the Anthropic Messages content list for one modality."""
    content: list[dict[str, object]] = []
    page_label = f"{capture.page_type} ({capture.url})"

    if modality == "screenshot":
        if capture.screenshot_rel is None:
            content.append({"type": "text", "text": f"{page_label} — screenshot unavailable."})
        else:
            data = base64.b64encode(
                (bundle_root / capture.screenshot_rel).read_bytes()
            ).decode("ascii")
            content.append({"type": "text", "text": f"{page_label} — screenshot:"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": data,
                    },
                }
            )
    else:  # a11y
        a11y = ""
        if capture.accessibility_rel is not None:
            try:
                a11y = (bundle_root / capture.accessibility_rel).read_text(
                    encoding="utf-8"
                )
            except OSError:
                a11y = ""
        content.append(
            {
                "type": "text",
                "text": (
                    f"{page_label} — accessibility tree:\n```json\n{a11y}\n```"
                ),
            }
        )

    content.append({"type": "text", "text": _judge_question_text(prompt_body)})
    return content


async def _messages_create_with_retry_anthropic(
    client: object,
    *,
    model: str,
    max_tokens: int,
    messages: list[dict[str, object]],
) -> object:
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


def _extract_text_anthropic(message: object) -> str:
    raw_blocks: object = getattr(message, "content", None) or []
    if not isinstance(raw_blocks, list):
        return ""
    out: list[str] = []
    blocks: list[object] = list(raw_blocks)  # pyright: ignore[reportUnknownArgumentType]
    for block in blocks:
        if getattr(block, "type", None) != "text":
            continue
        text = getattr(block, "text", "")
        if isinstance(text, str):
            out.append(text)
    return "\n".join(out).strip()


async def _judge_anthropic(
    capture: PageCapture,
    *,
    bundle_root: Path,
    modality: Modality,
    prompt_body: str,
    prefixed_model: str,
    bare_model: str,
    client: object,
) -> SlotVerdict:
    content = _build_content_anthropic(
        capture, bundle_root=bundle_root, modality=modality, prompt_body=prompt_body
    )
    response = await _messages_create_with_retry_anthropic(
        client,
        model=bare_model,
        max_tokens=_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": content}],
    )
    raw = _extract_text_anthropic(response)
    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0)
    out_tok = int(getattr(usage, "output_tokens", 0) or 0)
    cost = _compute_cost(prefixed_model, in_tok, out_tok)
    return _parse_verdict(raw, judge_model=prefixed_model, cost_usd=cost)


# --------------------------------------------------------------------------- #
# OpenAI provider.
# --------------------------------------------------------------------------- #


def _build_content_openai(
    capture: PageCapture,
    *,
    bundle_root: Path,
    modality: Modality,
    prompt_body: str,
) -> list[dict[str, object]]:
    content: list[dict[str, object]] = []
    page_label = f"{capture.page_type} ({capture.url})"

    if modality == "screenshot":
        if capture.screenshot_rel is None:
            content.append({"type": "text", "text": f"{page_label} — screenshot unavailable."})
        else:
            data = base64.b64encode(
                (bundle_root / capture.screenshot_rel).read_bytes()
            ).decode("ascii")
            content.append({"type": "text", "text": f"{page_label} — screenshot:"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{data}"},
                }
            )
    else:
        a11y = ""
        if capture.accessibility_rel is not None:
            try:
                a11y = (bundle_root / capture.accessibility_rel).read_text(
                    encoding="utf-8"
                )
            except OSError:
                a11y = ""
        content.append(
            {
                "type": "text",
                "text": (
                    f"{page_label} — accessibility tree:\n```json\n{a11y}\n```"
                ),
            }
        )

    content.append({"type": "text", "text": _judge_question_text(prompt_body)})
    return content


async def _chat_completions_with_retry_openai(
    client: object,
    *,
    model: str,
    max_completion_tokens: int,
    messages: list[dict[str, object]],
) -> object:
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
            if exc.status_code < 500:  # noqa: PLR2004
                raise
            last_exc = exc
            delay = _retry_backoff(attempt)
        if attempt + 1 == _RETRY_MAX_ATTEMPTS:
            break
        await asyncio.sleep(min(delay, _RETRY_MAX_DELAY_S))
    assert last_exc is not None
    raise last_exc


def _extract_text_openai(response: object) -> str:
    choices: object = getattr(response, "choices", None) or []
    if not isinstance(choices, list) or not choices:
        return ""
    choices_list: list[object] = list(choices)  # pyright: ignore[reportUnknownArgumentType]
    first: object = choices_list[0]
    message = getattr(first, "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        out: list[str] = []
        parts: list[object] = list(content)  # pyright: ignore[reportUnknownArgumentType]
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                out.append(text)
        return "\n".join(out).strip()
    return ""


async def _judge_openai(
    capture: PageCapture,
    *,
    bundle_root: Path,
    modality: Modality,
    prompt_body: str,
    prefixed_model: str,
    bare_model: str,
    client: object,
) -> SlotVerdict:
    content = _build_content_openai(
        capture, bundle_root=bundle_root, modality=modality, prompt_body=prompt_body
    )
    response = await _chat_completions_with_retry_openai(
        client,
        model=bare_model,
        max_completion_tokens=_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": content}],
    )
    raw = _extract_text_openai(response)
    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
    out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
    cost = _compute_cost(prefixed_model, in_tok, out_tok)
    return _parse_verdict(raw, judge_model=prefixed_model, cost_usd=cost)


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #


async def judge_slot(
    capture: PageCapture,
    *,
    bundle_root: Path,
    modality: Modality,
    prompt_body: str,
    model: str,
    client: object,
) -> SlotVerdict:
    """Issue one judge call for ``capture`` on ``modality`` and return a verdict.

    When the capture is non-applicable (the underlying page was
    unreachable), the function short-circuits with a
    ``present=False`` verdict explaining the gap — no provider call is
    issued.

    Args:
        capture: One :class:`PageCapture` from the bundle.
        bundle_root: Directory the capture's relative paths resolve under.
        modality: Which modality this judge call sees. The prompt and
            attached payload differ accordingly.
        prompt_body: The rubric entry's prompt text (read from disk by
            the dispatcher).
        model: Provider-prefixed model id, e.g. ``"anthropic:claude-haiku-4-5"``.
        client: Pre-built provider client opened via
            :func:`open_judge_client`.
    """
    if not capture.applicable:
        return SlotVerdict(
            present=False,
            name_used=None,
            evidence_locator=None,
            reasoning=f"page unavailable: {capture.notes or 'unknown'}",
            judge_model=model,
            judge_cost_usd=0.0,
        )

    provider, bare_model = split_provider(model)
    if provider == "anthropic":
        return await _judge_anthropic(
            capture,
            bundle_root=bundle_root,
            modality=modality,
            prompt_body=prompt_body,
            prefixed_model=model,
            bare_model=bare_model,
            client=client,
        )
    return await _judge_openai(
        capture,
        bundle_root=bundle_root,
        modality=modality,
        prompt_body=prompt_body,
        prefixed_model=model,
        bare_model=bare_model,
        client=client,
    )
