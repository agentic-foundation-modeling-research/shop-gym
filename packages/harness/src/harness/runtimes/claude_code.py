"""Claude Code CLI runtime adapter (spec §5.6).

`ClaudeCodeRuntime` wraps the ``claude`` CLI in non-interactive mode. For
each iteration it:

* ensures ``run_dir/CLAUDE.md`` is a symlink to ``AGENTS.md`` so the CLI's
  project-rules auto-load picks up the harness anchor file;
* spawns ``claude --print --output-format stream-json --verbose`` in a
  fresh process group, with the rendered prompt piped on stdin and the
  combined stdout/stderr stream tee'd to ``iter_dir/native.log``;
* parses the NDJSON event stream into normalized `TrajectoryStep`s;
* enforces the harness wall-clock timeout by killing the entire process
  group on expiry and re-raising `subprocess.TimeoutExpired`.

The native log shape matches the Claude Code CLI's documented streaming
contract: each line is a JSON object with a top-level ``type`` field
(``system``, ``user``, ``assistant``, ``result``); assistant/user messages
carry a ``message.content`` array whose entries are typed content blocks
(``text``, ``thinking``, ``tool_use``, ``tool_result``).

The runtime owns the LLM, tool selection, and in-iteration context. The
harness owns iteration lifecycle, telemetry persistence, plan parsing,
and the workspace state machine. See
`docs/specs/harness/plan_exec_loop.md` §5.6 and §5.7.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import signal
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any, Final, cast

from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import (
    ErrorStep,
    MessageStep,
    ThoughtStep,
    ToolCallStep,
    ToolResultStep,
    Trajectory,
    TrajectoryStep,
)

_RUNTIME_NAME: Final[str] = "claude_code"
_NATIVE_LOG_FILENAME: Final[str] = "native.log"
_AGENTS_FILENAME: Final[str] = "AGENTS.md"
_CLAUDE_FILENAME: Final[str] = "CLAUDE.md"
_DEFAULT_BIN: Final[str] = "claude"
_DEFAULT_MODEL: Final[str] = "claude-opus-4-7"
_KILL_GRACE_SECONDS: Final[float] = 5.0


class ClaudeCodeRuntime:
    """`AgentRuntime` adapter wrapping the Claude Code CLI.

    The constructor takes no required arguments; ``binary`` and ``model``
    are exposed so tests and packaging can override them without forking.

    Attributes:
        binary: Executable name or absolute path of the ``claude`` CLI.
        model: Model identifier passed via ``--model`` (full name like
            ``claude-opus-4-7`` or alias like ``opus``).
    """

    def __init__(
        self,
        *,
        binary: str = _DEFAULT_BIN,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        """Initialise a runtime backed by ``binary`` and ``model``.

        Args:
            binary: Executable name or absolute path of the ``claude`` CLI.
                Defaults to ``"claude"`` (resolved via ``PATH``).
            model: Model identifier passed to ``claude --model``. Defaults
                to ``"claude-opus-4-7"``. Accepts a full model name or an
                alias supported by the CLI (e.g. ``"opus"``, ``"sonnet"``).
        """
        self._binary = binary
        self._model = model

    @property
    def binary(self) -> str:
        """Executable name or path of the ``claude`` CLI."""
        return self._binary

    @property
    def model(self) -> str:
        """Model identifier passed via ``--model``."""
        return self._model

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Run one Claude Code iteration synchronously.

        Args:
            run_dir: Workspace root used as the agent's working directory.
            iter_dir: Per-iteration directory the runtime owns. Must
                already exist; the runtime writes ``native.log`` here.
            prompt: Fully rendered prompt delivered on the CLI's stdin.
            timeout: Per-iteration wall-clock budget in seconds.

        Returns:
            A `RuntimeIterationResult` carrying the normalized
            `Trajectory` for the iteration.

        Raises:
            subprocess.TimeoutExpired: When the CLI exceeds ``timeout``.
                The harness loop maps this to ``final_status=timeout``.
        """
        _ensure_claude_md_symlink(run_dir)
        log_path = iter_dir / _NATIVE_LOG_FILENAME
        argv = [
            self._binary,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self._model,
            # Headless runs cannot answer interactive permission prompts;
            # auto-accept edits so file writes inside the workspace land
            # without blocking. The harness still gates everything by the
            # subprocess-level timeout.
            "--dangerously-skip-permissions",
        ]
        started_at = _utcnow()
        exit_code = _spawn_and_capture(
            argv=argv,
            cwd=run_dir,
            prompt=prompt,
            log_path=log_path,
            timeout=timeout,
        )
        ended_at = _utcnow()

        steps = parse_native_log(log_path, timestamp=started_at)
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        trajectory = Trajectory(
            iter_id=iter_dir.name,
            runtime=_RUNTIME_NAME,
            started_at=started_at,
            ended_at=ended_at,
            exit_code=exit_code,
            prompt_sha256=prompt_sha,
            steps=tuple(steps),
        )
        return RuntimeIterationResult(trajectory=trajectory)


# ---------------------------------------------------------------------------
# Workspace setup
# ---------------------------------------------------------------------------


def _ensure_claude_md_symlink(run_dir: Path) -> None:
    """Create ``run_dir/CLAUDE.md`` → ``AGENTS.md`` if not already present.

    Idempotent: if a file or symlink at ``CLAUDE.md`` already exists we
    leave it alone. If ``AGENTS.md`` is missing we silently skip — the
    workspace setup will have already failed upstream.
    """
    target = run_dir / _CLAUDE_FILENAME
    if target.exists() or target.is_symlink():
        return
    if not (run_dir / _AGENTS_FILENAME).exists():
        return
    # Relative symlink so the workspace is portable across moves.
    os.symlink(_AGENTS_FILENAME, target)


# ---------------------------------------------------------------------------
# Subprocess driver
# ---------------------------------------------------------------------------


def _spawn_and_capture(
    *,
    argv: list[str],
    cwd: Path,
    prompt: str,
    log_path: Path,
    timeout: float,
) -> int:
    """Run ``argv`` with ``prompt`` on stdin, tee'ing output to ``log_path``.

    The child runs in a fresh process group (``start_new_session=True``)
    so a timeout can take down any descendants the CLI spawned. On
    `subprocess.TimeoutExpired` we send ``SIGTERM`` to the group, give it
    a brief grace window, then escalate to ``SIGKILL`` and re-raise.

    Returns:
        The child's exit code, or ``-1`` if it terminated without one.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log_fh:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            proc.communicate(input=prompt.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_group(proc)
            raise
        finally:
            if proc.poll() is None:
                _terminate_group(proc)
    return proc.returncode if proc.returncode is not None else -1


def _terminate_group(proc: subprocess.Popen[bytes]) -> None:
    """Send SIGTERM, then SIGKILL on grace expiry, to ``proc``'s group."""
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        proc.wait(timeout=_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=_KILL_GRACE_SECONDS)


# ---------------------------------------------------------------------------
# Native log → trajectory step converter
# ---------------------------------------------------------------------------


def parse_native_log(log_path: Path, *, timestamp: dt.datetime) -> list[TrajectoryStep]:
    """Convert a Claude Code stream-json native log into trajectory steps.

    Lines that fail JSON decoding (CLI banners, partial writes after a
    kill, or stderr noise) are skipped. Unknown event ``type`` values and
    unknown content-block ``type`` values are also skipped — callers
    should treat the conversion as best-effort against an
    intentionally-evolving CLI surface.

    Args:
        log_path: Path to the captured ``native.log``. Missing file
            yields an empty list.
        timestamp: Timestamp to stamp on every emitted step. The CLI's
            stream events do not carry per-event timestamps, so the
            harness uses the iteration's ``started_at`` for ordering by
            insertion only.

    Returns:
        Ordered list of `TrajectoryStep` instances ready for inclusion in
        a `Trajectory`.
    """
    if not log_path.is_file():
        return []
    steps: list[TrajectoryStep] = []
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event_raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event_raw, dict):
                continue
            event = cast(dict[str, Any], event_raw)
            steps.extend(_event_to_steps(event, timestamp=timestamp))
    return steps


def _event_to_steps(
    event: dict[str, Any],
    *,
    timestamp: dt.datetime,
) -> list[TrajectoryStep]:
    """Convert one stream-json event to zero or more trajectory steps."""
    event_type = event.get("type")
    if event_type == "assistant":
        return _content_blocks_to_steps(
            _extract_content(event), role="assistant", timestamp=timestamp
        )
    if event_type == "user":
        return _content_blocks_to_steps(_extract_content(event), role="user", timestamp=timestamp)
    if event_type == "result":
        # The terminal `result` event is a summary of the run that
        # duplicates content already streamed. Surface only its error
        # state so a failed iteration still carries an explicit step.
        if event.get("is_error") is True:
            message = _coerce_text(event.get("error") or event.get("result") or "result error")
            return [ErrorStep(timestamp=timestamp, message=message)]
        return []
    # `system` (init/config) and any unrecognised top-level event types
    # are intentionally dropped; they carry no trajectory-shaped payload.
    return []


def _extract_content(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``message.content`` block list for an assistant/user event."""
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = cast(dict[str, Any], message).get("content")
    if not isinstance(content, list):
        return []
    return [
        cast(dict[str, Any], block) for block in cast(list[Any], content) if isinstance(block, dict)
    ]


def _content_blocks_to_steps(
    blocks: list[dict[str, Any]],
    *,
    role: str,
    timestamp: dt.datetime,
) -> list[TrajectoryStep]:
    """Convert one content-block list to ordered trajectory steps."""
    steps: list[TrajectoryStep] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            text = _coerce_text(block.get("text"))
            if not text:
                continue
            if role == "assistant":
                steps.append(MessageStep(timestamp=timestamp, role="assistant", text=text))
            elif role == "user":
                steps.append(MessageStep(timestamp=timestamp, role="user", text=text))
            # Unknown roles fall through and are dropped.
        elif block_type == "thinking":
            text = _coerce_text(block.get("thinking") or block.get("text"))
            if text:
                steps.append(ThoughtStep(timestamp=timestamp, text=text))
        elif block_type == "tool_use":
            call_id = _coerce_text(block.get("id"))
            tool = _coerce_text(block.get("name"))
            if not call_id or not tool:
                continue
            tool_input = block.get("input")
            arguments: dict[str, Any] = (
                dict(cast(dict[str, Any], tool_input)) if isinstance(tool_input, dict) else {}
            )
            steps.append(
                ToolCallStep(
                    timestamp=timestamp,
                    call_id=call_id,
                    tool=tool,
                    arguments=arguments,
                )
            )
        elif block_type == "tool_result":
            call_id = _coerce_text(block.get("tool_use_id"))
            if not call_id:
                continue
            output = _coerce_tool_result_content(block.get("content"))
            steps.append(
                ToolResultStep(
                    timestamp=timestamp,
                    call_id=call_id,
                    output=output,
                    is_error=bool(block.get("is_error", False)),
                )
            )
        # Unknown block types are dropped — the CLI may add new ones.
    return steps


def _coerce_text(value: Any) -> str:
    """Best-effort string coercion for stream-json text fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _coerce_tool_result_content(value: Any) -> str:
    """Flatten stream-json tool_result ``content`` into a single string.

    The CLI emits either a bare string or an array of typed sub-blocks
    (e.g. ``[{"type": "text", "text": "..."}]``). For trajectory
    purposes we collapse to a single string so downstream consumers see
    a stable shape regardless of the CLI's chosen encoding.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for entry in cast(list[Any], value):
            if isinstance(entry, dict):
                entry_dict = cast(dict[str, Any], entry)
                if entry_dict.get("type") == "text":
                    chunks.append(_coerce_text(entry_dict.get("text")))
                else:
                    chunks.append(_coerce_text(entry_dict))
            else:
                chunks.append(_coerce_text(entry))
        return "".join(chunks)
    return _coerce_text(value)


def _utcnow() -> dt.datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return dt.datetime.now(tz=dt.UTC)
