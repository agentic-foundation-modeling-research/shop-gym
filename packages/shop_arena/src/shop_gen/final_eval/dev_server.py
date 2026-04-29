"""Production ``pnpm dev`` runner — implements :class:`DevServerFactory`.

Spec: ``docs/specs/shop_arena/visual_verifier.md`` §5.5 ·
Impl plan: ``docs/impl/visual_verifier_implementation.md`` T6.1.

Replaces the ``_unconfigured_dev_server_factory`` placeholders previously
hardcoded in :mod:`shop_gen.build.loop` and
:mod:`shop_gen.final_eval.step`.

Two public surfaces:

* :func:`dev_server_lifecycle` — context manager that spawns an
  arbitrary HTTP-server subprocess (``argv``), polls ``GET /health``
  until it responds 200, yields its base URL, and tears the process
  down on exit (normal exit, exception, or SIGTERM / SIGINT delivered
  to the parent).

* :func:`pnpm_dev_factory` — returns a
  :class:`~shop_gen.final_eval.playwright_smoke.DevServerFactory`
  callable that wraps :func:`dev_server_lifecycle` with the canonical
  ``pnpm dev`` argv. The factory allocates a free TCP port (or reuses
  a caller-pinned one), injects ``PORT`` into the subprocess
  environment, and roots the dev server at ``hydrogen_dir``.

The lifecycle helper mirrors :func:`shop_gen.build.sidecar.sidecar_lifecycle`
so the two long-lived subprocesses (`shop-backend` sidecar +
``pnpm dev`` Hydrogen server) share the same teardown contract.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from types import FrameType
from typing import Any, Final, cast

import httpx

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #


_HEALTH_TIMEOUT_S: Final[float] = 60.0
"""Max wall-clock seconds to wait for ``/health`` (Vite warm-up budget)."""

_HEALTH_POLL_INTERVAL_S: Final[float] = 0.5
"""Sleep between ``/health`` poll attempts."""

_TERMINATE_GRACE_S: Final[float] = 5.0
"""Grace seconds between ``SIGTERM`` and the follow-up ``SIGKILL``."""

_HTTP_OK: Final[int] = 200
"""HTTP success status code (matches the canonical Hydrogen ``/health``)."""

_HEALTH_PATH: Final[str] = "/health"
"""URL path the lifecycle helper polls."""

_PORT_ENV_KEY: Final[str] = "PORT"
"""Environment variable Hydrogen's ``server.mjs`` reads its listen port from."""


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class DevServerLifecycleError(RuntimeError):
    """Raised when the dev server subprocess fails to boot or stay healthy.

    Distinguishes lifecycle bugs (spawn failure, ``/health`` timeout,
    early exit) from in-flight HTTP failures the verifier surfaces as
    its own verdict.
    """


# --------------------------------------------------------------------------- #
# Lifecycle helper
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def dev_server_lifecycle(
    *,
    argv: Sequence[str],
    port: int,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    health_timeout_s: float = _HEALTH_TIMEOUT_S,
) -> Iterator[str]:
    """Spawn ``argv``, poll ``/health``, yield ``base_url``, clean up on exit.

    The subprocess is always torn down before this generator returns,
    regardless of the exit path:

    * **Normal exit.** The ``with`` block completes; the ``finally``
      branch terminates the subprocess.
    * **Exception inside the block.** The ``finally`` branch runs; the
      subprocess is terminated and the exception propagates.
    * **SIGTERM / SIGINT.** A handler installed on entry terminates
      the subprocess, restores the previous handler, and re-delivers
      the signal so the parent's previous handler observes it.

    The subprocess is launched in its own session
    (``start_new_session=True``) so signals delivered to the parent
    do not implicitly travel down the controlling-terminal tree;
    cleanup is always explicit.

    Args:
        argv: Process-spawn argument vector. Production callers pass
            ``["pnpm", "dev"]``; tests inject a Python stub.
        port: TCP port the subprocess is expected to listen on.
            Embedded in the yielded ``base_url``.
        cwd: Working directory for the subprocess. Production callers
            pass the freshly built hydrogen tree.
        env: Environment for the subprocess. ``None`` inherits from
            the parent.
        health_timeout_s: Max wall-clock seconds spent polling
            ``GET /health`` before declaring the spawn a failure.

    Yields:
        ``"http://127.0.0.1:<port>"`` once ``/health`` returns 200.

    Raises:
        DevServerLifecycleError: The subprocess exited before becoming
            healthy, the deadline expired, or ``/health`` returned an
            unexpected status.
    """
    proc = subprocess.Popen(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    prev_handlers = _install_signal_cleanup(proc)
    try:
        _wait_for_health(proc, base_url, timeout_s=health_timeout_s)
        yield base_url
    finally:
        _restore_signal_handlers(prev_handlers)
        _terminate(proc)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def pnpm_dev_factory(
    *,
    health_timeout_s: float = _HEALTH_TIMEOUT_S,
    port: int | None = None,
    pnpm_executable: str = "pnpm",
) -> Any:
    """Return a :class:`DevServerFactory` that boots Hydrogen via ``pnpm dev``.

    The returned callable allocates a free TCP port (unless ``port``
    is pinned), spawns ``<pnpm_executable> dev`` rooted at
    ``hydrogen_dir`` with ``PORT`` injected into the environment,
    polls ``/health`` until the dev server is reachable, and tears
    the process down on exit via :func:`dev_server_lifecycle`.

    Args:
        health_timeout_s: Max wall-clock seconds to wait for
            ``/health`` to respond 200.
        port: If provided, reuse this fixed port; otherwise allocate
            a kernel-assigned free port on each invocation.
        pnpm_executable: ``pnpm`` binary name. Override only for tests
            that wrap the runner in a custom shim.

    Returns:
        A callable matching the
        :class:`~shop_gen.final_eval.playwright_smoke.DevServerFactory`
        protocol.
    """

    def factory(hydrogen_dir: Path) -> AbstractContextManager[str]:
        actual_port = port if port is not None else _allocate_free_port()
        env = {**os.environ, _PORT_ENV_KEY: str(actual_port)}
        return dev_server_lifecycle(
            argv=[pnpm_executable, "dev"],
            port=actual_port,
            cwd=hydrogen_dir,
            env=env,
            health_timeout_s=health_timeout_s,
        )

    return factory


# --------------------------------------------------------------------------- #
# Internals — port allocation
# --------------------------------------------------------------------------- #


def _allocate_free_port() -> int:
    """Bind to port 0 and return the kernel-assigned port.

    A short TOCTOU window exists between socket close and subprocess
    bind; in practice the kernel cycles through the ephemeral range
    quickly enough that collisions are rare. Production callers tear
    a single dev server up and down per build, so this is acceptable.
    """
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert isinstance(port, int)
    return port


# --------------------------------------------------------------------------- #
# Internals — health poll
# --------------------------------------------------------------------------- #


def _wait_for_health(
    proc: subprocess.Popen[bytes],
    base_url: str,
    *,
    timeout_s: float,
) -> None:
    """Poll ``GET /health`` until 200 or the deadline expires.

    Raises:
        DevServerLifecycleError: Subprocess exited early, the deadline
            expired, or ``/health`` returned a non-2xx status the
            entire poll window.
    """
    deadline = time.monotonic() + timeout_s
    last_error: str = ""
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            stderr = _drain(proc.stderr).decode("utf-8", errors="replace")
            raise DevServerLifecycleError(
                f"dev server exited with code {rc} before {_HEALTH_PATH} responded; "
                f"stderr=\n{stderr}",
            )
        try:
            response = httpx.get(f"{base_url}{_HEALTH_PATH}", timeout=1.0)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            time.sleep(_HEALTH_POLL_INTERVAL_S)
            continue
        if response.status_code == _HTTP_OK:
            return
        last_error = f"HTTP {response.status_code}"
        time.sleep(_HEALTH_POLL_INTERVAL_S)
    raise DevServerLifecycleError(
        f"timed out waiting for {_HEALTH_PATH} after {timeout_s:.1f}s; last={last_error}",
    )


# --------------------------------------------------------------------------- #
# Internals — subprocess teardown
# --------------------------------------------------------------------------- #


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Stop ``proc``. Idempotent for an already-exited process."""
    if proc.poll() is not None:
        return
    proc.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=_TERMINATE_GRACE_S)
        return
    proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=_TERMINATE_GRACE_S)


def _drain(stream: object) -> bytes:
    """Read whatever is currently buffered on ``stream`` (best-effort)."""
    if stream is None:
        return b""
    try:
        return cast("Any", stream).read() or b""
    except (OSError, ValueError):
        return b""


# --------------------------------------------------------------------------- #
# Internals — signal cleanup
# --------------------------------------------------------------------------- #


_SignalHandler = signal.Handlers | int | object | None
"""``signal.getsignal``'s declared return type."""


def _install_signal_cleanup(
    proc: subprocess.Popen[bytes],
) -> dict[int, _SignalHandler]:
    """Install SIGTERM / SIGINT handlers that terminate ``proc`` then re-raise.

    Returns a ``{signum: previous_handler}`` mapping the caller passes
    back to :func:`_restore_signal_handlers` on context exit.
    Suppressed silently when called from a non-main thread (``signal``
    only allows handler installation in the main thread); the caller
    falls back to the ``finally``-branch teardown for normal exits and
    exceptions.
    """
    prev: dict[int, _SignalHandler] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            prev_handler = signal.getsignal(sig)
        except (OSError, ValueError):
            continue
        try:
            signal.signal(sig, _make_signal_handler(proc, prev_handler))
        except (OSError, ValueError):
            continue
        prev[sig] = prev_handler
    return prev


def _restore_signal_handlers(prev: dict[int, _SignalHandler]) -> None:
    """Restore previous SIGTERM / SIGINT handlers (best-effort)."""
    for sig, handler in prev.items():
        with contextlib.suppress(OSError, ValueError, TypeError):
            signal.signal(sig, cast("Any", handler))


def _make_signal_handler(
    proc: subprocess.Popen[bytes],
    prev_handler: _SignalHandler,
) -> Any:
    """Build a ``signal.signal``-compatible handler that terminates ``proc``."""

    def handler(signum: int, frame: FrameType | None) -> None:
        del frame
        _terminate(proc)
        with contextlib.suppress(OSError, ValueError, TypeError):
            signal.signal(signum, cast("Any", prev_handler))
        with contextlib.suppress(ProcessLookupError):
            os.kill(os.getpid(), signum)

    return handler


__all__ = [
    "DevServerLifecycleError",
    "dev_server_lifecycle",
    "pnpm_dev_factory",
]
