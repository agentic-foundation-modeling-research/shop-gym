"""Unit tests for :mod:`shop_arena.util._llm` (M2 task).

Covers the M2 contract for ``llm.py``:

* prefix-based dispatch routing (``claude-*`` → Anthropic, ``gpt-*`` /
  ``o1*`` / ``o3*`` / ``o4*`` → OpenAI, anything else raises),
* missing-credential failures surface as :class:`LLMConfigError`,
* text-only model deny list raises before the SDK is constructed,
* :class:`_AnthropicVisionClient` issues a forced tool-use request and
  returns the tool input as :attr:`VisionResponse.parsed`,
* :class:`_OpenAIVisionClient` issues a json_schema request and JSON-decodes
  the assistant message,
* malformed responses surface as ``parse_errors`` instead of exceptions.

All tests run hermetically by injecting a fake SDK via ``client_factory``;
no live HTTP is performed.
"""

from __future__ import annotations

import dataclasses
import json
from base64 import b64decode
from dataclasses import dataclass, field
from typing import Any

import pytest

from shop_arena.util._llm import (
    DEFAULT_RUBRIC_TEMPERATURE,
    LLMConfigError,
    LLMVisionClient,
    VisionResponse,
    _AnthropicVisionClient,
    _OpenAIVisionClient,
    build_default_client,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _ToolUseBlock:
    """Mimic :class:`anthropic.types.ToolUseBlock` for response parsing."""

    type: str = "tool_use"
    name: str = "emit_rubric"
    input: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {"type": self.type, "name": self.name, "input": dict(self.input)}


@dataclass
class _TextBlock:
    """Mimic an Anthropic text content block."""

    type: str = "text"
    text: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text}


@dataclass
class _AnthropicMessage:
    """Mimic :class:`anthropic.types.Message` enough for ``_parse_anthropic_message``."""

    content: list[Any]


class _FakeAnthropicMessages:
    def __init__(self, response: _AnthropicMessage) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _AnthropicMessage:
        self.calls.append(kwargs)
        return self.response


class _FakeAnthropicClient:
    def __init__(self, response: _AnthropicMessage, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.messages = _FakeAnthropicMessages(response)


@dataclass
class _OpenAIMessage:
    content: str


@dataclass
class _OpenAIChoice:
    message: _OpenAIMessage


@dataclass
class _OpenAICompletion:
    choices: list[_OpenAIChoice]


class _FakeOpenAIChatCompletions:
    def __init__(self, response: _OpenAICompletion) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _OpenAICompletion:
        self.calls.append(kwargs)
        return self.response


class _FakeOpenAIChat:
    def __init__(self, response: _OpenAICompletion) -> None:
        self.completions = _FakeOpenAIChatCompletions(response)


class _FakeOpenAIClient:
    def __init__(self, response: _OpenAICompletion, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.chat = _FakeOpenAIChat(response)


_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-payload"
_RUBRIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nav": {"type": "integer", "minimum": 0},
        "footer": {"type": "integer", "minimum": 0},
    },
    "required": ["nav", "footer"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Dispatch routing
# ---------------------------------------------------------------------------


def test_build_default_client_routes_claude_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """``claude-*`` ids dispatch to the Anthropic implementation."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub")
    client = build_default_client("claude-sonnet-4-6")
    assert isinstance(client, _AnthropicVisionClient)
    assert client.model == "claude-sonnet-4-6"


def test_build_default_client_routes_gpt_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """``gpt-*`` ids dispatch to the OpenAI implementation."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    client = build_default_client("gpt-4o")
    assert isinstance(client, _OpenAIVisionClient)
    assert client.model == "gpt-4o"


@pytest.mark.parametrize("model", ["o1", "o3-pro", "o4-mini-2025", "chatgpt-4o-latest"])
def test_build_default_client_routes_reasoning_models_to_openai(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    """OpenAI reasoning families (``o1``/``o3``/``o4``) route to OpenAI."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    client = build_default_client(model)
    assert isinstance(client, _OpenAIVisionClient)


def test_build_default_client_rejects_unknown_provider() -> None:
    """Unknown prefixes raise :class:`LLMConfigError` rather than guessing."""
    with pytest.raises(LLMConfigError, match="cannot infer provider"):
        build_default_client("mistral-large-latest")


def test_build_default_client_rejects_empty_model() -> None:
    """An empty model id is rejected explicitly."""
    with pytest.raises(LLMConfigError, match="non-empty"):
        build_default_client("")


def test_build_default_client_implements_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returned clients satisfy the :class:`LLMVisionClient` Protocol."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub")
    client = build_default_client("claude-sonnet-4-6")
    assert isinstance(client, LLMVisionClient)


# ---------------------------------------------------------------------------
# Vision-support deny list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "gpt-3.5-turbo",
        "gpt-4-0613",
        "o1-mini",
        "claude-2.1",
        "claude-instant-1.2",
    ],
)
def test_build_default_client_rejects_text_only_models(model: str) -> None:
    """Text-only models surface a configuration error, not a silent fallback."""
    with pytest.raises(LLMConfigError, match="does not support vision"):
        build_default_client(model)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_anthropic_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing ``ANTHROPIC_API_KEY`` surfaces at :meth:`call`, not at construction."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = _AnthropicVisionClient("claude-sonnet-4-6")
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        client.call(prompt="hi", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)


def test_openai_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing ``OPENAI_API_KEY`` surfaces at :meth:`call`, not at construction."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _OpenAIVisionClient("gpt-4o")
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        client.call(prompt="hi", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)


def test_anthropic_client_accepts_explicit_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``api_key=`` argument bypasses the env var entirely."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = _AnthropicMessage(content=[_ToolUseBlock(input={"nav": 1, "footer": 2})])
    fake = _FakeAnthropicClient(response)
    client = _AnthropicVisionClient(
        "claude-sonnet-4-6",
        api_key="sk-ant-explicit",
        client_factory=lambda **kw: (fake.__init__(response, **kw), fake)[1],  # type: ignore[func-returns-value]
    )
    out = client.call(prompt="hi", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)
    assert out.parsed == {"nav": 1, "footer": 2}
    assert fake.init_kwargs == {"api_key": "sk-ant-explicit"}


# ---------------------------------------------------------------------------
# Anthropic call shape + response parsing
# ---------------------------------------------------------------------------


def test_anthropic_call_builds_forced_tool_use_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic ``messages.create`` receives the forced tool-use payload."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub")
    response = _AnthropicMessage(content=[_ToolUseBlock(input={"nav": 3, "footer": 1})])
    fake_client = _FakeAnthropicClient(response)

    client = _AnthropicVisionClient(
        "claude-sonnet-4-6",
        client_factory=lambda **_: fake_client,
    )
    out = client.call(
        prompt="categorise this screenshot",
        images=(_PNG_BYTES,),
        schema=_RUBRIC_SCHEMA,
        temperature=0.0,
    )

    assert out.parsed == {"nav": 3, "footer": 1}
    assert json.loads(out.raw_response) == {"footer": 1, "nav": 3}
    assert out.parse_errors == ()

    [call] = fake_client.messages.calls
    assert call["model"] == "claude-sonnet-4-6"
    assert call["temperature"] == 0.0
    assert call["tool_choice"] == {"type": "tool", "name": "emit_rubric"}
    [tool] = call["tools"]
    assert tool["name"] == "emit_rubric"
    assert tool["input_schema"] == _RUBRIC_SCHEMA
    [user_msg] = call["messages"]
    assert user_msg["role"] == "user"
    image_block, text_block = user_msg["content"]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/png"
    assert b64decode(image_block["source"]["data"]) == _PNG_BYTES
    assert text_block == {"type": "text", "text": "categorise this screenshot"}


def test_anthropic_response_without_tool_use_is_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response that omits the tool_use block surfaces as ``parse_errors``."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub")
    response = _AnthropicMessage(content=[_TextBlock(text="i declined to use the tool")])
    fake_client = _FakeAnthropicClient(response)

    client = _AnthropicVisionClient("claude-sonnet-4-6", client_factory=lambda **_: fake_client)
    out = client.call(prompt="x", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)

    assert out.parsed is None
    assert out.parse_errors == ("anthropic response contained no tool_use block",)
    # raw_response captures the model's text output for audit
    assert "i declined" in out.raw_response


# ---------------------------------------------------------------------------
# OpenAI call shape + response parsing
# ---------------------------------------------------------------------------


def test_openai_call_builds_json_schema_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI ``chat.completions.create`` receives the json_schema payload."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content='{"nav": 4, "footer": 0}'))],
    )
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient("gpt-4o", client_factory=lambda **_: fake_client)
    out = client.call(prompt="categorise", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)

    assert out.parsed == {"nav": 4, "footer": 0}
    assert out.raw_response == '{"nav": 4, "footer": 0}'
    assert out.parse_errors == ()

    [call] = fake_client.chat.completions.calls
    assert call["model"] == "gpt-4o"
    assert call["temperature"] == 0.0
    rf = call["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "rubric_response"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == _RUBRIC_SCHEMA
    [user_msg] = call["messages"]
    image_block, text_block = user_msg["content"]
    assert image_block["type"] == "image_url"
    assert image_block["image_url"]["url"].startswith("data:image/png;base64,")
    assert text_block == {"type": "text", "text": "categorise"}


def test_openai_invalid_json_response_is_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-JSON assistant content surfaces as a ``parse_errors`` entry."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content="not json at all"))],
    )
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient("gpt-4o", client_factory=lambda **_: fake_client)
    out = client.call(prompt="x", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)

    assert out.parsed is None
    assert out.raw_response == "not json at all"
    assert len(out.parse_errors) == 1
    assert "not valid JSON" in out.parse_errors[0]


def test_openai_empty_choices_is_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty ``choices`` list is treated as a structured parse failure."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(choices=[])
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient("gpt-4o", client_factory=lambda **_: fake_client)
    out = client.call(prompt="x", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)

    assert out.parsed is None
    assert out.parse_errors == ("openai completion contained no choices",)


def test_openai_non_object_root_is_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JSON array at the root is rejected; the rubric schema requires an object."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content="[1, 2, 3]"))],
    )
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient("gpt-4o", client_factory=lambda **_: fake_client)
    out = client.call(prompt="x", images=(_PNG_BYTES,), schema=_RUBRIC_SCHEMA)

    assert out.parsed is None
    assert out.parse_errors == ("openai response root is list, expected object",)


# ---------------------------------------------------------------------------
# Temperature handling for fixed-temperature OpenAI families.
# ---------------------------------------------------------------------------


def test_default_rubric_temperature_is_zero() -> None:
    """Spec §5.3 anchors the rubric on ``temperature 0`` where supported."""
    assert DEFAULT_RUBRIC_TEMPERATURE == 0.0


@pytest.mark.parametrize(
    "model",
    [
        "o1",
        "o1-2024-12-17",
        "o3-pro",
        "o4-mini",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-2025-08-07",
    ],
)
def test_openai_call_omits_temperature_for_fixed_temperature_models(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    """Reasoning + ``gpt-5`` families reject explicit ``temperature``; we drop it."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content='{"nav": 1, "footer": 0}'))],
    )
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient(model, client_factory=lambda **_: fake_client)
    out = client.call(
        prompt="x",
        images=(_PNG_BYTES,),
        schema=_RUBRIC_SCHEMA,
        temperature=DEFAULT_RUBRIC_TEMPERATURE,
    )

    assert out.parsed == {"nav": 1, "footer": 0}
    [call] = fake_client.chat.completions.calls
    assert call["model"] == model
    assert "temperature" not in call
    # Other call kwargs unchanged — only ``temperature`` is omitted.
    assert call["max_completion_tokens"] == 4096
    assert call["response_format"]["type"] == "json_schema"


def test_openai_call_keeps_temperature_for_gpt_4o(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-reasoning families still receive the explicit ``temperature`` kwarg."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content='{"nav": 1, "footer": 0}'))],
    )
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient("gpt-4o-2024-08-06", client_factory=lambda **_: fake_client)
    client.call(
        prompt="x",
        images=(_PNG_BYTES,),
        schema=_RUBRIC_SCHEMA,
        temperature=DEFAULT_RUBRIC_TEMPERATURE,
    )
    [call] = fake_client.chat.completions.calls
    assert call["temperature"] == 0.0


# ---------------------------------------------------------------------------
# Text-only call path (call_text)
# ---------------------------------------------------------------------------


def test_anthropic_call_text_omits_image_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """``call_text`` issues the same forced tool-use payload with no image content."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub")
    response = _AnthropicMessage(content=[_ToolUseBlock(input={"nav": 7, "footer": 3})])
    fake_client = _FakeAnthropicClient(response)

    client = _AnthropicVisionClient(
        "claude-sonnet-4-6",
        client_factory=lambda **_: fake_client,
    )
    out = client.call_text(
        prompt="classify these paths",
        schema=_RUBRIC_SCHEMA,
        temperature=0.0,
    )

    assert out.parsed == {"nav": 7, "footer": 3}
    assert out.parse_errors == ()

    [call] = fake_client.messages.calls
    assert call["model"] == "claude-sonnet-4-6"
    assert call["temperature"] == 0.0
    assert call["tool_choice"] == {"type": "tool", "name": "emit_rubric"}
    [tool] = call["tools"]
    assert tool["input_schema"] == _RUBRIC_SCHEMA
    [user_msg] = call["messages"]
    assert user_msg["role"] == "user"
    # The user content must be a single text block — no image entries.
    assert user_msg["content"] == [{"type": "text", "text": "classify these paths"}]


def test_openai_call_text_omits_image_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """``call_text`` issues the same json_schema payload with no image content."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content='{"nav": 2, "footer": 5}'))],
    )
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient("gpt-4o", client_factory=lambda **_: fake_client)
    out = client.call_text(
        prompt="classify",
        schema=_RUBRIC_SCHEMA,
        temperature=0.0,
    )

    assert out.parsed == {"nav": 2, "footer": 5}
    assert out.parse_errors == ()

    [call] = fake_client.chat.completions.calls
    assert call["model"] == "gpt-4o"
    assert call["temperature"] == 0.0
    rf = call["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == _RUBRIC_SCHEMA
    [user_msg] = call["messages"]
    # The user content must be a single text block — no image_url entries.
    assert user_msg["content"] == [{"type": "text", "text": "classify"}]


def test_openai_call_text_drops_temperature_for_fixed_temperature_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``call_text`` honours the same fixed-temperature drop as :meth:`call`."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    completion = _OpenAICompletion(
        choices=[_OpenAIChoice(message=_OpenAIMessage(content='{"nav": 0, "footer": 0}'))],
    )
    fake_client = _FakeOpenAIClient(completion)

    client = _OpenAIVisionClient("gpt-5", client_factory=lambda **_: fake_client)
    client.call_text(prompt="x", schema=_RUBRIC_SCHEMA, temperature=DEFAULT_RUBRIC_TEMPERATURE)

    [call] = fake_client.chat.completions.calls
    assert "temperature" not in call


# ---------------------------------------------------------------------------
# VisionResponse contract
# ---------------------------------------------------------------------------


def test_vision_response_is_frozen() -> None:
    """:class:`VisionResponse` is immutable — its values feed straight into artifacts."""
    response = VisionResponse(parsed={"nav": 1}, raw_response="{}", parse_errors=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.parsed = {"nav": 2}  # type: ignore[misc]
