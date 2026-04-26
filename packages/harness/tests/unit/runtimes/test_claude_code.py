"""Tests for `harness.runtimes.claude_code` (T3.1).

Exercises the public converter, the CLAUDE.md symlink helper, and the
registry entry. The subprocess driver itself is not exercised here — it
calls the real `claude` CLI and is covered by the gated smoke tests
(T3.4).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from harness.runtimes import AgentRuntime, get_runtime
from harness.runtimes.claude_code import (
    ClaudeCodeRuntime,
    _ensure_claude_md_symlink,
    parse_native_log,
)
from harness.trajectory import (
    ErrorStep,
    MessageStep,
    ThoughtStep,
    ToolCallStep,
    ToolResultStep,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "claude_code_native.log"
_TS = dt.datetime(2025, 1, 1, 0, 0, tzinfo=dt.UTC)


def test_parse_native_log_returns_ordered_steps_for_recorded_fixture() -> None:
    """End-to-end converter happy path against a recorded native log."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)

    # Order matches the fixture: thinking → text → tool_use → tool_result
    # → tool_use → tool_result(error) → text. The `system` init line and
    # the trailing `result` summary are intentionally dropped; the
    # malformed mid-stream line is skipped.
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


def test_parse_native_log_tool_use_becomes_tool_call_step() -> None:
    """Assistant `tool_use` blocks surface as `ToolCallStep` carrying input."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)
    tool_calls = [s for s in steps if isinstance(s, ToolCallStep)]
    assert [tc.call_id for tc in tool_calls] == ["toolu_1", "toolu_2"]
    first = tool_calls[0]
    assert first.call_id == "toolu_1"
    assert first.tool == "Bash"
    assert first.arguments == {"command": "cat plan.md"}


def test_parse_native_log_tool_result_string_content_preserved() -> None:
    """User `tool_result` with string content round-trips verbatim."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)
    results = [s for s in steps if isinstance(s, ToolResultStep)]
    assert results[0].call_id == "toolu_1"
    assert results[0].is_error is False
    assert results[0].output == "# Plan\n\n## Tasks\n- [ ] homepage\n"


def test_parse_native_log_tool_result_array_content_flattened() -> None:
    """Array-form tool_result content is flattened to its concatenated text."""
    steps = parse_native_log(_FIXTURE, timestamp=_TS)
    results = [s for s in steps if isinstance(s, ToolResultStep)]
    assert results[1].call_id == "toolu_2"
    assert results[1].is_error is True
    assert results[1].output == "command failed"


def test_parse_native_log_skips_malformed_lines(tmp_path: Path) -> None:
    """Non-JSON noise interleaved with JSON events is silently skipped."""
    log = tmp_path / "native.log"
    log.write_text(
        "claude: starting...\n"
        '{"type":"assistant","message":{"role":"assistant",'
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


def test_parse_native_log_result_event_is_error_emits_error_step(
    tmp_path: Path,
) -> None:
    """A failing terminal `result` event produces an `ErrorStep`."""
    log = tmp_path / "native.log"
    log.write_text(
        '{"type":"result","subtype":"error","is_error":true,"error":"rate limited"}\n',
        encoding="utf-8",
    )

    steps = parse_native_log(log, timestamp=_TS)

    assert len(steps) == 1
    err = steps[0]
    assert isinstance(err, ErrorStep)
    assert err.message == "rate limited"


def test_parse_native_log_drops_unknown_event_and_block_types(
    tmp_path: Path,
) -> None:
    """Unknown top-level types and unknown content blocks are dropped."""
    log = tmp_path / "native.log"
    log.write_text(
        '{"type":"telemetry","payload":{"x":1}}\n'
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"future_block","data":"???"}]}}\n',
        encoding="utf-8",
    )

    assert parse_native_log(log, timestamp=_TS) == []


def test_ensure_claude_md_symlink_creates_relative_link(tmp_path: Path) -> None:
    """The helper creates a relative `CLAUDE.md → AGENTS.md` symlink."""
    (tmp_path / "AGENTS.md").write_text("# rules", encoding="utf-8")

    _ensure_claude_md_symlink(tmp_path)

    target = tmp_path / "CLAUDE.md"
    assert target.is_symlink()
    assert Path(target.readlink()) == Path("AGENTS.md")
    # Reading through the symlink resolves to AGENTS.md content.
    assert target.read_text(encoding="utf-8") == "# rules"


def test_ensure_claude_md_symlink_is_idempotent(tmp_path: Path) -> None:
    """Re-invoking the helper with an existing CLAUDE.md leaves it alone."""
    (tmp_path / "AGENTS.md").write_text("# rules", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# pre-existing", encoding="utf-8")

    _ensure_claude_md_symlink(tmp_path)

    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "# pre-existing"
    assert not (tmp_path / "CLAUDE.md").is_symlink()


def test_ensure_claude_md_symlink_skips_when_agents_md_missing(
    tmp_path: Path,
) -> None:
    """Without AGENTS.md present, no symlink is created."""
    _ensure_claude_md_symlink(tmp_path)

    assert not (tmp_path / "CLAUDE.md").exists()


def test_runtime_satisfies_agent_runtime_protocol() -> None:
    """`ClaudeCodeRuntime` satisfies the `AgentRuntime` Protocol structurally."""
    runtime = ClaudeCodeRuntime(binary="claude")

    assert isinstance(runtime, AgentRuntime)
    assert runtime.binary == "claude"


def test_get_runtime_resolves_claude_code() -> None:
    """The registry resolves ``claude_code`` to a `ClaudeCodeRuntime`."""
    runtime = get_runtime("claude_code")

    assert isinstance(runtime, ClaudeCodeRuntime)


def test_get_runtime_claude_code_forwards_kwargs() -> None:
    """Constructor kwargs (e.g. ``binary``) are forwarded by the registry."""
    runtime = get_runtime("claude_code", binary="/opt/bin/claude")

    assert isinstance(runtime, ClaudeCodeRuntime)
    assert runtime.binary == "/opt/bin/claude"


@pytest.mark.parametrize("bad_kw", [{"unknown_arg": 1}])
def test_get_runtime_claude_code_rejects_unknown_kwargs(
    bad_kw: dict[str, object],
) -> None:
    """Forwarding garbage to the constructor surfaces a `TypeError`."""
    with pytest.raises(TypeError):
        get_runtime("claude_code", **bad_kw)
