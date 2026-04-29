"""Hermetic tests for ``shop_probe.agent.judge.run_completion_judge`` (T3.3).

The judge issues a single Anthropic Messages API call and parses the model
response into a closed :class:`JudgeVerdict`. These tests stub the
:class:`AsyncAnthropic` client to pin three contracts:

* the request body contains both screenshots as non-empty base64 ``image``
  blocks and embeds the inline ``judge_prompt`` verbatim;
* a well-formed JSON verdict parses cleanly and surfaces a ``cost_usd``
  derived from ``usage.input_tokens`` / ``usage.output_tokens``;
* a malformed prose response (no JSON, no ``passed:`` literal) falls back
  to the unparseable branch so callers can flag the degradation in
  ``ProbeOutcome.notes``.

The tests do not touch the network, the live ``anthropic`` client, or any
real screenshots beyond a few PNG header bytes written under ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import pytest

from shop_probe.agent.judge import run_completion_judge

# --------------------------------------------------------------------------- #
# Stubs.
# --------------------------------------------------------------------------- #


class _StubBlock:
    """Minimal Anthropic content-block substitute (text only)."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _StubUsage:
    """Minimal Anthropic ``usage`` substitute reporting only token counts."""

    def __init__(self, *, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _StubMessage:
    """Minimal Anthropic ``Message`` substitute for one ``messages.create`` call."""

    def __init__(
        self,
        *,
        text: str,
        input_tokens: int = 1000,
        output_tokens: int = 50,
    ) -> None:
        self.content = [_StubBlock(text)]
        self.usage = _StubUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class _StubMessages:
    """Records the kwargs passed to ``messages.create``."""

    def __init__(self, response: _StubMessage) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _StubMessage:
        self.calls.append(kwargs)
        return self._response


class _StubClient:
    """Drop-in replacement for :class:`anthropic.AsyncAnthropic`."""

    def __init__(self, response: _StubMessage) -> None:
        self.messages = _StubMessages(response)


def _write_png(path: Path, payload: bytes) -> Path:
    """Persist ``payload`` (with a PNG header) under ``path``."""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload)
    return path


# --------------------------------------------------------------------------- #
# Tests.
# --------------------------------------------------------------------------- #


def test_judge_request_includes_images_and_prompt(tmp_path: Path) -> None:
    """The request carries both base64 image blocks + the rubric prompt verbatim."""
    before = _write_png(tmp_path / "before.png", b"before-bytes")
    after = _write_png(tmp_path / "after.png", b"after-bytes")
    response = _StubMessage(text='{"passed": true, "reasoning": "ok"}')
    client = _StubClient(response)
    judge_prompt = "Did the visible product set narrow between BEFORE and AFTER?"

    asyncio.run(
        run_completion_judge(
            before,
            after,
            "step_00: navigate -> /collections/all",
            judge_prompt,
            client=client,  # type: ignore[arg-type]
        )
    )

    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    # Single user-role message with the layered content list.
    assert call["model"] == "claude-opus-4-7"
    messages = call["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content: list[dict[str, Any]] = messages[0]["content"]

    # Two image blocks; both carry non-empty base64 payloads matching the
    # exact bytes the judge read off disk.
    image_blocks = [b for b in content if b.get("type") == "image"]
    assert len(image_blocks) == 2  # noqa: PLR2004
    expected_before_b64 = base64.b64encode(before.read_bytes()).decode("ascii")
    expected_after_b64 = base64.b64encode(after.read_bytes()).decode("ascii")
    payloads = [b["source"]["data"] for b in image_blocks]
    assert all(len(p) > 0 for p in payloads)
    assert payloads == [expected_before_b64, expected_after_b64]
    assert all(b["source"]["media_type"] == "image/png" for b in image_blocks)

    # The rubric ``judge_prompt`` appears verbatim in one of the text blocks.
    text_bodies = [b.get("text", "") for b in content if b.get("type") == "text"]
    assert any(judge_prompt in body for body in text_bodies)


def test_judge_parses_clean_json_and_reports_cost(tmp_path: Path) -> None:
    """A valid ``{"passed": ..., "reasoning": ...}`` body produces a clean verdict."""
    before = _write_png(tmp_path / "before.png", b"b")
    after = _write_png(tmp_path / "after.png", b"a")
    response = _StubMessage(
        text='{"passed": true, "reasoning": "Product order visibly changed."}',
        input_tokens=1234,
        output_tokens=56,
    )
    client = _StubClient(response)

    verdict = asyncio.run(
        run_completion_judge(
            before,
            after,
            "trajectory text",
            "Did the order change?",
            client=client,  # type: ignore[arg-type]
        )
    )

    assert verdict.passed is True
    assert verdict.reasoning == "Product order visibly changed."
    assert verdict.model_id == "claude-opus-4-7"
    # Opus rate: 15 USD / 1M input + 75 USD / 1M output.
    expected = (1234 * 15.0 + 56 * 75.0) / 1_000_000.0
    assert verdict.cost_usd == pytest.approx(expected)
    assert verdict.cost_usd > 0


def test_judge_falls_back_when_response_is_malformed(tmp_path: Path) -> None:
    """A prose body with no JSON / no ``passed:`` literal hits the fallback branch."""
    before = _write_png(tmp_path / "before.png", b"b")
    after = _write_png(tmp_path / "after.png", b"a")
    response = _StubMessage(text="yes the order changed")
    client = _StubClient(response)

    verdict = asyncio.run(
        run_completion_judge(
            before,
            after,
            "trajectory text",
            "Did the order change?",
            client=client,  # type: ignore[arg-type]
        )
    )

    assert verdict.passed is False
    # Fallback prefix surfaces in ``reasoning`` so callers can flag it via
    # ``ProbeOutcome.notes`` when they downgrade ``passed`` to ``False``.
    assert verdict.reasoning.startswith("[unparseable judge response]")
    assert "yes the order changed" in verdict.reasoning
