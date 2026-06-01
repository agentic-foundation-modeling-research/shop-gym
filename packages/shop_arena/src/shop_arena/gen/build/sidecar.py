"""Phase 4 ``start_sidecar`` step + lifecycle helper (spec §5.5.1, T5.2).

Owns the ``shop-backend`` subprocess that the build harness loop talks
to via ``PUBLIC_STORE_DOMAIN``. Exposes two public surfaces:

* :func:`sidecar_lifecycle` — context manager that spawns the
  ``shop-backend`` subprocess, polls ``/health`` until ready, yields a
  :class:`SidecarHandle`, and tears the process down on exit. Handles
  three teardown paths uniformly: normal exit, exception inside the
  ``with`` block, and ``SIGTERM`` / ``SIGINT`` delivered to the parent
  process. Signal handlers are installed on entry and restored on exit.

* :class:`StartSidecarStep` (id ``start_sidecar``) — pre-flight step
  registered in the build phase. Reads the resolved port back out of
  ``<out_dir>/hydrogen/.env``, locates the bundled
  ``packages/shop_backend/dist/cli.js``, boots the sidecar once via
  :func:`sidecar_lifecycle` to verify the spawn sequence works against
  the freshly assembled ``data/`` tree, then writes
  ``<out_dir>/sidecar.json`` with the resolved
  port / URL / argv / store-name. The long-lived sidecar that the
  build loop talks to is spawned by ``run_build_harness_loop`` (T5.6)
  using the same :func:`sidecar_lifecycle` helper — one sidecar per
  loop, per spec §5.5.1.

Step contract (spec §5.7.1):

* ``id``: ``start_sidecar``.
* ``phase``: ``build``.
* ``inputs``: two :class:`StepInput` references — ``write_env_file``
  source) and ``assemble_data`` (the six ``data/*.json`` files
  shop-backend loads on boot are that step's declared outputs, so a
  ``StepInput`` reference is the canonical freshness signal).
* ``outputs``: ``[sidecar.json]``.
* ``depends_on``: ``[write_env_file, assemble_data]``.

Module is import-safe: no I/O, no env reads, no side effects at import
time.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Final, cast

import httpx

from shop_arena.gen.data_validation.hosting_check import find_shop_backend_cli
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "build"
_STEP_ID: Final[str] = "start_sidecar"
_STEP_VERSION: Final[int] = 2

_UPSTREAM_WRITE_ENV: Final[str] = "write_env_file"
_UPSTREAM_ASSEMBLE_DATA: Final[str] = "assemble_data"

_DATA_DIR: Final[Path] = Path("data")
"""Run-relative location of the published SandboxShop dataset."""

_HYDROGEN_ENV: Final[Path] = Path("hydrogen") / ".env"
"""Run-relative location of the ``.env`` written by ``write_env_file``."""

_SIDECAR_REPORT: Final[Path] = Path("sidecar.json")
"""Run-relative path of the JSON verdict the step writes.

Sibling of ``data_validation.json`` / ``final_eval.json``. Kept *outside*
``runs/build/`` because that subtree is owned by ``run_build_harness_loop``
as the harness ``run_dir``: anything pre-existing there forces the harness
into resume mode (`Workspace.open`), which fails the identity check.
"""

_DATA_FILES: Final[tuple[str, ...]] = (
    "store.json",
    "products.json",
    "collections.json",
    "pages.json",
    "policies.json",
    "navigation.json",
)
"""Closed list of dataset files shop-backend reads on boot (spec §5.4).

Tracked transitively via the ``assemble_data`` :class:`StepInput` rather
than per-file :class:`FileInput`s: ``assemble_data`` declares these as
its outputs, so its fingerprint is the canonical freshness signal.
"""

_HEALTH_TIMEOUT_S: Final[float] = 15.0
"""Maximum wall-clock time spent polling ``/health`` after spawn."""

_HEALTH_POLL_INTERVAL_S: Final[float] = 0.1
"""Sleep between ``/health`` poll attempts."""

_TERMINATE_GRACE_S: Final[float] = 3.0
"""Seconds given to the subprocess to exit after ``SIGTERM`` before ``SIGKILL``."""

_HTTP_OK: Final[int] = 200
"""HTTP success status code (matches ``shop-backend``'s ``/health``)."""

_DOMAIN_KEY: Final[str] = "PUBLIC_STORE_DOMAIN"
"""``.env`` key emitted by ``write_env_file`` containing the resolved sidecar URL."""

_PORT_RANGE_MAX: Final[int] = 65535
"""Inclusive upper bound on a TCP port (used for parse validation)."""


class SidecarLifecycleError(RuntimeError):
    """Raised when the sidecar fails to start or its config cannot be parsed.

    Distinguishable from :class:`shop_arena.gen.data_validation.hosting_check.HostingValidationError`:
    that one signals a query-suite failure against a *running* sidecar;
    this one signals a problem with the lifecycle helper itself
    (spawn, health, or env-file parse).
    """


@dataclass(frozen=True, slots=True)
class SidecarHandle:
    """Live-sidecar metadata yielded by :func:`sidecar_lifecycle`.

    Attributes:
        pid: Operating-system pid of the spawned ``shop-backend`` process.
        port: TCP port the subprocess is listening on (``127.0.0.1:port``).
        base_url: ``http://127.0.0.1:<port>`` — the storefront URL the
            harness loop's Hydrogen tree points at via
            ``PUBLIC_STORE_DOMAIN``.
        store_name: Value of the ``store`` field returned by
            ``GET /health`` once the subprocess is ready.
    """

    pid: int
    port: int
    base_url: str
    store_name: str


# --------------------------------------------------------------------------- #
# Lifecycle helper
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def sidecar_lifecycle(
    *,
    argv: Sequence[str],
    port: int,
    health_timeout_s: float = _HEALTH_TIMEOUT_S,
) -> Generator[SidecarHandle, None, None]:
    """Spawn ``shop-backend``, poll ``/health``, yield a handle, clean up on exit.

    The subprocess is always torn down before this generator returns,
    regardless of the exit path:

    * **Normal exit.** The ``with`` block completes; the ``finally``
      branch terminates the subprocess.
    * **Exception inside the block.** The ``finally`` branch runs; the
      subprocess is terminated and the exception propagates.
    * **SIGTERM / SIGINT.** A handler installed on entry terminates
      the subprocess, restores the previous handler, and re-delivers
      the signal so the parent's previous handler observes it.
      Re-delivery means the parent's normal teardown order is
      preserved (e.g. pytest finalizers).

    The subprocess is launched in its own session
    (``start_new_session=True``) so a SIGTERM delivered to the parent
    does not implicitly travel down the controlling-terminal tree;
    cleanup is always explicit.

    Args:
        argv: Process-spawn argument vector. Production callers pass
            ``["node", str(cli_path), str(data_dir), str(port)]``;
            tests inject a Python stub script via this seam.
        port: TCP port the subprocess is expected to listen on.
            Embedded in the polled ``base_url`` and surfaced on the
            yielded :class:`SidecarHandle`.
        health_timeout_s: Maximum wall-clock seconds spent polling
            ``GET /health`` before declaring the spawn a failure.

    Yields:
        :class:`SidecarHandle` describing the live subprocess.

    Raises:
        SidecarLifecycleError: The subprocess exited before becoming
            healthy, or the deadline expired, or ``/health`` returned
            an unexpected payload.
    """
    proc = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    prev_handlers = _install_signal_cleanup(proc)
    try:
        store_name = _wait_for_health(proc, base_url, timeout_s=health_timeout_s)
        yield SidecarHandle(
            pid=proc.pid,
            port=port,
            base_url=base_url,
            store_name=store_name,
        )
    finally:
        _restore_signal_handlers(prev_handlers)
        _terminate(proc)


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class StartSidecarStep:
    """Phase 4 ``start_sidecar`` step (spec §5.5.1).

    Boots ``shop-backend`` against ``<out_dir>/data/`` on the port
    written into ``<out_dir>/hydrogen/.env`` by
    :class:`shop_arena.gen.build.env.WriteEnvFileStep`, asserts ``/health``
    responds, captures the verdict in
    ``<out_dir>/sidecar.json``, then tears the subprocess
    down. The long-lived sidecar that the build loop talks to is
    spawned later by ``run_build_harness_loop`` (T5.6) using the same
    :func:`sidecar_lifecycle` helper.

    Attributes:
        id: Step id (``start_sidecar``).
        phase: ``build``.
        inputs: Two :class:`StepInput` references — ``write_env_file``
            source) and ``assemble_data`` (the dataset shop-backend
            loads on boot, declared as that step's outputs).
        outputs: ``[sidecar.json]``.
        depends_on: ``[write_env_file, assemble_data]``.
        version: Bumped when the sidecar lifecycle contract changes.
    """

    def __init__(self) -> None:
        """Build the step bound to the upstream ``write_env_file`` producer."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            StepInput(step_id=_UPSTREAM_WRITE_ENV),
            StepInput(step_id=_UPSTREAM_ASSEMBLE_DATA),
        ]
        self.outputs: list[Path] = [_SIDECAR_REPORT]
        self.depends_on: list[str] = [_UPSTREAM_WRITE_ENV, _UPSTREAM_ASSEMBLE_DATA]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Boot the sidecar, write the verdict, tear it down.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                step talks only to the spawned subprocess.

        Raises:
            SidecarLifecycleError: ``hydrogen/.env`` is missing or
                malformed, the subprocess failed to come up, or
                ``/health`` did not respond before the deadline.
            shop_arena.gen.data_validation.hosting_check.HostingValidationError:
                ``packages/shop_backend/dist/cli.js`` cannot be located.
        """
        env_path = ctx.out_dir / _HYDROGEN_ENV
        port = parse_port_from_env(env_path)
        cli_path = find_shop_backend_cli()
        data_dir = ctx.out_dir / _DATA_DIR
        argv: list[str] = ["node", str(cli_path), str(data_dir), str(port)]

        with sidecar_lifecycle(argv=argv, port=port) as handle:
            verdict: dict[str, Any] = {
                "ok": True,
                "port": handle.port,
                "base_url": handle.base_url,
                "store_name": handle.store_name,
                "data_dir": str(data_dir),
                "cli_path": str(cli_path),
                "argv": argv,
            }

        report_path = ctx.out_dir / _SIDECAR_REPORT
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(verdict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internals — env-file parsing
# --------------------------------------------------------------------------- #


def parse_port_from_env(env_path: Path) -> int:
    """Extract the ``PUBLIC_STORE_DOMAIN`` port from ``write_env_file``'s ``.env``.

    The file's expected shape (see
    :mod:`shop_arena.gen.build.env`) is::

        PUBLIC_STORE_DOMAIN=http://localhost:<port>

    Anything else — missing key, malformed value, non-numeric port,
    out-of-range port — raises :class:`SidecarLifecycleError` rather
    than silently substituting a default.
    """
    if not env_path.is_file():
        raise SidecarLifecycleError(
            f"hydrogen .env not found at {env_path}; did write_env_file run?",
        )
    text = env_path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith(f"{_DOMAIN_KEY}="):
            continue
        value = line.split("=", 1)[1].strip().strip('"').strip("'")
        if "://" in value:
            value = value.split("://", 1)[1]
        _, _, port_s = value.rpartition(":")
        if not port_s.isdigit():
            raise SidecarLifecycleError(
                f"{env_path}: {_DOMAIN_KEY} value {raw_line!r} has no numeric port",
            )
        port = int(port_s)
        if not 1 <= port <= _PORT_RANGE_MAX:
            raise SidecarLifecycleError(
                f"{env_path}: {_DOMAIN_KEY} port {port} out of range",
            )
        return port
    raise SidecarLifecycleError(
        f"{env_path}: missing {_DOMAIN_KEY}= line",
    )


# --------------------------------------------------------------------------- #
# Internals — subprocess lifecycle
# --------------------------------------------------------------------------- #


_SignalHandler = signal.Handlers | int | object | None
"""``signal.getsignal``'s declared return type (callable | SIG_DFL | SIG_IGN | None)."""


def _wait_for_health(
    proc: subprocess.Popen[bytes],
    base_url: str,
    *,
    timeout_s: float,
) -> str:
    """Poll ``GET /health`` until 200 or the deadline expires.

    Returns:
        Value of the ``store`` field from the ``/health`` JSON payload.

    Raises:
        SidecarLifecycleError: Subprocess exited early, the deadline
            expired, or the response payload was malformed.
    """
    deadline = time.monotonic() + timeout_s
    last_error: str = ""
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            stderr = _drain(proc.stderr).decode("utf-8", errors="replace")
            raise SidecarLifecycleError(
                f"sidecar exited with code {rc} before /health responded; stderr=\n{stderr}",
            )
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            time.sleep(_HEALTH_POLL_INTERVAL_S)
            continue
        if response.status_code == _HTTP_OK:
            payload = cast("dict[str, Any]", response.json())
            store = payload.get("store")
            if not isinstance(store, str):
                raise SidecarLifecycleError(
                    f"/health returned unexpected payload: {payload!r}",
                )
            return store
        last_error = f"HTTP {response.status_code}"
        time.sleep(_HEALTH_POLL_INTERVAL_S)
    raise SidecarLifecycleError(
        f"timed out waiting for /health after {timeout_s:.1f}s; last={last_error}",
    )


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
            # Non-main thread or unsupported signal: skip rather than
            # crash the lifecycle. Normal-exit + exception cleanup
            # still works via the ``finally`` branch.
            continue
        prev[sig] = prev_handler
    return prev


def _restore_signal_handlers(prev: dict[int, _SignalHandler]) -> None:
    """Restore the previous SIGTERM / SIGINT handlers (best-effort)."""
    for sig, handler in prev.items():
        with contextlib.suppress(OSError, ValueError, TypeError):
            signal.signal(sig, cast("Any", handler))


def _make_signal_handler(
    proc: subprocess.Popen[bytes],
    prev_handler: _SignalHandler,
) -> Any:
    """Build a ``signal.signal``-compatible handler that terminates ``proc``.

    The handler:

    1. Terminates the subprocess (idempotent).
    2. Restores the previous handler.
    3. Re-delivers the signal to ``os.getpid()`` so the previous
       handler observes it (default SIGTERM exits; default SIGINT
       raises ``KeyboardInterrupt``).

    Returns ``Any`` to satisfy :func:`signal.signal`'s loose typing
    surface; the function shape ``(int, FrameType | None) -> None`` is
    documented but not enforced by ``signal``.
    """

    def handler(signum: int, frame: FrameType | None) -> None:
        del frame
        _terminate(proc)
        with contextlib.suppress(OSError, ValueError, TypeError):
            signal.signal(signum, cast("Any", prev_handler))
        with contextlib.suppress(ProcessLookupError):
            os.kill(os.getpid(), signum)

    return handler


__all__ = [
    "SidecarHandle",
    "SidecarLifecycleError",
    "StartSidecarStep",
    "parse_port_from_env",
    "sidecar_lifecycle",
]
