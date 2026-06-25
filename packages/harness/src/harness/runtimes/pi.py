"""`pi` CLI runtime adapter (spec §5.6).

`PiRuntime` wraps the ``pi`` coding-agent CLI in non-interactive mode. For
each iteration it:

* spawns ``pi --print --mode json`` in a fresh process group, with the
  rendered prompt piped on stdin and the combined stdout/stderr stream
  tee'd to ``iter_dir/native.log``;
* parses the NDJSON event stream into normalized `TrajectoryStep`s;
* enforces the harness wall-clock timeout by killing the entire process
  group on expiry and re-raising `subprocess.TimeoutExpired`.

Unlike `ClaudeCodeRuntime`, the runtime does not symlink ``CLAUDE.md``.
It disables ``pi``'s context-file walk-up and injects the harness-owned
``run_dir/AGENTS.md`` explicitly with ``--append-system-prompt`` so
parent-directory or user-global instructions cannot leak into a run.

The subprocess also runs with ``PI_CODING_AGENT_DIR`` and
``PI_CODING_AGENT_SESSION_DIR`` pointed at per-call scratch directories,
and passes ``--no-extensions --no-skills --no-prompt-templates
--no-themes``. This keeps runtime behaviour independent from the user's
personal ``~/.pi/agent`` / ``~/.agents`` resources while preserving
provider credentials supplied through the project ``.env`` or exported
environment variables.

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
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Final, cast

from dotenv import dotenv_values, find_dotenv

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
_AGENTS_FILENAME: Final[str] = "AGENTS.md"
_MODELS_FILENAME: Final[str] = "models.json"
_DEFAULT_BIN: Final[str] = "pi"
_KILL_GRACE_SECONDS: Final[float] = 5.0
_PI_AGENT_DIR_ENV: Final[str] = "PI_CODING_AGENT_DIR"
_PI_SESSION_DIR_ENV: Final[str] = "PI_CODING_AGENT_SESSION_DIR"
_ISOLATED_AGENT_DIRNAME: Final[str] = ".pi-agent"
_ISOLATED_SESSION_DIRNAME: Final[str] = ".pi-sessions"
_PI_PROXY_API_KEY_ENV: Final[str] = "PI_PROXY_API_KEY"
_ANTHROPIC_BASE_URL_ENV: Final[str] = "ANTHROPIC_BASE_URL"
_ANTHROPIC_API_KEY_ENV: Final[str] = "ANTHROPIC_API_KEY"
_OPENAI_BASE_URL_ENV: Final[str] = "OPENAI_BASE_URL"
_OPENAI_API_KEY_ENV: Final[str] = "OPENAI_API_KEY"
_MAX_ONESHOT_ERROR_CHARS: Final[int] = 4_000

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


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
        skill_paths: Sequence[Path | str] = (),
    ) -> None:
        """Initialise a runtime backed by ``binary``.

        Args:
            binary: Executable name or absolute path of the ``pi`` CLI.
                Defaults to ``"pi"`` (resolved via ``PATH``).
            model: Optional model identifier forwarded to ``pi`` as
                ``--model <model>``. Defaults to ``None``, which lets
                ``pi`` pick its built-in default and preserves the
                pre-T6.1 invocation shape.
            skill_paths: Optional explicit skill directories or files to
                load with ``--skill``. Discovery remains disabled, so
                only these caller-owned skills are available.
        """
        self._binary = binary
        self._model = model
        self._skill_paths = tuple(Path(path) for path in skill_paths)

    @property
    def binary(self) -> str:
        """Executable name or path of the ``pi`` CLI."""
        return self._binary

    @property
    def model(self) -> str | None:
        """Model identifier forwarded as ``--model``, or ``None`` for default."""
        return self._model

    @property
    def skill_paths(self) -> tuple[Path, ...]:
        """Explicit skill paths forwarded as ``--skill``."""
        return self._skill_paths

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
        argv = build_argv(
            binary=self._binary,
            model=self._model,
            agents_md=run_dir / _AGENTS_FILENAME,
            skill_paths=self._skill_paths,
        )
        agent_dir = iter_dir / _ISOLATED_AGENT_DIRNAME
        session_dir = iter_dir / _ISOLATED_SESSION_DIRNAME
        env = build_isolated_env(agent_dir=agent_dir, session_dir=session_dir)
        prepare_isolated_config(agent_dir=agent_dir, session_dir=session_dir, env=env)
        started_at = _utcnow()
        exit_code = _spawn_and_capture(
            argv=argv,
            cwd=run_dir,
            prompt=prompt,
            log_path=log_path,
            timeout=timeout,
            env=env,
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

    def complete(self, prompt: str, *, timeout: float) -> str:
        """Run a one-shot non-agent ``pi`` completion against ``prompt``.

        Implements the `LLMCompleter` Protocol from
        `harness.runtimes.base`. Spawns ``pi --print --mode text
        --no-tools --no-extensions --no-skills
        --no-prompt-templates --no-themes --no-context-files
        --no-session [--model M]`` under an isolated
        ``PI_CODING_AGENT_DIR`` so the call is a pure prompt → text
        completion against the same model the runtime drives its
        iterations with. No AGENTS.md auto-loading, no tools, no
        session persistence, no user-installed resources, no log file
        side-effects.

        Args:
            prompt: Fully rendered prompt delivered on the CLI's stdin.
            timeout: Wall-clock budget in seconds. The CLI is killed on
                expiry and `subprocess.TimeoutExpired` is re-raised.

        Returns:
            The CLI's stdout decoded as UTF-8 (replacement-mode), with
            trailing whitespace stripped. May be empty.

        Raises:
            subprocess.TimeoutExpired: When the CLI exceeds ``timeout``.
        """
        argv = build_complete_argv(binary=self._binary, model=self._model)
        with tempfile.TemporaryDirectory(prefix="shop-gym-pi-") as tmp:
            tmp_dir = Path(tmp)
            agent_dir = tmp_dir / _ISOLATED_AGENT_DIRNAME
            session_dir = tmp_dir / _ISOLATED_SESSION_DIRNAME
            env = build_isolated_env(agent_dir=agent_dir, session_dir=session_dir)
            prepare_isolated_config(
                agent_dir=agent_dir,
                session_dir=session_dir,
                env=env,
            )
            return _spawn_oneshot(
                argv=argv,
                prompt=prompt,
                timeout=timeout,
                env=env,
            )


# ---------------------------------------------------------------------------
# CLI argv builder
# ---------------------------------------------------------------------------


def build_argv(
    *,
    binary: str,
    model: str | None,
    agents_md: Path | None = None,
    skill_paths: Sequence[Path | str] = (),
) -> list[str]:
    """Build the ``pi`` invocation argv for a single non-interactive iteration.

    Args:
        binary: Executable name or absolute path of the ``pi`` CLI.
        model: Optional model identifier forwarded as ``--model``. When
            ``None``, the flag is omitted and ``pi`` uses its built-in
            default (preserving the pre-T6.1 invocation shape).
        agents_md: Optional harness-owned ``AGENTS.md`` path to append
            explicitly to the system prompt. The runtime also passes
            ``--no-context-files`` so this is the only context file the
            subprocess receives.
        skill_paths: Explicit skill directories or files to load with
            ``--skill``. ``--no-skills`` still disables discovery of
            personal and project-global skills.

    Returns:
        The argv list ready to pass to `subprocess.Popen`.
    """
    argv = [
        binary,
        "--print",
        "--mode",
        "json",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
    ]
    if agents_md is not None:
        argv.extend(["--append-system-prompt", str(agents_md)])
    for skill_path in skill_paths:
        argv.extend(["--skill", str(skill_path)])
    if model is not None:
        argv.extend(["--model", model])
    return argv


def build_complete_argv(*, binary: str, model: str | None) -> list[str]:
    """Build the ``pi`` argv for a one-shot non-agent completion.

    Disables tools, extension / skill / prompt-template / theme
    discovery, AGENTS.md auto-loading, and session persistence so the
    call is a pure prompt → text completion. Used by `PiRuntime.complete`
    to satisfy the `LLMCompleter` protocol.

    Args:
        binary: Executable name or absolute path of the ``pi`` CLI.
        model: Optional model identifier forwarded as ``--model``. When
            ``None``, the flag is omitted and ``pi`` uses its built-in
            default — same defaulting behaviour as `build_argv`.

    Returns:
        The argv list ready to pass to `subprocess.Popen`.
    """
    argv = [
        binary,
        "--print",
        "--mode",
        "text",
        "--no-tools",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-session",
    ]
    if model is not None:
        argv.extend(["--model", model])
    return argv


def build_isolated_env(*, agent_dir: Path, session_dir: Path) -> dict[str, str]:
    """Return a subprocess environment isolated from personal ``pi`` config.

    ``pi`` reads settings, auth, models, packages, system prompts, and
    default session lookup state under ``PI_CODING_AGENT_DIR``. The
    harness points that directory at a per-call scratch location so
    runtime behaviour cannot depend on ``~/.pi/agent``.

    Provider credentials and routing variables are loaded from the first
    project ``.env`` found by walking upward from the current working
    directory, then overlaid with ``os.environ`` so shell exports still
    win. The isolated ``pi`` config paths are applied last.

    Args:
        agent_dir: Per-call config directory for ``PI_CODING_AGENT_DIR``.
        session_dir: Per-call session directory for
            ``PI_CODING_AGENT_SESSION_DIR``.

    Returns:
        A child-process environment with project ``.env`` values,
        current process env values, and the two ``pi`` config paths
        overridden.
    """
    env = _project_dotenv_values()
    env.update(os.environ)
    env[_PI_AGENT_DIR_ENV] = str(agent_dir.resolve())
    env[_PI_SESSION_DIR_ENV] = str(session_dir.resolve())
    return env


def prepare_isolated_config(
    *,
    agent_dir: Path,
    session_dir: Path,
    env: Mapping[str, str],
) -> None:
    """Write harness-owned ``pi`` config derived only from project inputs.

    The isolated agent directory must not copy ``~/.pi/agent``. When the
    project ``.env`` supplies provider base URLs, this writes the minimal
    ``models.json`` override that ``pi`` needs to route built-in models
    through those endpoints. API keys are referenced through Pi's
    ``$ENV_VAR`` interpolation syntax, not copied into the file.

    Args:
        agent_dir: Per-call config directory for ``PI_CODING_AGENT_DIR``.
        session_dir: Per-call session directory for
            ``PI_CODING_AGENT_SESSION_DIR``.
        env: Child process environment returned by
            :func:`build_isolated_env`.
    """
    agent_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)

    models_config = build_models_config_from_env(env)
    if models_config is None:
        return
    models_path = agent_dir / _MODELS_FILENAME
    models_path.write_text(
        json.dumps(models_config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_models_config_from_env(env: Mapping[str, str]) -> dict[str, JsonValue] | None:
    """Return a ``pi`` ``models.json`` config from provider routing env vars.

    ``pi`` reads provider API keys from environment variables, but its
    built-in providers do not read the repo's ``ANTHROPIC_BASE_URL`` or
    ``OPENAI_BASE_URL`` variables directly. A provider-level override
    keeps the run independent from personal ``models.json`` while still
    honoring project ``.env`` routing.

    Args:
        env: Child process environment.

    Returns:
        A JSON-serializable ``models.json`` payload, or ``None`` when no
        provider base URL override is configured.
    """
    providers: dict[str, JsonValue] = {}
    anthropic = _provider_models_config(
        env=env,
        base_url_env=_ANTHROPIC_BASE_URL_ENV,
        provider_api_key_env=_ANTHROPIC_API_KEY_ENV,
    )
    if anthropic is not None:
        providers["anthropic"] = anthropic
    openai = _provider_models_config(
        env=env,
        base_url_env=_OPENAI_BASE_URL_ENV,
        provider_api_key_env=_OPENAI_API_KEY_ENV,
    )
    if openai is not None:
        providers["openai"] = openai
    if not providers:
        return None
    return {"providers": providers}


def _provider_models_config(
    *,
    env: Mapping[str, str],
    base_url_env: str,
    provider_api_key_env: str,
) -> dict[str, JsonValue] | None:
    """Return one provider override for ``models.json`` when configured."""
    base_url = env.get(base_url_env, "").strip()
    if not base_url:
        return None
    config: dict[str, JsonValue] = {"baseUrl": base_url}
    api_key_env = _select_api_key_env(env, provider_api_key_env)
    if api_key_env is not None:
        config["apiKey"] = f"${api_key_env}"
    return config


def _select_api_key_env(
    env: Mapping[str, str],
    provider_api_key_env: str,
) -> str | None:
    """Choose the env var name a generated provider config should reference."""
    if env.get(_PI_PROXY_API_KEY_ENV, "").strip():
        return _PI_PROXY_API_KEY_ENV
    if env.get(provider_api_key_env, "").strip():
        return provider_api_key_env
    return None


def _project_dotenv_values() -> dict[str, str]:
    """Return key/value pairs from the nearest project ``.env``.

    Missing files are normal. Entries without a value are ignored,
    matching the repo's existing ``override=False`` behavior while
    avoiding mutation of the parent process environment.
    """
    path = find_dotenv(usecwd=True)
    if not path:
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


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
    env: dict[str, str],
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
            env=env,
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


def _spawn_oneshot(
    *,
    argv: list[str],
    prompt: str,
    timeout: float,
    env: dict[str, str],
) -> str:
    """Run ``argv`` with ``prompt`` on stdin, returning captured stdout.

    Mirrors `_spawn_and_capture`'s timeout / process-group discipline,
    but captures stdout / stderr into memory rather than tee'ing to a
    debug artifact. On `subprocess.TimeoutExpired`
    we send ``SIGTERM`` to the process group, give it a brief grace
    window, then escalate to ``SIGKILL`` and re-raise.

    Returns:
        The child's UTF-8-decoded stdout, with trailing whitespace
        stripped.

    Raises:
        RuntimeError: The child exits non-zero. The message includes
            trimmed stderr/stdout so provider auth and model-routing
            failures are visible to callers.
    """
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    try:
        stdout_bytes, stderr_bytes = proc.communicate(
            input=prompt.encode("utf-8"),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _terminate_group(proc)
        raise
    finally:
        if proc.poll() is None:
            _terminate_group(proc)
    stdout = stdout_bytes.decode("utf-8", errors="replace").rstrip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").rstrip()
    returncode = proc.returncode if proc.returncode is not None else -1
    if returncode != 0:
        detail = _format_oneshot_error(stdout=stdout, stderr=stderr)
        raise RuntimeError(f"pi completion failed with exit code {returncode}: {detail}")
    return stdout


def _format_oneshot_error(*, stdout: str, stderr: str) -> str:
    """Return a compact diagnostic for a failed one-shot subprocess."""
    parts: list[str] = []
    if stderr:
        parts.append(f"stderr: {_truncate_error_text(stderr)}")
    if stdout:
        parts.append(f"stdout: {_truncate_error_text(stdout)}")
    if not parts:
        return "no stdout/stderr"
    return " ".join(parts)


def _truncate_error_text(value: str) -> str:
    """Trim very large subprocess output before raising it as an exception."""
    if len(value) <= _MAX_ONESHOT_ERROR_CHARS:
        return value
    return value[: _MAX_ONESHOT_ERROR_CHARS - 1].rstrip() + "…"


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
