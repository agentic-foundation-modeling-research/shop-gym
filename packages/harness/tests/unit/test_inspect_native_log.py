"""Tests for ``harness.tools.inspect_native_log``.

Covers runtime auto-detection, the Claude Code placeholder, and the
per-tool argument formatters (compact one-line summaries and the verbose
detail-mode formatter). Uses the recorded
``toy_homepage_claude_code/exec-0001/native.log`` cassette for the
detection and placeholder cases; renderer-shape tests against a pi
cassette have been retired alongside the cassette itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.tools.inspect_native_log import (
    _compact_tool_summary,  # type: ignore[reportPrivateUsage]
    _format_tool_call_args,  # type: ignore[reportPrivateUsage]
    _tildify,  # type: ignore[reportPrivateUsage]
    _truncate_inline,  # type: ignore[reportPrivateUsage]
    detect_runtime,
    main,
    render_claude_code_placeholder,
)

_HARNESS_ROOT = Path(__file__).resolve().parent.parent.parent
_CASSETTES = _HARNESS_ROOT / "tests" / "cassettes"
_CLAUDE_LOG = _CASSETTES / "toy_homepage_claude_code" / "exec-0001" / "native.log"


# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------


def test_detect_runtime_claude_code_cassette() -> None:
    """The claude_code cassette starts with a ``system`` event → ``claude_code``."""
    assert detect_runtime(_CLAUDE_LOG) == "claude_code"


def test_detect_runtime_blank_file_returns_unknown(tmp_path: Path) -> None:
    """An empty file matches no signature."""
    log = tmp_path / "empty.log"
    log.write_text("", encoding="utf-8")
    assert detect_runtime(log) == "unknown"


def test_detect_runtime_skips_garbage_then_finds_signature(tmp_path: Path) -> None:
    """Non-JSON CLI banners and partial writes are skipped during detection."""
    log = tmp_path / "noisy.log"
    log.write_text(
        "\n".join(
            [
                "not-json banner",
                "{",  # truncated
                '{"type": "session", "version": 3}',
                '{"type": "agent_start"}',
            ]
        ),
        encoding="utf-8",
    )
    assert detect_runtime(log) == "pi"


# ---------------------------------------------------------------------------
# Claude Code placeholder
# ---------------------------------------------------------------------------


def test_render_claude_code_placeholder_mentions_path() -> None:
    """The Claude Code stub identifies itself and echoes the input path."""
    output = render_claude_code_placeholder(_CLAUDE_LOG)
    assert "not yet implemented" in output
    assert str(_CLAUDE_LOG) in output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def test_main_claude_code_cassette_emits_placeholder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main`` returns 0 and prints the placeholder for a claude_code cassette."""
    rc = main([str(_CLAUDE_LOG)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "not yet implemented" in captured.out


def test_main_missing_file_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main`` writes an error and returns 1 when the path does not exist."""
    rc = main([str(tmp_path / "does_not_exist.log")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "not a file" in captured.err


def test_main_unknown_runtime_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unrecognised log shape produces a clear error and rc=1."""
    log = tmp_path / "unknown.log"
    log.write_text('{"type": "something_else"}\n', encoding="utf-8")
    rc = main([str(log)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "could not detect runtime" in captured.err


# ---------------------------------------------------------------------------
# Compact tool summarizer (one-line ``[tool: …]`` form)
# ---------------------------------------------------------------------------


def test_compact_tool_summary_bash_shows_command_inline() -> None:
    """``bash`` summary renders ``[bash: <command>]`` without the ``$`` prefix."""
    rendered = _compact_tool_summary("bash", {"command": "ls -la /tmp"}, max_chars=100)
    assert rendered == "[bash: ls -la /tmp]"


def test_compact_tool_summary_read_appends_offset_range() -> None:
    """``read`` with offset+limit appends ``:start-end`` to the path."""
    rendered = _compact_tool_summary(
        "read",
        {"file_path": "/Users/me/x.py", "offset": 1, "limit": 100},
        max_chars=200,
    )
    assert rendered.startswith("[read: ")
    assert rendered.endswith(":1-100]")


def test_compact_tool_summary_read_tildifies_home() -> None:
    """``read`` paths under HOME are tildified for compactness."""
    home = str(Path.home())
    rendered = _compact_tool_summary("read", {"file_path": f"{home}/foo.py"}, max_chars=200)
    assert "~/foo.py]" in rendered


def test_compact_tool_summary_unknown_tool_falls_back_to_json() -> None:
    """Unrecognised tools render JSON inside the brackets."""
    rendered = _compact_tool_summary("custom", {"foo": 1}, max_chars=200)
    assert rendered.startswith("[custom: ")
    assert "foo" in rendered


def test_compact_tool_summary_truncates_to_budget() -> None:
    """Inner content is capped to the per-line budget with a ``…`` marker."""
    budget = 40
    long_cmd = "x" * 500
    rendered = _compact_tool_summary("bash", {"command": long_cmd}, max_chars=budget)
    assert len(rendered) <= budget
    assert rendered.endswith("…]")


# ---------------------------------------------------------------------------
# Helpers — direct unit coverage
# ---------------------------------------------------------------------------


def test_tildify_replaces_home_prefix() -> None:
    """``$HOME/x`` becomes ``~/x``; unrelated paths stay literal."""
    home = str(Path.home())
    assert _tildify(f"{home}/proj/x.py") == "~/proj/x.py"
    assert _tildify("/etc/hosts") == "/etc/hosts"


def test_truncate_inline_collapses_whitespace_and_caps_length() -> None:
    """Newlines and runs of whitespace become single spaces; cap → ``…``."""
    assert _truncate_inline("hello\n  world", 30) == "hello world"
    cap = 10
    out = _truncate_inline("a" * 100, cap)
    assert len(out) == cap
    assert out.endswith("…")


# ---------------------------------------------------------------------------
# Per-tool detail-mode formatter (used by ``--detail``)
# ---------------------------------------------------------------------------


def test_format_tool_call_args_bash_renders_command_only() -> None:
    """``bash`` tool calls collapse to a ``$ <command>`` one-liner."""
    rendered = _format_tool_call_args("bash", {"command": "ls -la", "description": "list"})
    assert rendered == "$ ls -la"


def test_format_tool_call_args_read_includes_offset_and_limit() -> None:
    """``read`` shows the path with offset/limit when supplied."""
    rendered = _format_tool_call_args("read", {"file_path": "/x.py", "offset": 10, "limit": 50})
    assert rendered == "/x.py  (offset=10, limit=50)"


def test_format_tool_call_args_read_path_only() -> None:
    """``read`` with just a path renders just the path."""
    rendered = _format_tool_call_args("read", {"file_path": "/a/b.py"})
    assert rendered == "/a/b.py"


def test_format_tool_call_args_write_truncates_long_content() -> None:
    """``write`` previews the first 10 lines and notes the rest."""
    content = "\n".join(f"line {i}" for i in range(25))
    rendered = _format_tool_call_args("write", {"file_path": "/x.txt", "content": content})
    assert rendered.startswith("/x.txt\nline 0\n")
    assert "more lines" in rendered


def test_format_tool_call_args_edit_shows_old_new_first_lines() -> None:
    """``edit`` shows the path plus a one-line ``-`` / ``+`` preview."""
    rendered = _format_tool_call_args(
        "edit",
        {"file_path": "/x.py", "old_string": "old\nrest", "new_string": "new\nrest"},
    )
    assert rendered == "/x.py\n- old\n+ new"


def test_format_tool_call_args_grep_combines_pattern_and_path() -> None:
    """``grep`` shows ``<pattern>  in <path>`` when a path is provided."""
    rendered = _format_tool_call_args("grep", {"pattern": "TODO", "path": "src/"})
    assert rendered == "TODO  in src/"


def test_format_tool_call_args_unknown_tool_falls_back_to_json() -> None:
    """An unrecognised tool renders compact JSON."""
    rendered = _format_tool_call_args("custom_tool", {"foo": 1})
    assert rendered.startswith("{")
    assert "foo" in rendered


def test_format_tool_call_args_empty_arguments() -> None:
    """An empty argument dict renders a stable placeholder."""
    assert _format_tool_call_args("bash", {}) == "(no arguments)"
