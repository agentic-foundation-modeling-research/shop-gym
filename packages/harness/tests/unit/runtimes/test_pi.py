"""Tests for `harness.runtimes.pi` (T3.2).

Exercises the public converter and the registry entry. The subprocess
driver itself is not exercised here — it calls the real ``pi`` CLI and
is covered by the gated smoke tests (T3.4).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from harness.runtimes import AgentRuntime, LLMCompleter, get_runtime
from harness.runtimes.pi import PiRuntime, build_argv, build_complete_argv, parse_native_log
from harness.trajectory import (
    MessageStep,
    ThoughtStep,
    ToolCallStep,
    ToolResultStep,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "pi_native.log"
_TS = dt.datetime(2025, 1, 1, 0, 0, tzinfo=dt.UTC)


def test_parse_native_log_returns_ordered_steps_for_recorded_fixture() -> None:
    """End-to-end converter happy path against a recorded native log."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)

    # Order matches the fixture: thinking → text → tool_use → tool_result
    # → tool_use → tool_result(error) → text. Lifecycle events
    # (`session`, `agent_start`, `turn_start`/`turn_end`, `agent_end`),
    # the streaming `message_start`/`message_update` deltas, the
    # `tool_execution_*` events, and the `queue_update` event are
    # intentionally dropped. The malformed mid-stream line is skipped.
    kinds = [type(step) for step in steps]
    assert kinds == [
        ThoughtStep,
        MessageStep,
        ToolCallStep,
        ToolResultStep,
        ToolCallStep,
        ToolResultStep,
        MessageStep,
    ]


def test_parse_native_log_assistant_text_becomes_message_step() -> None:
    """Assistant `text` blocks surface as `MessageStep(role=assistant)`."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)

    messages = [s for s in steps if isinstance(s, MessageStep)]
    assert messages[0].role == "assistant"
    assert messages[0].text == "Reading plan.md to find the next task."
    assert messages[0].timestamp == _TS


def test_parse_native_log_thinking_becomes_thought_step() -> None:
    """Assistant `thinking` blocks surface as `ThoughtStep`."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)
    thoughts = [s for s in steps if isinstance(s, ThoughtStep)]
    assert len(thoughts) == 1
    assert thoughts[0].text == "Need to inspect plan.md."


def test_parse_native_log_tool_call_becomes_tool_call_step() -> None:
    """Assistant `toolCall` blocks surface as `ToolCallStep` carrying arguments."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)
    tool_calls = [s for s in steps if isinstance(s, ToolCallStep)]
    assert [tc.call_id for tc in tool_calls] == ["toolu_1", "toolu_2"]
    first = tool_calls[0]
    assert first.tool == "bash"
    assert first.arguments == {"command": "cat plan.md"}


def test_parse_native_log_tool_result_array_content_flattened() -> None:
    """`toolResult` messages flatten their array `content` to a single string."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)
    results = [s for s in steps if isinstance(s, ToolResultStep)]
    assert results[0].call_id == "toolu_1"
    assert results[0].is_error is False
    assert results[0].output == "# Plan\n\n## Tasks\n- [ ] homepage\n"
    assert results[1].call_id == "toolu_2"
    assert results[1].is_error is True
    assert results[1].output == "command failed"


def test_parse_native_log_tool_result_string_content_preserved(tmp_path: Path) -> None:
    """`toolResult` messages with bare string `content` round-trip verbatim."""
    log = tmp_path / "native.log"
    log.write_text(
        '{"type":"message_end","message":{"role":"toolResult",'
        '"toolCallId":"toolu_x","toolName":"bash","content":"raw output","isError":false}}\n',
        encoding="utf-8",
    )

    steps = parse_native_log(log, timestamp=_TS)

    assert len(steps) == 1
    result = steps[0]
    assert isinstance(result, ToolResultStep)
    assert result.call_id == "toolu_x"
    assert result.output == "raw output"
    assert result.is_error is False


def test_parse_native_log_skips_malformed_lines(tmp_path: Path) -> None:
    """Non-JSON noise interleaved with JSON events is silently skipped."""
    log = tmp_path / "native.log"
    log.write_text(
        "pi: starting...\n"
        '{"type":"message_end","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"hi"}]}}\n'
        "<-- partial line cut off",
        encoding="utf-8",
    )

    steps = parse_native_log(log, timestamp=_TS)

    assert len(steps) == 1
    assert isinstance(steps[0], MessageStep)
    assert steps[0].text == "hi"


def test_parse_native_log_missing_file_returns_empty_list(tmp_path: Path) -> None:
    """A missing native.log yields an empty step list, never raises."""
    assert parse_native_log(tmp_path / "absent.log", timestamp=_TS) == []


def test_parse_native_log_drops_streaming_deltas_and_lifecycle_events(
    tmp_path: Path,
) -> None:
    """Only `message_end` events emit steps; deltas and lifecycle events are dropped."""
    log = tmp_path / "native.log"
    log.write_text(
        '{"type":"session","version":3,"id":"abc","cwd":"/tmp"}\n'
        '{"type":"agent_start"}\n'
        '{"type":"turn_start"}\n'
        '{"type":"message_start","message":{"role":"assistant","content":[]}}\n'
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta",'
        '"delta":"hi"},"message":{"role":"assistant","content":[{"type":"text",'
        '"text":"hi"}]}}\n'
        '{"type":"tool_execution_start","toolCallId":"toolu_1","toolName":"bash",'
        '"args":{"command":"echo hi"}}\n'
        '{"type":"tool_execution_end","toolCallId":"toolu_1","toolName":"bash",'
        '"result":{"content":[{"type":"text","text":"hi\\n"}]},"isError":false}\n'
        '{"type":"turn_end","message":{"role":"assistant","content":[]},"toolResults":[]}\n'
        '{"type":"agent_end","messages":[]}\n',
        encoding="utf-8",
    )

    assert parse_native_log(log, timestamp=_TS) == []


def test_parse_native_log_drops_unknown_block_types(tmp_path: Path) -> None:
    """Unknown content blocks inside an assistant message are dropped."""
    log = tmp_path / "native.log"
    log.write_text(
        '{"type":"message_end","message":{"role":"assistant",'
        '"content":[{"type":"future_block","data":"???"}]}}\n',
        encoding="utf-8",
    )

    assert parse_native_log(log, timestamp=_TS) == []


def test_parse_native_log_drops_tool_result_without_call_id(tmp_path: Path) -> None:
    """A `toolResult` message missing `toolCallId` is silently dropped."""
    log = tmp_path / "native.log"
    log.write_text(
        '{"type":"message_end","message":{"role":"toolResult",'
        '"toolName":"bash","content":[{"type":"text","text":"oops"}],"isError":false}}\n',
        encoding="utf-8",
    )

    assert parse_native_log(log, timestamp=_TS) == []


def test_parse_native_log_user_text_becomes_message_step(tmp_path: Path) -> None:
    """User `text` blocks surface as `MessageStep(role=user)`."""
    log = tmp_path / "native.log"
    log.write_text(
        '{"type":"message_end","message":{"role":"user",'
        '"content":[{"type":"text","text":"do the thing"}]}}\n',
        encoding="utf-8",
    )

    steps = parse_native_log(log, timestamp=_TS)
    assert len(steps) == 1
    msg = steps[0]
    assert isinstance(msg, MessageStep)
    assert msg.role == "user"
    assert msg.text == "do the thing"


def test_runtime_satisfies_agent_runtime_protocol() -> None:
    """`PiRuntime` satisfies the `AgentRuntime` Protocol structurally."""
    runtime = PiRuntime(binary="pi")

    assert isinstance(runtime, AgentRuntime)
    assert runtime.binary == "pi"
    assert runtime.model is None


def test_build_argv_omits_model_flag_by_default() -> None:
    """Default invocation preserves the pre-T6.1 argv (no ``--model``)."""
    assert build_argv(binary="pi", model=None) == ["pi", "--print", "--mode", "json"]


def test_build_argv_appends_model_flag_when_set() -> None:
    """A configured model threads through as ``--model <model>`` on the CLI."""
    assert build_argv(binary="pi", model="anthropic/claude-sonnet-4-6") == [
        "pi",
        "--print",
        "--mode",
        "json",
        "--model",
        "anthropic/claude-sonnet-4-6",
    ]


def test_runtime_exposes_configured_model() -> None:
    """`PiRuntime(model=...)` round-trips the identifier through `runtime.model`."""
    runtime = PiRuntime(model="sonnet:high")

    assert runtime.model == "sonnet:high"


def test_get_runtime_resolves_pi() -> None:
    """The registry resolves ``pi`` to a `PiRuntime`."""
    runtime = get_runtime("pi")

    assert isinstance(runtime, PiRuntime)


def test_get_runtime_pi_forwards_kwargs() -> None:
    """Constructor kwargs (e.g. ``binary``) are forwarded by the registry."""
    runtime = get_runtime("pi", binary="/opt/bin/pi")

    assert isinstance(runtime, PiRuntime)
    assert runtime.binary == "/opt/bin/pi"


def test_get_runtime_pi_forwards_model_kwarg() -> None:
    """`model` threads through `get_runtime("pi", model=...)` to `PiRuntime`.

    Mirrors the T6.1 acceptance: callers (synthesis, smoke tests) can
    pin the underlying Claude model via the registry without editing
    harness internals, and the value reaches the CLI argv builder.
    """
    runtime = get_runtime("pi", model="anthropic/claude-opus-4-7")

    assert isinstance(runtime, PiRuntime)
    assert runtime.model == "anthropic/claude-opus-4-7"
    assert build_argv(binary=runtime.binary, model=runtime.model)[-2:] == [
        "--model",
        "anthropic/claude-opus-4-7",
    ]


@pytest.mark.parametrize("bad_kw", [{"unknown_arg": 1}])
def test_get_runtime_pi_rejects_unknown_kwargs(
    bad_kw: dict[str, object],
) -> None:
    """Forwarding garbage to the constructor surfaces a `TypeError`."""
    with pytest.raises(TypeError):
        get_runtime("pi", **bad_kw)


def test_build_complete_argv_omits_model_flag_by_default() -> None:
    """One-shot completion argv defaults to ``pi`` text mode without ``--model``."""
    assert build_complete_argv(binary="pi", model=None) == [
        "pi",
        "--print",
        "--mode",
        "text",
        "--no-tools",
        "--no-context-files",
        "--no-session",
    ]


def test_build_complete_argv_appends_model_flag_when_set() -> None:
    """A configured model threads through the one-shot completion argv."""
    assert build_complete_argv(binary="pi", model="anthropic/claude-opus-4-7") == [
        "pi",
        "--print",
        "--mode",
        "text",
        "--no-tools",
        "--no-context-files",
        "--no-session",
        "--model",
        "anthropic/claude-opus-4-7",
    ]


def test_runtime_satisfies_llm_completer_protocol() -> None:
    """`PiRuntime` exposes ``complete`` and so satisfies `LLMCompleter` (T6.2)."""
    runtime = PiRuntime(binary="pi")

    assert isinstance(runtime, LLMCompleter)
