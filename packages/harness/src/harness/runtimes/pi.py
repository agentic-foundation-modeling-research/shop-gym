"""`pi` CLI runtime adapter (spec §5.6).

`PiRuntime` wraps the ``pi`` coding-agent CLI in non-interactive mode. For
each iteration it:

* spawns ``pi --print --mode json`` in a fresh process group, with the
  rendered prompt piped on stdin and the combined stdout/stderr stream
  tee'd to ``iter_dir/native.log``;
* parses the NDJSON event stream into normalized `TrajectoryStep`s;
* enforces the harness wall-clock timeout by killing the entire process
  group on expiry and re-raising `subprocess.TimeoutExpired`.

Unlike `ClaudeCodeRuntime`, the runtime does not symlink ``CLAUDE.md`` —
``pi`` discovers the harness anchor file natively as ``AGENTS.md`` (see
the ``--no-context-files`` CLI flag).

The native log shape matches `pi`'s documented JSON event stream
(``docs/json.md``): each line is a JSON object with a top-level ``type``
field (``session``, ``agent_start``, ``turn_start``, ``message_start``,
``message_update``, ``message_end``, ``turn_end``, ``agent_end``,
``tool_execution_start``, ``tool_execution_update``,
``tool_execution_end``, plus compaction/retry events). The converter
distils the stream by reading only ``message_end`` events: each carries
the fully assembled message for one turn, with ``content`` blocks of
type ``text``, ``thinking``, or ``toolCall``, or — for tool results —
the role ``toolResult`` carrying ``toolCallId``/``content``/``isError``.

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
    MessageStep,
    ThoughtStep,
    ToolCallStep,
    ToolResultStep,
    Trajectory,
    TrajectoryStep,
)

_RUNTIME_NAME: Final[str] = "pi"
_NATIVE_LOG_FILENAME: Final[str] = "native.log"
_DEFAULT_BIN: Final[str] = "pi"
_KILL_GRACE_SECONDS: Final[float] = 5.0


class PiRuntime:
    """`AgentRuntime` adapter wrapping the ``pi`` CLI.

    The constructor takes no required arguments; ``binary`` and ``model``
    are exposed so tests, packaging, and synthesis callers can override
    the executable name and pin the underlying model without forking.

    Attributes:
        binary: Executable name or absolute path of the ``pi`` CLI.
        model: Model identifier forwarded to the CLI as ``--model``, or
            ``None`` to let ``pi`` pick its default. ``pi`` accepts
            patterns (``sonnet:high``), provider-prefixed IDs
            (``anthropic/claude-sonnet-4-6``), and bare names.
    """

    def __init__(
        self,
        *,
        binary: str = _DEFAULT_BIN,
        model: str | None = None,
    ) -> None:
        """Initialise a runtime backed by ``binary``.

        Args:
            binary: Executable name or absolute path of the ``pi`` CLI.
                Defaults to ``"pi"`` (resolved via ``PATH``).
            model: Optional model identifier forwarded to ``pi`` as
                ``--model <model>``. Defaults to ``None``, which lets
                ``pi`` pick its built-in default and preserves the
                pre-T6.1 invocation shape.
        """
        self._binary = binary
        self._model = model

    @property
    def binary(self) -> str:
        """Executable name or path of the ``pi`` CLI."""
        return self._binary

    @property
    def model(self) -> str | None:
        """Model identifier forwarded as ``--model``, or ``None`` for default."""
        return self._model

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Run one ``pi`` iteration synchronously.

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
        log_path = iter_dir / _NATIVE_LOG_FILENAME
        argv = build_argv(binary=self._binary, model=self._model)
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
# CLI argv builder
# ---------------------------------------------------------------------------


def build_argv(*, binary: str, model: str | None) -> list[str]:
    """Build the ``pi`` invocation argv for a single non-interactive iteration.

    Args:
        binary: Executable name or absolute path of the ``pi`` CLI.
        model: Optional model identifier forwarded as ``--model``. When
            ``None``, the flag is omitted and ``pi`` uses its built-in
            default (preserving the pre-T6.1 invocation shape).

    Returns:
        The argv list ready to pass to `subprocess.Popen`.
    """
    argv = [binary, "--print", "--mode", "json"]
    if model is not None:
        argv.extend(["--model", model])
    return argv


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
    """Convert a ``pi`` JSON-mode native log into trajectory steps.

    Lines that fail JSON decoding (CLI banners, partial writes after a
    kill, or stderr noise) are skipped. Unknown event ``type`` values and
    unknown content-block ``type`` values are also skipped — callers
    should treat the conversion as best-effort against an
    intentionally-evolving CLI surface.

    Args:
        log_path: Path to the captured ``native.log``. Missing file
            yields an empty list.
        timestamp: Timestamp to stamp on every emitted step. ``pi``'s
            event stream does carry per-event timestamps, but the
            harness uses the iteration's ``started_at`` to keep step
            ordering by insertion only and to match the converter
            contract used by the other runtimes.

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
    """Convert one JSON-mode event to zero or more trajectory steps.

    Only ``message_end`` events carry trajectory-shaped payload: each
    one represents a fully assembled assistant/user/toolResult message.
    Lifecycle events (``agent_start``, ``turn_start``/``turn_end``,
    ``agent_end``), the ``session`` header, the streaming
    ``message_start``/``message_update`` deltas, the
    ``tool_execution_*`` events, and compaction/retry events are
    intentionally dropped — their content is duplicated by the
    corresponding ``message_end`` event.
    """
    if event.get("type") != "message_end":
        return []
    message_raw = event.get("message")
    if not isinstance(message_raw, dict):
        return []
    message = cast(dict[str, Any], message_raw)
    role = message.get("role")
    if role == "toolResult":
        return _tool_result_message_to_steps(message, timestamp=timestamp)
    content = message.get("content")
    blocks: list[dict[str, Any]] = (
        [
            cast(dict[str, Any], block)
            for block in cast(list[Any], content)
            if isinstance(block, dict)
        ]
        if isinstance(content, list)
        else []
    )
    if role == "assistant":
        return _assistant_blocks_to_steps(blocks, timestamp=timestamp)
    if role == "user":
        return _user_blocks_to_steps(blocks, timestamp=timestamp)
    # Unknown roles fall through and are dropped.
    return []


def _assistant_blocks_to_steps(
    blocks: list[dict[str, Any]],
    *,
    timestamp: dt.datetime,
) -> list[TrajectoryStep]:
    """Convert an assistant message's content blocks to trajectory steps."""
    steps: list[TrajectoryStep] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            text = _coerce_text(block.get("text"))
            if text:
                steps.append(MessageStep(timestamp=timestamp, role="assistant", text=text))
        elif block_type == "thinking":
            text = _coerce_text(block.get("thinking") or block.get("text"))
            if text:
                steps.append(ThoughtStep(timestamp=timestamp, text=text))
        elif block_type == "toolCall":
            call_id = _coerce_text(block.get("id"))
            tool = _coerce_text(block.get("name"))
            if not call_id or not tool:
                continue
            tool_args = block.get("arguments")
            arguments: dict[str, Any] = (
                dict(cast(dict[str, Any], tool_args)) if isinstance(tool_args, dict) else {}
            )
            steps.append(
                ToolCallStep(
                    timestamp=timestamp,
                    call_id=call_id,
                    tool=tool,
                    arguments=arguments,
                )
            )
        # Unknown block types are dropped — the CLI may add new ones.
    return steps


def _user_blocks_to_steps(
    blocks: list[dict[str, Any]],
    *,
    timestamp: dt.datetime,
) -> list[TrajectoryStep]:
    """Convert a user message's content blocks to trajectory steps."""
    steps: list[TrajectoryStep] = []
    for block in blocks:
        if block.get("type") != "text":
            continue
        text = _coerce_text(block.get("text"))
        if text:
            steps.append(MessageStep(timestamp=timestamp, role="user", text=text))
    return steps


def _tool_result_message_to_steps(
    message: dict[str, Any],
    *,
    timestamp: dt.datetime,
) -> list[TrajectoryStep]:
    """Convert a ``role=toolResult`` message to a single `ToolResultStep`."""
    call_id = _coerce_text(message.get("toolCallId"))
    if not call_id:
        return []
    output = _coerce_tool_result_content(message.get("content"))
    return [
        ToolResultStep(
            timestamp=timestamp,
            call_id=call_id,
            output=output,
            is_error=bool(message.get("isError", False)),
        )
    ]


def _coerce_text(value: Any) -> str:
    """Best-effort string coercion for JSON-mode text fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _coerce_tool_result_content(value: Any) -> str:
    """Flatten a ``toolResult.content`` payload into a single string.

    ``pi`` emits ``toolResult`` messages whose ``content`` is an array
    of typed sub-blocks (``[{"type": "text", "text": "..."}]``). For
    trajectory purposes we collapse to a single string so downstream
    consumers see a stable shape regardless of the CLI's chosen
    encoding. Bare strings are also accepted as a defensive fallback.
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
