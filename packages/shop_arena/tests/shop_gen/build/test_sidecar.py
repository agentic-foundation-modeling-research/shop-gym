"""Unit + integration tests for :mod:`shop_gen.build.sidecar`.

Covers the T5.2 requirements from
``docs/impl/shop_gen_implementation.md``:

* Step contract: id, phase, inputs, outputs, depends_on, version.
* Pipeline registration: ``start_sidecar`` surfaces in the build
  phase listing.
* ``.env`` parsing: happy path + the failure modes
  :class:`SidecarLifecycleError` documents.
* Lifecycle helper teardown — the impl-plan check explicitly demands
  three independent paths:

  1. **Normal exit.** The ``with`` block completes; the spawned
     subprocess is gone.
  2. **Test-induced crash.** An exception inside the ``with`` block
     propagates *and* the subprocess is still cleaned up.
  3. **SIGTERM.** A driver child process uses
     :func:`sidecar_lifecycle`; we send SIGTERM to the driver and
     verify the driver's grandchild (the stub backend) dies before
     the timeout expires.

Tests use a Python-based stub backend (a tiny ``http.server``) so
they do not depend on the compiled ``packages/shop_backend``. The
step-level integration tests skip when the real ``cli.js`` is
absent, mirroring the pattern in
``tests/shop_gen/data_validation/test_hosting_check.py``.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from shop_gen.build.sidecar import (
    SidecarHandle,
    SidecarLifecycleError,
    StartSidecarStep,
    parse_port_from_env,
    sidecar_lifecycle,
)
from shop_gen.config import ShopGenConfig
from shop_gen.data_validation.hosting_check import HostingValidationError, find_shop_backend_cli
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import FileInput, Step, StepContext, StepInput

# --------------------------------------------------------------------------- #
# Stub backend
# --------------------------------------------------------------------------- #

_STUB_BACKEND_SOURCE: str = textwrap.dedent(
    """
    import http.server
    import json
    import sys

    PORT = int(sys.argv[1])
    STORE = sys.argv[2] if len(sys.argv) > 2 else "Stub Store"


    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                body = json.dumps({"ok": True, "store": STORE}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args, **kwargs):  # noqa: D401, ANN001, ANN002, ANN003
            return


    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
    """
).strip()
"""Stub ``shop-backend`` that responds to ``GET /health`` and nothing else."""


def _allocate_free_port() -> int:
    """Bind to port 0 and return the kernel-assigned port."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert isinstance(port, int)
    return port


def _stub_argv(port: int, store_name: str = "Stub Store") -> list[str]:
    """Build the argv that spawns the Python stub backend."""
    return [sys.executable, "-c", _STUB_BACKEND_SOURCE, str(port), store_name]


def _wait_for_process_exit(pid: int, *, timeout_s: float = 5.0) -> bool:
    """Poll ``os.kill(pid, 0)`` until it raises or the deadline expires.

    Returns ``True`` once the process is gone, ``False`` if the
    deadline expired.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # Another user owns the pid; treat as alive — the test
            # would not have been able to spawn it anyway.
            return False
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return True
            raise
        time.sleep(0.05)
    return False


# --------------------------------------------------------------------------- #
# Step contract
# --------------------------------------------------------------------------- #


def test_start_sidecar_step_satisfies_step_protocol() -> None:
    step = StartSidecarStep()

    assert isinstance(step, Step)
    assert step.id == "start_sidecar"
    assert step.phase == "build"
    assert step.outputs == [Path("runs") / "build" / "sidecar.json"]
    assert step.depends_on == ["write_env_file"]
    assert step.version == 1


def test_start_sidecar_inputs_cover_env_dep_plus_six_data_files() -> None:
    """``inputs`` declares the upstream env-write step + every data file."""
    step = StartSidecarStep()

    step_inputs = [ref for ref in step.inputs if isinstance(ref, StepInput)]
    file_inputs = [ref for ref in step.inputs if isinstance(ref, FileInput)]
    assert [ref.step_id for ref in step_inputs] == ["write_env_file"]
    assert sorted(ref.path.name for ref in file_inputs) == [
        "collections.json",
        "navigation.json",
        "pages.json",
        "policies.json",
        "products.json",
        "store.json",
    ]


def test_start_sidecar_step_registered_in_build_phase() -> None:
    """``--list-steps`` surfaces ``start_sidecar`` after ``write_env_file``."""
    grouped = list_steps()

    build = grouped["build"]
    assert "start_sidecar" in build
    assert build.index("start_sidecar") > build.index("write_env_file")


# --------------------------------------------------------------------------- #
# .env parsing
# --------------------------------------------------------------------------- #

_FIXED_PORT_FOR_PARSER_TEST: int = 54321
"""Arbitrary fixed port the parser tests embed in the synthetic ``.env``."""

_BARE_PORT_FOR_PARSER_TEST: int = 12345
"""Arbitrary fixed port for the bare-host-port parser variant."""


def testparse_port_from_env_extracts_port_from_public_store_domain(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        f"PUBLIC_STORE_DOMAIN=http://localhost:{_FIXED_PORT_FOR_PARSER_TEST}\nSESSION_SECRET=foo\n",
        encoding="utf-8",
    )

    assert parse_port_from_env(env) == _FIXED_PORT_FOR_PARSER_TEST


def testparse_port_from_env_handles_bare_host_port(tmp_path: Path) -> None:
    """The parser must tolerate a value without an explicit ``http://`` prefix."""
    env = tmp_path / ".env"
    env.write_text(
        f"PUBLIC_STORE_DOMAIN=localhost:{_BARE_PORT_FOR_PARSER_TEST}\n",
        encoding="utf-8",
    )

    assert parse_port_from_env(env) == _BARE_PORT_FOR_PARSER_TEST


def testparse_port_from_env_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(SidecarLifecycleError, match=r"hydrogen \.env not found"):
        parse_port_from_env(tmp_path / "missing.env")


def testparse_port_from_env_raises_when_key_missing(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SESSION_SECRET=foo\n", encoding="utf-8")

    with pytest.raises(SidecarLifecycleError, match="missing PUBLIC_STORE_DOMAIN"):
        parse_port_from_env(env)


def testparse_port_from_env_raises_when_port_non_numeric(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("PUBLIC_STORE_DOMAIN=http://localhost:abc\n", encoding="utf-8")

    with pytest.raises(SidecarLifecycleError, match="no numeric port"):
        parse_port_from_env(env)


# --------------------------------------------------------------------------- #
# Lifecycle helper — happy path
# --------------------------------------------------------------------------- #


def test_sidecar_lifecycle_yields_handle_after_health_ok() -> None:
    port = _allocate_free_port()

    with sidecar_lifecycle(argv=_stub_argv(port), port=port) as handle:
        assert isinstance(handle, SidecarHandle)
        assert handle.port == port
        assert handle.base_url == f"http://127.0.0.1:{port}"
        assert handle.store_name == "Stub Store"
        # Process is alive while inside the with block.
        os.kill(handle.pid, 0)


# --------------------------------------------------------------------------- #
# Cleanup path 1 — normal exit
# --------------------------------------------------------------------------- #


def test_sidecar_lifecycle_terminates_subprocess_on_normal_exit() -> None:
    port = _allocate_free_port()

    with sidecar_lifecycle(argv=_stub_argv(port), port=port) as handle:
        spawned_pid = handle.pid

    assert _wait_for_process_exit(spawned_pid), (
        f"sidecar pid {spawned_pid} still alive after lifecycle exit"
    )


# --------------------------------------------------------------------------- #
# Cleanup path 2 — exception inside the with block
# --------------------------------------------------------------------------- #


class _SyntheticTestError(RuntimeError):
    """Marker exception raised inside the ``with`` block to test cleanup."""


def test_sidecar_lifecycle_terminates_subprocess_on_exception() -> None:
    port = _allocate_free_port()
    spawned_pid: int | None = None

    with (
        pytest.raises(_SyntheticTestError, match="boom"),
        sidecar_lifecycle(argv=_stub_argv(port), port=port) as handle,
    ):
        spawned_pid = handle.pid
        raise _SyntheticTestError("boom")

    assert spawned_pid is not None
    assert _wait_for_process_exit(spawned_pid), (
        f"sidecar pid {spawned_pid} still alive after exception teardown"
    )


# --------------------------------------------------------------------------- #
# Cleanup path 3 — SIGTERM delivered to the parent
# --------------------------------------------------------------------------- #


def _sigterm_driver_source() -> str:
    """Driver script the SIGTERM test spawns as a child process.

    The driver enters ``sidecar_lifecycle`` against the Python stub
    backend, prints the spawned pid + a ready marker on stdout, then
    blocks on ``signal.pause`` until SIGTERM is delivered. The lifecycle
    helper's signal handler runs first (terminating the stub backend);
    after handler restoration the previous default SIGTERM handler
    terminates the driver itself.
    """
    return textwrap.dedent(
        f"""
        import json
        import os
        import signal
        import sys

        from shop_gen.build.sidecar import sidecar_lifecycle

        PORT = int(sys.argv[1])
        STUB_SOURCE = {_STUB_BACKEND_SOURCE!r}
        ARGV = [sys.executable, "-c", STUB_SOURCE, str(PORT), "Stub Store"]

        with sidecar_lifecycle(argv=ARGV, port=PORT) as handle:
            sys.stdout.write(json.dumps({{"pid": handle.pid, "ready": True}}) + "\\n")
            sys.stdout.flush()
            # Wait until SIGTERM (or any signal) hits us. The lifecycle
            # helper installed a handler that terminates the sidecar
            # subprocess and re-raises the signal.
            signal.pause()
        """
    ).strip()


def test_sidecar_lifecycle_terminates_subprocess_on_sigterm(tmp_path: Path) -> None:
    """SIGTERM to a process using the lifecycle takes the sidecar with it."""
    port = _allocate_free_port()
    driver_script = tmp_path / "driver.py"
    driver_script.write_text(_sigterm_driver_source(), encoding="utf-8")

    driver = subprocess.Popen(
        [sys.executable, str(driver_script), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Read the ready marker so we know the sidecar booted.
        assert driver.stdout is not None
        ready_line = driver.stdout.readline().decode("utf-8", errors="replace")
        assert ready_line, "driver did not emit a ready marker before exiting"
        payload = json.loads(ready_line)
        sidecar_pid = int(payload["pid"])
        assert payload["ready"] is True

        # Sanity: the sidecar pid is currently alive.
        os.kill(sidecar_pid, 0)

        # Send SIGTERM to the driver. The lifecycle's installed handler
        # must terminate the sidecar before the driver exits.
        driver.send_signal(signal.SIGTERM)
        driver.wait(timeout=10.0)
    finally:
        # Defensive cleanup if the test failed mid-way.
        if driver.poll() is None:
            driver.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                driver.wait(timeout=5.0)

    assert _wait_for_process_exit(sidecar_pid), (
        f"sidecar pid {sidecar_pid} still alive after driver SIGTERM"
    )


# --------------------------------------------------------------------------- #
# Lifecycle helper — failure paths
# --------------------------------------------------------------------------- #


def test_sidecar_lifecycle_raises_when_subprocess_exits_before_health() -> None:
    """A spawn that exits immediately surfaces a clean lifecycle error."""
    # ``python -c "raise SystemExit(7)"`` exits before any /health server boots.
    argv = [sys.executable, "-c", "import sys; sys.exit(7)"]
    port = _allocate_free_port()

    with (
        pytest.raises(SidecarLifecycleError, match="exited with code 7"),
        sidecar_lifecycle(argv=argv, port=port, health_timeout_s=2.0),
    ):
        pytest.fail("yield should not have been reached")


def test_sidecar_lifecycle_raises_when_health_times_out() -> None:
    """A spawn that lives but never serves /health surfaces a timeout."""
    # Spawn a process that sleeps without binding any port.
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    port = _allocate_free_port()

    with (
        pytest.raises(SidecarLifecycleError, match="timed out waiting for /health"),
        sidecar_lifecycle(argv=argv, port=port, health_timeout_s=0.5),
    ):
        pytest.fail("yield should not have been reached")


# --------------------------------------------------------------------------- #
# Step.run — happy path against the bundled ``packages/shop_backend``
# --------------------------------------------------------------------------- #


def test_start_sidecar_step_writes_sidecar_json(tmp_path: Path) -> None:
    """The step writes ``runs/build/sidecar.json`` against the bundled CLI."""
    if not _backend_available():
        pytest.skip(_BACKEND_REASON)

    # Set up a workspace with a hydrogen/.env + populated data/.
    seed = tmp_path / "seed"
    seed.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hydrogen = out_dir / "hydrogen"
    hydrogen.mkdir()
    port = _allocate_free_port()
    (hydrogen / ".env").write_text(
        f"PUBLIC_STORE_DOMAIN=http://localhost:{port}\n",
        encoding="utf-8",
    )
    _materialise_data_dir(out_dir)

    cfg = ShopGenConfig(seeds=(seed,), out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    StartSidecarStep().run(ctx)

    report = out_dir / "runs" / "build" / "sidecar.json"
    assert report.is_file()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["port"] == port
    assert payload["base_url"] == f"http://127.0.0.1:{port}"
    assert payload["data_dir"] == str(out_dir / "data")
    # store_name comes from the real shop-backend's /health response.
    assert isinstance(payload["store_name"], str)
    assert payload["store_name"]


def test_start_sidecar_step_propagates_env_parse_error(tmp_path: Path) -> None:
    """A workspace with no ``hydrogen/.env`` raises before any spawn."""
    seed = tmp_path / "seed"
    seed.mkdir()
    out_dir = tmp_path / "out"
    (out_dir / "hydrogen").mkdir(parents=True)
    cfg = ShopGenConfig(seeds=(seed,), out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    with pytest.raises(SidecarLifecycleError):
        StartSidecarStep().run(ctx)


# --------------------------------------------------------------------------- #
# Real-CLI fixture plumbing (mirrors test_hosting_check.py)
# --------------------------------------------------------------------------- #


def _backend_available() -> bool:
    """Return ``True`` when the compiled ``cli.js`` is on disk."""
    try:
        find_shop_backend_cli()
    except HostingValidationError:
        return False
    return True


_BACKEND_REASON = (
    "shop-backend dist/cli.js missing; run `pnpm --filter @shop-gym/shop-backend build`"
)

_DATA_FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "data_synth" / "fixtures" / "sandbox_shop_v0"
)
_BACKEND_FIXTURE_DIR = (
    Path(__file__).resolve().parents[5]
    / "packages"
    / "shop_backend"
    / "tests"
    / "fixtures"
    / "sandbox_shop_v0"
)
_FIXTURE_FILES: tuple[str, ...] = (
    "store.json",
    "products.json",
    "collections.json",
    "pages.json",
    "policies.json",
    "navigation.json",
)


def _materialise_data_dir(out_dir: Path) -> Path:
    """Copy the canonical JSON fixtures + a real ``images/`` tree into ``<out_dir>/data/``."""
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in _FIXTURE_FILES:
        shutil.copy(_DATA_FIXTURE_DIR / name, data_dir / name)
    images_dir = data_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    pixel = _BACKEND_FIXTURE_DIR / "images" / "pixel.png"
    products = json.loads((data_dir / "products.json").read_text(encoding="utf-8"))
    for product in products:
        for image in product.get("images", []) or []:
            src = image.get("src")
            if isinstance(src, str):
                target = images_dir / src
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(pixel, target)
    return data_dir
