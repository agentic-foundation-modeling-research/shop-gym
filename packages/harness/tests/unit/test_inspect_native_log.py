"""Tests for ``harness.tools.inspect_native_log``.

Covers the runtime auto-detection logic, both render modes (compact
default and ``--detail`` verbose), per-tool argument formatting, the
``--no-tools`` filter, and the Claude Code placeholder. Uses the
recorded ``toy_homepage_*`` cassettes as the only fixtures so the tests
stay in lockstep with the real runtime stream contracts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.tools.inspect_native_log import (
    StepFilter,
    _compact_tool_summary,  # type: ignore[reportPrivateUsage]
    _format_tool_call_args,  # type: ignore[reportPrivateUsage]
    _tildify,  # type: ignore[reportPrivateUsage]
    _truncate_inline,  # type: ignore[reportPrivateUsage]
    detect_runtime,
    main,
    render_claude_code_placeholder,
    render_pi,
)

_HARNESS_ROOT = Path(__file__).resolve().parent.parent.parent
_CASSETTES = _HARNESS_ROOT / "tests" / "cassettes"
_PI_LOG = _CASSETTES / "toy_homepage_pi" / "exec-0001" / "native.log"
_CLAUDE_LOG = _CASSETTES / "toy_homepage_claude_code" / "exec-0001" / "native.log"


# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------


def test_detect_runtime_pi_cassette() -> None:
    """The pi cassette starts with a ``session`` event → ``pi``."""
    assert detect_runtime(_PI_LOG) == "pi"


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
# Compact (default) renderer
# ---------------------------------------------------------------------------


def test_render_pi_compact_default_emits_bullets() -> None:
    """Default mode produces ``• user:`` / ``• [tool: …]`` / ``• assistant:`` lines."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    assert "• user:" in output
    assert "• assistant:" in output or "• [" in output  # at least one bullet


def test_render_pi_compact_includes_step_marker() -> None:
    """Each compact bullet is anchored by a zero-padded ``s<NN>`` step marker."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    assert "s01 •" in output
    # Markers are padded to a uniform width (>=2) so columns line up.
    assert "s1 •" not in output


def test_render_pi_compact_bullets_at_column_zero() -> None:
    """All bullet lines start at column 0 — no role-based indentation."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    bullet_lines = [line for line in output.splitlines() if "•" in line]
    assert bullet_lines, "expected at least one bullet line"
    for line in bullet_lines:
        assert not line.startswith(" "), f"unexpected indentation: {line!r}"


def test_render_pi_compact_omits_section_headers() -> None:
    """The compact view never emits the ``──── turn N / msg M`` divider."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    assert "──── turn" not in output
    assert "msg " not in output


def test_render_pi_compact_omits_tool_results() -> None:
    """Tool-result messages are silently dropped from the compact view."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    assert "tool_result" not in output
    assert "status: ok" not in output
    assert "status: error" not in output


def test_render_pi_compact_no_tools_hides_tool_calls() -> None:
    """``hide_tools=True`` removes the ``[tool: …]`` bullets."""
    with_tools = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    without_tools = render_pi(
        _PI_LOG,
        step_filter=None,
        full=False,
        max_chars=400,
        tool=None,
        hide_tools=True,
    )
    assert "• [bash:" in with_tools or "• [read:" in with_tools
    assert "• [bash:" not in without_tools
    assert "• [read:" not in without_tools


def test_render_pi_compact_thinking_hidden_by_default() -> None:
    """Thinking blocks are not shown unless ``show_thinking=True``."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    assert "• thinking:" not in output


def test_render_pi_compact_show_thinking_includes_thinking() -> None:
    """``show_thinking=True`` adds ``• thinking:`` bullets."""
    output = render_pi(
        _PI_LOG,
        step_filter=None,
        full=False,
        max_chars=400,
        tool=None,
        show_thinking=True,
    )
    assert "• thinking:" in output


def test_render_pi_compact_drops_streaming_deltas() -> None:
    """Streaming-delta event names never leak into the compact output."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    assert "message_update" not in output
    assert "toolcall_delta" not in output
    assert "tool_execution_update" not in output


def test_render_pi_compact_step_filter_restricts_output() -> None:
    """``--step 1`` applies in compact mode and shrinks the output."""
    full_output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    step1_output = render_pi(
        _PI_LOG,
        step_filter=StepFilter(start=1, end=1),
        full=False,
        max_chars=400,
        tool=None,
    )
    assert len(step1_output) < len(full_output)


def test_render_pi_compact_expand_renders_full_content_under_bullets() -> None:
    """``expand=True`` puts each bullet's full body on indented follow-up lines."""
    compact = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    expanded = render_pi(
        _PI_LOG,
        step_filter=None,
        full=False,
        max_chars=400,
        tool=None,
        expand=True,
    )
    # Bullet head sits on its own line, followed by 4-space-indented body.
    assert "• user:\n    " in expanded
    # No inline truncation marker survives in expanded output.
    assert "…" not in expanded or len(expanded) > len(compact)
    assert any(line.startswith("    ") for line in expanded.splitlines())


def test_render_pi_compact_expand_surfaces_tool_results() -> None:
    """``expand=True`` brings tool-result messages back into compact output."""
    plain = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None)
    expanded = render_pi(
        _PI_LOG,
        step_filter=None,
        full=False,
        max_chars=400,
        tool=None,
        expand=True,
    )
    assert "• result" not in plain
    assert "• result" in expanded


def test_render_pi_compact_expand_respects_no_tools() -> None:
    """``hide_tools=True`` still wins over ``expand=True`` for tool results."""
    expanded_no_tools = render_pi(
        _PI_LOG,
        step_filter=None,
        full=False,
        max_chars=400,
        tool=None,
        expand=True,
        hide_tools=True,
    )
    assert "• result" not in expanded_no_tools
    assert "• [bash" not in expanded_no_tools


# ---------------------------------------------------------------------------
# Detail (--detail) renderer
# ---------------------------------------------------------------------------


def test_render_pi_detail_includes_session_header_and_message_sections() -> None:
    """Detail mode emits the session banner and per-section dividers."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None, detail=True)
    assert "pi native.log" in output
    assert "session" in output
    assert "──── turn" in output
    assert " · user " in output or " · user\n" in output
    assert " · assistant " in output


def test_render_pi_detail_drops_streaming_deltas() -> None:
    """Detail mode also drops streaming-delta event names."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None, detail=True)
    assert "message_update" not in output
    assert "toolcall_delta" not in output


def test_render_pi_detail_full_disables_truncation() -> None:
    """``--full`` removes the size annotation that truncated blocks otherwise carry."""
    truncated = render_pi(
        _PI_LOG, step_filter=None, full=False, max_chars=50, tool=None, detail=True
    )
    full = render_pi(_PI_LOG, step_filter=None, full=True, max_chars=50, tool=None, detail=True)
    assert "[truncated," in truncated
    assert "[truncated," not in full


def test_render_pi_detail_truncation_uses_ellipsis_leader() -> None:
    """Truncated blocks are prefixed with the ``…`` marker on their own line."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=50, tool=None, detail=True)
    assert "\n… [truncated," in output or "    … [truncated," in output


def test_render_pi_detail_collapses_first_user_message_by_default() -> None:
    """The first user message renders as a one-line preview by default."""
    output = render_pi(_PI_LOG, step_filter=None, full=True, max_chars=400, tool=None, detail=True)
    assert "--show-prompt to expand" in output


def test_render_pi_detail_show_prompt_expands_first_user_message() -> None:
    """``show_prompt=True`` keeps the full text of the first user message."""
    output = render_pi(
        _PI_LOG,
        step_filter=None,
        full=True,
        max_chars=400,
        tool=None,
        detail=True,
        show_prompt=True,
    )
    assert "--show-prompt to expand" not in output


def test_render_pi_detail_default_usage_omits_cache_tokens() -> None:
    """Detail mode default shows ``tok=N`` (or nothing); no cache breakdown."""
    output = render_pi(_PI_LOG, step_filter=None, full=False, max_chars=400, tool=None, detail=True)
    assert "cacheRead=" not in output
    assert "cacheWrite=" not in output


def test_render_pi_detail_show_usage_includes_full_breakdown() -> None:
    """``show_usage=True`` surfaces the input/output/cache counts."""
    output = render_pi(
        _PI_LOG,
        step_filter=None,
        full=False,
        max_chars=400,
        tool=None,
        detail=True,
        show_usage=True,
    )
    assert any(key in output for key in ("input=", "cacheRead=", "cacheWrite="))


def test_render_pi_detail_omits_call_id_line_in_tool_results() -> None:
    """Tool-result sections rely on adjacency; the ``call_id:`` line is gone."""
    output = render_pi(_PI_LOG, step_filter=None, full=True, max_chars=400, tool=None, detail=True)
    assert "call_id:" not in output


def test_render_pi_detail_uses_call_label_for_tool_calls() -> None:
    """Assistant tool-call blocks render under a ``· call: <name>`` label."""
    output = render_pi(_PI_LOG, step_filter=None, full=True, max_chars=400, tool=None, detail=True)
    assert "· call:" in output


def test_render_pi_detail_no_tools_drops_tool_result_sections() -> None:
    """``hide_tools=True`` suppresses tool_result sections in detail mode too."""
    with_tools = render_pi(
        _PI_LOG, step_filter=None, full=True, max_chars=400, tool=None, detail=True
    )
    without_tools = render_pi(
        _PI_LOG,
        step_filter=None,
        full=True,
        max_chars=400,
        tool=None,
        detail=True,
        hide_tools=True,
    )
    assert "tool_result" in with_tools
    assert "tool_result" not in without_tools


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


def test_main_pi_cassette_writes_compact_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main`` returns 0 and writes the compact bullet view by default."""
    rc = main([str(_PI_LOG)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "• user:" in captured.out
    assert "──── turn" not in captured.out


def test_main_detail_flag_emits_session_banner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--detail`` switches to verbose mode and emits the pi banner."""
    rc = main([str(_PI_LOG), "--detail"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "pi native.log" in captured.out
    assert "──── turn" in captured.out


def test_main_no_tools_flag_hides_tool_bullets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--no-tools`` removes ``[tool: …]`` bullets from the compact output."""
    rc = main([str(_PI_LOG), "--no-tools"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "• [bash:" not in captured.out
    assert "• [read:" not in captured.out


def test_main_claude_code_cassette_emits_placeholder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main`` returns 0 and prints the placeholder for a claude_code cassette."""
    rc = main([str(_CLAUDE_LOG)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "not yet implemented" in captured.out


def test_main_capsys_output_has_no_ansi_codes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """capsys is not a TTY — the palette auto-disables and emits no ANSI codes."""
    rc = main([str(_PI_LOG)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "\x1b[" not in captured.out


def test_main_expand_flag_emits_full_bodies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--expand`` renders multi-line bodies under each bullet."""
    rc = main([str(_PI_LOG), "--expand"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "• user:\n    " in captured.out


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
