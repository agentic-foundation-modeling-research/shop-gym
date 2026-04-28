"""Pretty-print a harness ``native.log`` for human inspection.

The harness writes one ``native.log`` per iteration under
``<run_dir>/iters/<iter>/native.log``. Each line is a JSON event from the
underlying CLI's stream — most of the bytes are streaming deltas
(``message_update``/``toolcall_delta``) that re-emit the in-progress
state on every token. The actual signal is concentrated in a small
fraction of events (``message_end`` for ``pi``; ``assistant``/``user``
for Claude Code).

This module auto-detects the runtime that produced the log and emits a
compact, role-annotated trajectory to stdout. The two runtimes have
different stream schemas — only the ``pi`` renderer is implemented;
Claude Code falls through to a placeholder until that path is needed.

The module is wired up as a console script (``inspect``) in
``packages/harness/pyproject.toml``. Typical usage from anywhere in the
workspace:

```
uv run inspect <path>                       # compact one-line-per-event view
uv run inspect <path> --no-tools            # hide tool calls (just user/assistant)
uv run inspect <path> --show-thinking       # include thinking blocks
uv run inspect <path> --expand              # multi-line full content under bullets
uv run inspect <path> --detail              # full per-section verbose view
uv run inspect <path> --detail --step 2-5 --tool bash
```

Auto-detection inspects the first few JSON events: pi emits a
``session`` header and ``agent_start`` / ``turn_start`` lifecycle
events, while Claude Code emits top-level ``system`` / ``assistant`` /
``user`` / ``result`` events. The signature sets are disjoint, so the
first matching event picks the renderer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

# Tool-specific argument formatters return either a rendered string or
# ``None`` to signal "fall back to the generic JSON dump".
_ToolFormatter = Callable[[dict[str, Any]], str | None]

# Lifecycle/event names unique to the `pi` JSON-mode stream
# (`docs/json.md` of the `pi` CLI). These never appear in the Claude
# Code stream-json schema, so seeing any of them is sufficient to pick
# the `pi` renderer.
_PI_SIGNATURES: Final[frozenset[str]] = frozenset(
    {
        "session",
        "agent_start",
        "turn_start",
        "turn_end",
        "agent_end",
        "message_start",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
    }
)

# Top-level event names emitted by the Claude Code CLI's stream-json
# output. Disjoint from `_PI_SIGNATURES`.
_CLAUDE_SIGNATURES: Final[frozenset[str]] = frozenset({"system", "assistant", "user", "result"})

_DEFAULT_MAX_CHARS: Final[int] = 800
_SCAN_LINES_FOR_DETECTION: Final[int] = 20
_PROMPT_PREVIEW_CHARS: Final[int] = 120
_WRITE_PREVIEW_LINES: Final[int] = 10
_EDIT_LINE_PREVIEW_CHARS: Final[int] = 80
_CALL_ID_PREVIEW_CHARS: Final[int] = 12

# Compact-mode line-width budget. Each summary bullet (`• user: …`,
# `• [bash: …]`) is collapsed to a single line and capped here so the
# output stays scannable in a normal terminal.
_COMPACT_LINE_CHARS: Final[int] = 100


RuntimeKind = Literal["pi", "claude_code", "unknown"]


@dataclass(frozen=True)
class StepFilter:
    """Inclusive step-index range for filtering rendered output."""

    start: int
    end: int

    def contains(self, step: int) -> bool:
        """Return True if ``step`` falls inside this filter's range."""
        return self.start <= step <= self.end


@dataclass(frozen=True)
class _Palette:
    """ANSI color codes per role, or empty strings when colors are off."""

    user: str
    assistant: str
    thinking: str
    tool_call: str
    tool_result: str
    dim: str
    reset: str

    @classmethod
    def disabled(cls) -> _Palette:
        """Return a palette with no escape codes (color disabled)."""
        return cls("", "", "", "", "", "", "")

    @classmethod
    def ansi(cls) -> _Palette:
        """Return a palette using ANSI escape codes for terminals."""
        return cls(
            user="\x1b[36m",  # cyan
            assistant="\x1b[32m",  # green
            thinking="\x1b[2;33m",  # dim yellow
            tool_call="\x1b[35m",  # magenta
            tool_result="",
            dim="\x1b[2m",
            reset="\x1b[0m",
        )

    def color_for(self, role_name: str) -> str:
        """Return the color code for a role label, or '' if unknown."""
        return {
            "user": self.user,
            "assistant": self.assistant,
            "tool_result": self.tool_result,
        }.get(role_name, "")

    def wrap(self, color: str, text: str) -> str:
        """Wrap ``text`` in the given color code; no-op if color is empty."""
        if not color:
            return text
        return f"{color}{text}{self.reset}"


def _resolve_palette() -> _Palette:
    """Decide whether to emit ANSI colors based on TTY detection.

    Color is on for terminal stdout and off otherwise (capsys, pipes,
    redirected output). There is no opt-out flag — when colors leak into
    a non-TTY consumer, that consumer is misclassifying its sink.
    """
    if not sys.stdout.isatty():
        return _Palette.disabled()
    return _Palette.ansi()


def _step_marker(step_index: int, *, width: int, palette: _Palette) -> str:
    """Render a dim, zero-padded ``s<NN>`` step anchor for a compact bullet.

    The label says "step" rather than "turn" because each pi
    ``turn_start`` event corresponds to one inference step in the agent
    loop (a single LLM round-trip, often capped by a tool call), not a
    user→assistant conversational turn. Padding is computed once per
    log so widths line up across the run.
    """
    raw = f"s{step_index:0{width}d}"
    if palette.dim:
        return f"{palette.dim}{raw}{palette.reset}"
    return raw


def detect_runtime(log_path: Path) -> RuntimeKind:
    """Sniff the first JSON events to identify the producing runtime.

    Reads up to ``_SCAN_LINES_FOR_DETECTION`` lines, decodes each as
    JSON, and returns the first runtime whose signature set contains
    the line's ``type`` field. Falls back to ``"unknown"`` if no
    signature matches — typically an empty file or a CLI banner.

    Args:
        log_path: Path to the ``native.log`` file.

    Returns:
        ``"pi"``, ``"claude_code"``, or ``"unknown"``.
    """
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for _, raw in zip(range(_SCAN_LINES_FOR_DETECTION), fh, strict=False):
            line = raw.strip()
            if not line:
                continue
            try:
                event_raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event_raw, dict):
                continue
            event = cast(dict[str, Any], event_raw)
            event_type = event.get("type")
            if not isinstance(event_type, str):
                continue
            if event_type in _PI_SIGNATURES:
                return "pi"
            if event_type in _CLAUDE_SIGNATURES:
                return "claude_code"
    return "unknown"


def _iter_events(log_path: Path) -> list[dict[str, Any]]:
    """Read all decodable JSON-object lines from ``log_path``.

    Lines that fail to parse, decode to non-objects, or are blank are
    silently dropped — matches the tolerance of the production parser
    in ``harness.runtimes.pi``.
    """
    events: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                event_raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event_raw, dict):
                events.append(cast(dict[str, Any], event_raw))
    return events


def _truncate(
    text: str,
    max_chars: int,
    *,
    full: bool,
    palette: _Palette,
) -> str:
    """Shrink long blocks with a "…" leader and size annotation.

    The truncation marker lives on its own line so it never gets visually
    fused with the content. When the palette has a ``dim`` code, the
    marker is dimmed to draw the eye to the surviving text.
    """
    if full or len(text) <= max_chars:
        return text
    head = text[:max_chars].rstrip()
    marker = f"… [truncated, {len(text)} chars total]"
    if palette.dim:
        marker = f"{palette.dim}{marker}{palette.reset}"
    return f"{head}\n{marker}"


def _truncate_inline(text: str, max_chars: int) -> str:
    """Collapse whitespace and truncate to ``max_chars`` with a ``…`` marker."""
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    return flat[: max_chars - 1] + "…"


def _tildify(path: str) -> str:
    """Replace HOME prefix with ``~`` for compact path readability."""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def _indent(text: str, prefix: str = "    ") -> str:
    """Prefix every line of ``text`` with ``prefix``."""
    return "\n".join(prefix + line for line in text.splitlines())


def _first_nonblank_line(text: str, max_chars: int) -> str:
    """Return the first non-blank stripped line, ``…``-truncated."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            if len(stripped) > max_chars:
                return stripped[:max_chars] + "…"
            return stripped
    return ""


# ---------------------------------------------------------------------------
# Per-tool argument formatters (used by the verbose `--detail` renderer).
# ---------------------------------------------------------------------------


def _format_bash_args(arguments: dict[str, Any]) -> str | None:
    """Bash → ``$ <command>`` if a string command is present."""
    cmd = arguments.get("command")
    if isinstance(cmd, str):
        return f"$ {cmd}"
    return None


def _format_read_args(arguments: dict[str, Any]) -> str | None:
    """Read → ``<path>  (offset=N, limit=M)`` (extras only when present)."""
    path_value = arguments.get("file_path") or arguments.get("path")
    if not isinstance(path_value, str):
        return None
    extras: list[str] = []
    offset = arguments.get("offset")
    limit = arguments.get("limit")
    if isinstance(offset, int):
        extras.append(f"offset={offset}")
    if isinstance(limit, int):
        extras.append(f"limit={limit}")
    if extras:
        return f"{path_value}  ({', '.join(extras)})"
    return path_value


def _format_write_args(arguments: dict[str, Any]) -> str | None:
    """Write → ``<path>`` plus the first ``_WRITE_PREVIEW_LINES`` of content."""
    path_value = arguments.get("file_path") or arguments.get("path")
    if not isinstance(path_value, str):
        return None
    content = arguments.get("content")
    if not isinstance(content, str) or not content:
        return path_value
    lines = content.splitlines()
    preview = "\n".join(lines[:_WRITE_PREVIEW_LINES])
    if len(lines) > _WRITE_PREVIEW_LINES:
        preview += f"\n… [{len(lines) - _WRITE_PREVIEW_LINES} more lines]"
    return f"{path_value}\n{preview}"


def _format_edit_args(arguments: dict[str, Any]) -> str | None:
    """Edit → ``<path>`` plus one-line ``-`` / ``+`` previews of old/new."""
    path_value = arguments.get("file_path") or arguments.get("path")
    if not isinstance(path_value, str):
        return None
    parts = [path_value]
    old = arguments.get("old_string")
    new = arguments.get("new_string")
    if isinstance(old, str) and old:
        parts.append(f"- {_first_nonblank_line(old, _EDIT_LINE_PREVIEW_CHARS)}")
    if isinstance(new, str) and new:
        parts.append(f"+ {_first_nonblank_line(new, _EDIT_LINE_PREVIEW_CHARS)}")
    return "\n".join(parts)


def _format_pattern_args(arguments: dict[str, Any]) -> str | None:
    """Grep/Glob → ``<pattern>  in <path>`` when both are strings."""
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str):
        return None
    path_value = arguments.get("path") or arguments.get("file_path")
    if isinstance(path_value, str):
        return f"{pattern}  in {path_value}"
    return pattern


_TOOL_FORMATTERS: Final[dict[str, _ToolFormatter]] = {
    "bash": _format_bash_args,
    "read": _format_read_args,
    "write": _format_write_args,
    "edit": _format_edit_args,
    "grep": _format_pattern_args,
    "glob": _format_pattern_args,
}


def _format_tool_call_args(name: str, arguments: dict[str, Any]) -> str:
    """Pretty-print arguments for known tools; fall back to compact JSON.

    Recognized tools: ``bash`` (command only), ``read`` (path with
    optional offset/limit), ``write`` (path + first 10 lines of content),
    ``edit`` (path + one-line preview of old/new), ``grep`` / ``glob``
    (pattern + path). Anything else is rendered as multi-line JSON.

    Tool names are matched case-insensitively to handle both the
    pi-canonical lowercase form and Claude-Code's TitleCase.
    """
    if not arguments:
        return "(no arguments)"
    formatter = _TOOL_FORMATTERS.get(name.lower())
    if formatter is not None:
        rendered = formatter(arguments)
        if rendered is not None:
            return rendered
    return json.dumps(arguments, indent=2, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Per-tool compact (one-line) summarizers used by the default renderer.
# ---------------------------------------------------------------------------


def _compact_bash(arguments: dict[str, Any]) -> str | None:
    cmd = arguments.get("command")
    return cmd if isinstance(cmd, str) else None


def _compact_read(arguments: dict[str, Any]) -> str | None:
    path_value = arguments.get("file_path") or arguments.get("path")
    if not isinstance(path_value, str):
        return None
    display = _tildify(path_value)
    offset = arguments.get("offset")
    limit = arguments.get("limit")
    if isinstance(offset, int) and isinstance(limit, int):
        display = f"{display}:{offset}-{offset + limit - 1}"
    elif isinstance(offset, int):
        display = f"{display}:{offset}-"
    return display


def _compact_path_only(arguments: dict[str, Any]) -> str | None:
    path_value = arguments.get("file_path") or arguments.get("path")
    if isinstance(path_value, str):
        return _tildify(path_value)
    return None


def _compact_pattern(arguments: dict[str, Any]) -> str | None:
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str):
        return None
    path_value = arguments.get("path") or arguments.get("file_path")
    if isinstance(path_value, str):
        return f"{pattern} in {_tildify(path_value)}"
    return pattern


_COMPACT_TOOL_SUMMARIZERS: Final[dict[str, _ToolFormatter]] = {
    "bash": _compact_bash,
    "read": _compact_read,
    "write": _compact_path_only,
    "edit": _compact_path_only,
    "grep": _compact_pattern,
    "glob": _compact_pattern,
}


def _compact_tool_summary(
    name: str,
    arguments: dict[str, Any],
    *,
    max_chars: int,
) -> str:
    """Render a tool call as a single ``[name: <preview>]`` token."""
    summarizer = _COMPACT_TOOL_SUMMARIZERS.get(name.lower())
    inner: str | None = None
    if summarizer is not None:
        inner = summarizer(arguments)
    if inner is None:
        inner = json.dumps(arguments, ensure_ascii=False) if arguments else "(no args)"
    label = name.lower()
    # Budget: the brackets and `name: ` prefix already consume some chars.
    prefix_len = len(label) + 4  # "[" + name + ": " + "]"
    inner_budget = max(8, max_chars - prefix_len)
    return f"[{label}: {_truncate_inline(inner, inner_budget)}]"


# ---------------------------------------------------------------------------
# Common helpers shared by both renderers.
# ---------------------------------------------------------------------------


def _flatten_tool_result_content(content: Any) -> str:
    """Concatenate ``toolResult.content`` blocks into a single string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for entry in cast(list[Any], content):
            if isinstance(entry, dict):
                entry_dict = cast(dict[str, Any], entry)
                if entry_dict.get("type") == "text":
                    text_value = entry_dict.get("text")
                    if isinstance(text_value, str):
                        chunks.append(text_value)
                        continue
                chunks.append(json.dumps(entry_dict, ensure_ascii=False))
            elif isinstance(entry, str):
                chunks.append(entry)
        return "".join(chunks)
    return json.dumps(content, ensure_ascii=False)


def _format_usage(usage: dict[str, Any] | None, *, show_full: bool) -> str:
    """Render the per-message ``usage`` block as a compact string.

    Default shows just ``tok=N`` for output tokens (the part the reader
    typically cares about). With ``show_full=True`` the input/output and
    cache-read/cache-write counts are included.
    """
    if not usage:
        return ""
    if show_full:
        parts: list[str] = []
        for key in ("input", "output", "cacheRead", "cacheWrite"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and value:
                parts.append(f"{key}={int(value)}")
        return " ".join(parts)
    output_value = usage.get("output")
    if isinstance(output_value, (int, float)) and output_value:
        return f"tok={int(output_value)}"
    return ""


def _coerce_block_list(content: Any) -> list[dict[str, Any]]:
    """Normalize a ``message.content`` payload to a list of dict blocks."""
    if not isinstance(content, list):
        return []
    return [
        cast(dict[str, Any], block) for block in cast(list[Any], content) if isinstance(block, dict)
    ]


def _filter_blocks_for_tool(
    blocks: list[dict[str, Any]],
    tool_name: str,
) -> list[dict[str, Any]]:
    """Keep assistant blocks that are non-toolCall or match ``tool_name``."""
    out: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("type") != "toolCall":
            out.append(block)
            continue
        if str(block.get("name", "")) == tool_name:
            out.append(block)
    return out


@dataclass(frozen=True)
class _RenderOptions:
    """Per-call switches threaded through the pi-renderer helpers."""

    full: bool
    max_chars: int
    tool: str | None
    palette: _Palette
    show_prompt: bool
    show_usage: bool
    detail: bool
    hide_tools: bool
    show_thinking: bool
    expand: bool
    step_width: int


# ---------------------------------------------------------------------------
# Compact renderer (default) — one line per event.
# ---------------------------------------------------------------------------


def _compact_text_bullet(
    *,
    step_index: int,
    role_label: str,
    color: str,
    text: str,
    opts: _RenderOptions,
) -> list[str]:
    """Emit one bullet for a text-bearing block (user / assistant / thinking).

    In default compact mode the body collapses to a single inline preview;
    with ``opts.expand`` the bullet head sits on its own line followed by
    the indented full body.
    """
    palette = opts.palette
    marker = _step_marker(step_index, width=opts.step_width, palette=palette)
    label = palette.wrap(color, role_label)
    if opts.expand:
        return [f"{marker} • {label}:", _indent(text)]
    preview = _truncate_inline(text, _COMPACT_LINE_CHARS)
    return [f"{marker} • {label}: {preview}"]


def _compact_user_lines(
    blocks: list[dict[str, Any]],
    *,
    step_index: int,
    opts: _RenderOptions,
) -> list[str]:
    """Emit ``s<NN> • user: …`` bullets for each non-empty text block."""
    out: list[str] = []
    for block in blocks:
        if block.get("type") != "text":
            continue
        text_value = block.get("text")
        if not isinstance(text_value, str) or not text_value:
            continue
        out.extend(
            _compact_text_bullet(
                step_index=step_index,
                role_label="user",
                color=opts.palette.user,
                text=text_value,
                opts=opts,
            )
        )
    return out


def _compact_assistant_lines(
    blocks: list[dict[str, Any]],
    *,
    step_index: int,
    opts: _RenderOptions,
) -> list[str]:
    """Emit column-zero bullets for assistant text/thinking/tool-call blocks."""
    out: list[str] = []
    palette = opts.palette
    marker = _step_marker(step_index, width=opts.step_width, palette=palette)
    for block in blocks:
        btype = block.get("type")
        if btype == "thinking":
            if not opts.show_thinking:
                continue
            text_value = block.get("thinking") or block.get("text")
            if isinstance(text_value, str) and text_value:
                out.extend(
                    _compact_text_bullet(
                        step_index=step_index,
                        role_label="thinking",
                        color=palette.thinking,
                        text=text_value,
                        opts=opts,
                    )
                )
        elif btype == "text":
            text_value = block.get("text")
            if isinstance(text_value, str) and text_value:
                out.extend(
                    _compact_text_bullet(
                        step_index=step_index,
                        role_label="assistant",
                        color=palette.assistant,
                        text=text_value,
                        opts=opts,
                    )
                )
        elif btype == "toolCall":
            if opts.hide_tools:
                continue
            name = str(block.get("name", "?"))
            args_value = block.get("arguments")
            arguments = cast(dict[str, Any], args_value) if isinstance(args_value, dict) else {}
            if opts.expand:
                head = palette.wrap(palette.tool_call, f"[{name.lower()}]")
                out.append(f"{marker} • {head}:")
                out.append(_indent(_format_tool_call_args(name, arguments)))
            else:
                summary = _compact_tool_summary(name, arguments, max_chars=_COMPACT_LINE_CHARS)
                styled = palette.wrap(palette.tool_call, summary)
                out.append(f"{marker} • {styled}")
    return out


def _compact_tool_result_lines(
    message: dict[str, Any],
    *,
    step_index: int,
    opts: _RenderOptions,
) -> list[str]:
    """Emit a ``s<NN> • result …`` bullet for a tool-result message (expand only)."""
    palette = opts.palette
    marker = _step_marker(step_index, width=opts.step_width, palette=palette)
    is_error = bool(message.get("isError", False))
    output = _flatten_tool_result_content(message.get("content"))
    label_text = "result [error]" if is_error else "result"
    label = palette.wrap(palette.tool_call, label_text)
    if not output:
        return [f"{marker} • {label}: (empty)"]
    return [f"{marker} • {label}:", _indent(output)]


def _render_pi_compact(
    events: list[dict[str, Any]],
    *,
    step_filter: StepFilter | None,
    opts: _RenderOptions,
) -> list[str]:
    """Render the pi event stream as one-line bullets (default mode).

    Each ``turn_start`` from the pi stream is rendered as one ``s<N>``
    inference step (one LLM round-trip). Tool-result messages are
    dropped in default compact mode; ``expand=True`` brings them back so
    users can see the full output of each call inline.
    """
    lines: list[str] = []
    step_index = 0
    for event in events:
        event_type = event.get("type")
        if event_type == "turn_start":
            step_index += 1
            continue
        if event_type != "message_end":
            continue
        effective_step = max(step_index, 1)
        if step_filter is not None and not step_filter.contains(effective_step):
            continue
        message_raw = event.get("message")
        if not isinstance(message_raw, dict):
            continue
        message = cast(dict[str, Any], message_raw)
        role = message.get("role")
        if role == "user":
            blocks = _coerce_block_list(message.get("content"))
            lines.extend(_compact_user_lines(blocks, step_index=effective_step, opts=opts))
        elif role == "assistant":
            blocks = _coerce_block_list(message.get("content"))
            if opts.tool is not None:
                if not any(
                    block.get("type") == "toolCall" and str(block.get("name", "")) == opts.tool
                    for block in blocks
                ):
                    continue
                blocks = _filter_blocks_for_tool(blocks, opts.tool)
            lines.extend(_compact_assistant_lines(blocks, step_index=effective_step, opts=opts))
        elif role == "toolResult" and opts.expand and not opts.hide_tools:
            lines.extend(_compact_tool_result_lines(message, step_index=effective_step, opts=opts))
    return lines


# ---------------------------------------------------------------------------
# Detail renderer (--detail) — full per-section verbose layout.
# ---------------------------------------------------------------------------


def _render_pi_session_header(event: dict[str, Any], event_count: int) -> list[str]:
    """Format the leading ``session`` event as a banner."""
    sid = str(event.get("id", "?"))
    started = str(event.get("timestamp", "?"))
    cwd = str(event.get("cwd", "?"))
    return [
        "=" * 72,
        f"pi native.log  ·  session {sid}",
        f"  started: {started}",
        f"  cwd:     {cwd}",
        f"  events:  {event_count}",
        "=" * 72,
        "",
    ]


def _detail_user_text_blocks(
    blocks: list[dict[str, Any]],
    *,
    opts: _RenderOptions,
) -> list[str]:
    """Render a user-role ``message_end`` content list."""
    out: list[str] = []
    for block in blocks:
        if block.get("type") != "text":
            continue
        text_value = block.get("text")
        if not isinstance(text_value, str) or not text_value:
            continue
        out.append(_truncate(text_value, opts.max_chars, full=opts.full, palette=opts.palette))
    return out


def _detail_assistant_blocks(
    blocks: list[dict[str, Any]],
    *,
    opts: _RenderOptions,
) -> list[str]:
    """Render an assistant-role ``message_end`` content list."""
    out: list[str] = []
    palette = opts.palette
    for block in blocks:
        block_type = block.get("type")
        if block_type == "thinking":
            text_value = block.get("thinking") or block.get("text")
            if isinstance(text_value, str) and text_value:
                out.append(palette.wrap(palette.thinking, "· thinking"))
                out.append(
                    _indent(_truncate(text_value, opts.max_chars, full=opts.full, palette=palette))
                )
        elif block_type == "text":
            text_value = block.get("text")
            if isinstance(text_value, str) and text_value:
                out.append("· text")
                out.append(
                    _indent(_truncate(text_value, opts.max_chars, full=opts.full, palette=palette))
                )
        elif block_type == "toolCall":
            name = str(block.get("name", "?"))
            call_id = str(block.get("id", "?"))
            short_id = (
                call_id[:_CALL_ID_PREVIEW_CHARS] + "…"
                if len(call_id) > _CALL_ID_PREVIEW_CHARS
                else call_id
            )
            args_value = block.get("arguments")
            arguments = cast(dict[str, Any], args_value) if isinstance(args_value, dict) else {}
            label = palette.wrap(palette.tool_call, f"· call: {name}  ({short_id})")
            out.append(label)
            formatted = _format_tool_call_args(name, arguments)
            out.append(
                _indent(_truncate(formatted, opts.max_chars, full=opts.full, palette=palette))
            )
    return out


def _detail_tool_result_body(
    message: dict[str, Any],
    *,
    opts: _RenderOptions,
) -> list[str]:
    """Render a ``role=toolResult`` message body (call_id is on the call line)."""
    is_error = bool(message.get("isError", False))
    output = _flatten_tool_result_content(message.get("content"))
    status = "error" if is_error else "ok"
    head = [f"status: {status}"]
    if output:
        head.append(
            _indent(_truncate(output, opts.max_chars, full=opts.full, palette=opts.palette))
        )
    return head


def _collapse_user_preview(body: list[str], opts: _RenderOptions) -> list[str]:
    """Collapse a user-message body to a one-line preview + size hint."""
    if not body:
        return body
    full_text = "\n".join(body)
    head = _first_nonblank_line(full_text, _PROMPT_PREVIEW_CHARS)
    note = f"({len(full_text)} chars · --show-prompt to expand)"
    if opts.palette.dim:
        note = f"{opts.palette.dim}{note}{opts.palette.reset}"
    if head:
        return [f"{head}  {note}"]
    return [note]


def _detail_user_section(
    message: dict[str, Any],
    *,
    turn: int,
    msg: int,
    opts: _RenderOptions,
    is_first_user: bool,
) -> list[str]:
    """Render a user-role ``message_end`` section, or [] if filtered/empty."""
    if opts.tool is not None:
        return []
    blocks = _coerce_block_list(message.get("content"))
    body = _detail_user_text_blocks(blocks, opts=opts)
    if not body:
        return []
    if is_first_user and not opts.show_prompt:
        body = _collapse_user_preview(body, opts)
    return [_section_header(turn, msg, "user", palette=opts.palette), *body, ""]


def _detail_assistant_section(
    message: dict[str, Any],
    *,
    turn: int,
    msg: int,
    opts: _RenderOptions,
    rendered_call_ids: set[str],
) -> list[str]:
    """Render an assistant-role ``message_end`` section, or [] if filtered/empty."""
    blocks = _coerce_block_list(message.get("content"))
    if opts.tool is not None:
        if not any(
            block.get("type") == "toolCall" and str(block.get("name", "")) == opts.tool
            for block in blocks
        ):
            return []
        blocks = _filter_blocks_for_tool(blocks, opts.tool)
    body = _detail_assistant_blocks(blocks, opts=opts)
    if not body:
        return []
    for block in blocks:
        if block.get("type") == "toolCall":
            call_id = str(block.get("id", ""))
            if call_id:
                rendered_call_ids.add(call_id)
    usage_raw = message.get("usage")
    usage = cast(dict[str, Any], usage_raw) if isinstance(usage_raw, dict) else None
    suffix = _format_usage(usage, show_full=opts.show_usage)
    return [
        _section_header(turn, msg, "assistant", suffix=suffix, palette=opts.palette),
        *body,
        "",
    ]


def _detail_tool_result_section(
    message: dict[str, Any],
    *,
    turn: int,
    msg: int,
    opts: _RenderOptions,
    rendered_call_ids: set[str],
) -> list[str]:
    """Render a toolResult-role ``message_end`` section, or [] if filtered."""
    if opts.tool is not None:
        call_id = str(message.get("toolCallId", ""))
        if call_id not in rendered_call_ids:
            return []
    body = _detail_tool_result_body(message, opts=opts)
    return [
        _section_header(turn, msg, "tool_result", palette=opts.palette),
        *body,
        "",
    ]


def _section_header(
    turn: int,
    msg: int,
    role: str,
    *,
    suffix: str = "",
    palette: _Palette | None = None,
) -> str:
    """Build a ``──── turn N / msg M · role · suffix ────`` divider.

    The role token is colorized when the palette has a code for it; the
    bar width is computed from the *raw* (unstyled) label so ANSI escape
    sequences don't throw off the column count.
    """
    palette_value = palette if palette is not None else _Palette.disabled()
    color = palette_value.color_for(role)
    role_styled = palette_value.wrap(color, role)

    raw_label = f"turn {turn} / msg {msg} · {role}"
    styled_label = f"turn {turn} / msg {msg} · {role_styled}"
    if suffix:
        raw_label = f"{raw_label} · {suffix}"
        styled_label = f"{styled_label} · {suffix}"
    bar = "─" * max(4, 72 - len(raw_label) - 6)
    return f"──── {styled_label} {bar}"


def _render_pi_detail(
    events: list[dict[str, Any]],
    *,
    step_filter: StepFilter | None,
    opts: _RenderOptions,
) -> list[str]:
    """Render the pi event stream in the verbose per-section layout."""
    lines: list[str] = []
    if events and events[0].get("type") == "session":
        lines.extend(_render_pi_session_header(events[0], len(events)))

    rendered_call_ids: set[str] = set()
    turn_index = 0
    msg_index = 0
    user_seen = False

    for event in events:
        event_type = event.get("type")
        if event_type == "turn_start":
            turn_index += 1
            continue
        if event_type != "message_end":
            continue
        msg_index += 1
        if step_filter is not None and not step_filter.contains(max(turn_index, 1)):
            continue
        message_raw = event.get("message")
        if not isinstance(message_raw, dict):
            continue
        message = cast(dict[str, Any], message_raw)
        role = message.get("role")
        if role == "user":
            is_first = not user_seen
            user_seen = True
            lines.extend(
                _detail_user_section(
                    message,
                    turn=turn_index,
                    msg=msg_index,
                    opts=opts,
                    is_first_user=is_first,
                )
            )
        elif role == "assistant":
            lines.extend(
                _detail_assistant_section(
                    message,
                    turn=turn_index,
                    msg=msg_index,
                    opts=opts,
                    rendered_call_ids=rendered_call_ids,
                )
            )
        elif role == "toolResult":
            if opts.hide_tools:
                continue
            lines.extend(
                _detail_tool_result_section(
                    message,
                    turn=turn_index,
                    msg=msg_index,
                    opts=opts,
                    rendered_call_ids=rendered_call_ids,
                )
            )
    return lines


# ---------------------------------------------------------------------------
# Top-level public entry points.
# ---------------------------------------------------------------------------


def render_pi(
    log_path: Path,
    *,
    step_filter: StepFilter | None,
    full: bool,
    max_chars: int,
    tool: str | None,
    palette: _Palette | None = None,
    show_prompt: bool = False,
    show_usage: bool = False,
    detail: bool = False,
    hide_tools: bool = False,
    show_thinking: bool = False,
    expand: bool = False,
) -> str:
    """Render a ``pi`` native.log as a multi-line trajectory string.

    By default emits a compact, one-line-per-event summary suitable for
    skimming what an agent did. Pass ``detail=True`` for the full
    per-section verbose layout (section headers, full block bodies,
    truncation marker, tool-result status, usage, etc.).

    Drops streaming delta events (``message_update``, ``toolcall_delta``,
    etc.) and renders one section per ``message_end``. Step indices are
    derived from the count of ``turn_start`` events seen so far (one
    pi turn = one inference step in the agent loop).

    Args:
        log_path: Path to the ``native.log``.
        step_filter: Optional inclusive step-index range; messages
            outside the range are skipped.
        full: When True, never truncate block text in detail mode.
        max_chars: Per-block truncation budget for detail mode when
            ``full`` is False. Ignored in compact mode.
        tool: Optional tool-name filter; restricts assistant tool-call
            blocks (and matching tool results in detail mode) to this
            tool.
        palette: Color palette to use; defaults to disabled (no ANSI).
        show_prompt: Detail mode only — when True, the first user
            message is rendered in full instead of collapsed.
        show_usage: Detail mode only — when True, the assistant header
            includes input/cacheRead/cacheWrite counts.
        detail: When True, switch to the verbose per-section renderer.
        hide_tools: When True, drop tool-call (and tool-result) lines —
            useful when you only want to see user/assistant messages.
        show_thinking: Compact mode only — include thinking blocks as
            their own bullets.
        expand: Compact mode only — render full message bodies under
            each bullet instead of inline-collapsed previews. Tool-result
            messages are also surfaced in this mode.

    Returns:
        The fully rendered output, ready to write to stdout.
    """
    events = _iter_events(log_path)
    palette_value = palette if palette is not None else _Palette.disabled()
    step_count = sum(1 for e in events if e.get("type") == "turn_start")
    step_width = max(2, len(str(max(step_count, 1))))
    opts = _RenderOptions(
        full=full,
        max_chars=max_chars,
        tool=tool,
        palette=palette_value,
        show_prompt=show_prompt,
        show_usage=show_usage,
        detail=detail,
        hide_tools=hide_tools,
        show_thinking=show_thinking,
        expand=expand,
        step_width=step_width,
    )
    if detail:
        lines = _render_pi_detail(events, step_filter=step_filter, opts=opts)
    else:
        lines = _render_pi_compact(events, step_filter=step_filter, opts=opts)
    return "\n".join(lines)


def render_claude_code_placeholder(log_path: Path) -> str:
    """Return a stable placeholder string for the un-implemented Claude Code path."""
    return (
        f"Claude Code log inspection is not yet implemented.\n"
        f"Detected a Claude Code stream-json log at: {log_path}\n"
        f"See packages/harness/src/harness/runtimes/claude_code.py for the schema.\n"
    )


def _parse_step_filter(spec: str) -> StepFilter:
    """Parse ``--step`` argument into an inclusive ``StepFilter``.

    Accepts a single integer (``"3"``) or a hyphenated range (``"2-5"``).
    Raises ``argparse.ArgumentTypeError`` for malformed inputs.
    """
    if "-" in spec:
        start_raw, end_raw = spec.split("-", 1)
    else:
        start_raw = end_raw = spec
    try:
        start = int(start_raw)
        end = int(end_raw)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"invalid step range: {spec!r}") from err
    if start < 1 or end < start:
        raise argparse.ArgumentTypeError(f"invalid step range: {spec!r}")
    return StepFilter(start=start, end=end)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Build and parse the argparse namespace for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Pretty-print a harness native.log (auto-detects pi vs claude_code). "
            "Default is a compact summary; use --detail for the full verbose view."
        ),
    )
    parser.add_argument("log_path", type=Path, help="Path to native.log")
    parser.add_argument(
        "--step",
        type=_parse_step_filter,
        default=None,
        help="Restrict output to step N or range N-M (1-indexed, inclusive).",
    )
    parser.add_argument(
        "--tool",
        type=str,
        default=None,
        help="Restrict to assistant tool-calls (and matching results in --detail) for this tool.",
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Hide tool-call (and tool-result) lines; show only user/assistant messages.",
    )
    parser.add_argument(
        "--show-thinking",
        action="store_true",
        help="Compact mode: include assistant thinking blocks as their own bullets.",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Switch to the verbose per-section layout (section headers, full bodies).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Detail mode: disable per-block truncation; emit every block in full.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=_DEFAULT_MAX_CHARS,
        help=(
            "Detail mode: per-block truncation budget when --full is not set "
            f"(default: {_DEFAULT_MAX_CHARS})."
        ),
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        help=(
            "Compact mode: render full message bodies under each bullet "
            "(no inline truncation; tool results are surfaced too)."
        ),
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Detail mode: render the first user message in full instead of collapsing.",
    )
    parser.add_argument(
        "--show-usage",
        action="store_true",
        help="Detail mode: include input and cache token counts in assistant headers.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point: detect runtime, render, write to stdout."""
    args = _parse_args(argv)
    log_path = cast(Path, args.log_path)
    if not log_path.is_file():
        print(f"error: not a file: {log_path}", file=sys.stderr)
        return 1
    runtime = detect_runtime(log_path)
    if runtime == "pi":
        palette = _resolve_palette()
        output = render_pi(
            log_path,
            step_filter=cast("StepFilter | None", args.step),
            full=bool(args.full),
            max_chars=int(args.max_chars),
            tool=cast("str | None", args.tool),
            palette=palette,
            show_prompt=bool(args.show_prompt),
            show_usage=bool(args.show_usage),
            detail=bool(args.detail),
            hide_tools=bool(args.no_tools),
            show_thinking=bool(args.show_thinking),
            expand=bool(args.expand),
        )
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    if runtime == "claude_code":
        sys.stdout.write(render_claude_code_placeholder(log_path))
        return 0
    print(
        f"error: could not detect runtime from {log_path} (expected pi or claude_code stream-json)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
