"""Tests for `shop_probe.agent.judge` provider dispatch.

Stubs the Anthropic and OpenAI async clients so the test runs without
network access. Asserts that ``run_capture_judge``:

* dispatches to the Anthropic Messages API when ``model`` starts with
  ``"anthropic:"``;
* dispatches to OpenAI Chat Completions when ``model`` starts with
  ``"openai:"``, encoding screenshots as ``image_url`` data URIs and
  computing cost from ``prompt_tokens`` / ``completion_tokens``;
* rejects an unprefixed model id with a ``ValueError`` that names the
  expected format.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from shop_probe.agent.judge import JudgeVerdict, run_capture_judge
from shop_probe.capture.bundle import PageCapture


# --------------------------------------------------------------------------- #
# Fixtures: a one-page applicable bundle slice on disk.
# --------------------------------------------------------------------------- #


def _write_bundle(tmp_path: Path) -> tuple[Path, tuple[PageCapture, ...]]:
    """Materialise a one-page bundle slice and return ``(bundle_root, captures)``."""
    bundle_root = tmp_path / "_bundle"
    page_dir = bundle_root / "home"
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (page_dir / "a11y.json").write_text('{"role": "WebArea"}', encoding="utf-8")
    capture = PageCapture(
        page_ref="home",
        url="http://localhost:4000/",
        screenshot_rel="home/screenshot.png",
        accessibility_rel="home/a11y.json",
        applicable=True,
    )
    return bundle_root, (capture,)


# --------------------------------------------------------------------------- #
# Anthropic stub.
# --------------------------------------------------------------------------- #


@dataclass
class _AnthropicTextBlock:
    text: str
    type: str = "text"


@dataclass
class _AnthropicMessage:
    content: list[_AnthropicTextBlock]
    usage: Any


@dataclass
class _AnthropicUsage:
    input_tokens: int
    output_tokens: int


class _StubAnthropicMessages:
    def __init__(self, response: _AnthropicMessage) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _AnthropicMessage:
        self.calls.append(kwargs)
        return self._response


class _StubAnthropicClient:
    def __init__(self, response: _AnthropicMessage) -> None:
        self.messages = _StubAnthropicMessages(response)


# --------------------------------------------------------------------------- #
# OpenAI stub.
# --------------------------------------------------------------------------- #


@dataclass
class _OpenAIMessage:
    content: str


@dataclass
class _OpenAIChoice:
    message: _OpenAIMessage


@dataclass
class _OpenAIUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _OpenAIResponse:
    choices: list[_OpenAIChoice]
    usage: _OpenAIUsage


class _StubOpenAICompletions:
    def __init__(self, response: _OpenAIResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _OpenAIResponse:
        self.calls.append(kwargs)
        return self._response


class _StubOpenAIChat:
    def __init__(self, response: _OpenAIResponse) -> None:
        self.completions = _StubOpenAICompletions(response)


class _StubOpenAIClient:
    def __init__(self, response: _OpenAIResponse) -> None:
        self.chat = _StubOpenAIChat(response)


# --------------------------------------------------------------------------- #
# Tests.
# --------------------------------------------------------------------------- #


def test_run_capture_judge_dispatches_to_anthropic(tmp_path: Path) -> None:
    bundle_root, captures = _write_bundle(tmp_path)
    response = _AnthropicMessage(
        content=[_AnthropicTextBlock(text='{"passed": true, "reasoning": "ok"}')],
        usage=_AnthropicUsage(input_tokens=1000, output_tokens=50),
    )
    client = _StubAnthropicClient(response)

    verdict = asyncio.run(
        run_capture_judge(
            captures,
            bundle_root,
            "Is the cart icon visible?",
            model="anthropic:claude-haiku-4-5",
            client=client,
        )
    )

    assert isinstance(verdict, JudgeVerdict)
    assert verdict.passed is True
    assert verdict.reasoning == "ok"
    assert verdict.model_id == "anthropic:claude-haiku-4-5"
    # Cost = (1000 * 1.0 + 50 * 5.0) / 1e6 = 0.00125
    assert verdict.cost_usd == pytest.approx(0.00125)

    # The model id passed to the SDK is the bare id, not the prefixed one.
    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    # Anthropic image blocks use the {"type": "image", "source": {...}} shape.
    user_msg = call["messages"][0]
    image_blocks = [
        b for b in user_msg["content"] if isinstance(b, dict) and b.get("type") == "image"
    ]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["type"] == "base64"


def test_run_capture_judge_dispatches_to_openai(tmp_path: Path) -> None:
    bundle_root, captures = _write_bundle(tmp_path)
    response = _OpenAIResponse(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content='{"passed": false, "reasoning": "no"}'))],
        usage=_OpenAIUsage(prompt_tokens=2000, completion_tokens=100),
    )
    client = _StubOpenAIClient(response)

    verdict = asyncio.run(
        run_capture_judge(
            captures,
            bundle_root,
            "Is the cart icon visible?",
            model="openai:gpt-4o-mini",
            client=client,
        )
    )

    assert verdict.passed is False
    assert verdict.reasoning == "no"
    assert verdict.model_id == "openai:gpt-4o-mini"
    # Cost = (2000 * 0.15 + 100 * 0.60) / 1e6 = 0.00036
    assert verdict.cost_usd == pytest.approx(0.00036)

    assert len(client.chat.completions.calls) == 1
    call = client.chat.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    # OpenAI image blocks use {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}.
    user_msg = call["messages"][0]
    image_blocks = [
        b for b in user_msg["content"] if isinstance(b, dict) and b.get("type") == "image_url"
    ]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_run_capture_judge_rejects_unprefixed_model(tmp_path: Path) -> None:
    bundle_root, captures = _write_bundle(tmp_path)
    with pytest.raises(ValueError, match="anthropic:<id>"):
        asyncio.run(
            run_capture_judge(
                captures,
                bundle_root,
                "Is the cart icon visible?",
                model="claude-haiku-4-5",
            )
        )


def test_run_capture_judge_rejects_unknown_provider(tmp_path: Path) -> None:
    bundle_root, captures = _write_bundle(tmp_path)
    with pytest.raises(ValueError, match="unknown provider"):
        asyncio.run(
            run_capture_judge(
                captures,
                bundle_root,
                "Is the cart icon visible?",
                model="cohere:command-r",
            )
        )


def test_run_capture_judge_short_circuits_when_all_inapplicable(tmp_path: Path) -> None:
    capture = PageCapture(
        page_ref="home",
        url="http://localhost:4000/",
        screenshot_rel=None,
        accessibility_rel=None,
        applicable=False,
        notes="navigation timeout",
    )
    verdict = asyncio.run(
        run_capture_judge(
            (capture,),
            tmp_path,
            "Is the cart icon visible?",
            model="anthropic:claude-haiku-4-5",
        )
    )
    assert verdict.passed is False
    assert verdict.reasoning == "bundle pages unavailable"
    assert verdict.cost_usd == 0.0
    assert verdict.model_id == "anthropic:claude-haiku-4-5"
