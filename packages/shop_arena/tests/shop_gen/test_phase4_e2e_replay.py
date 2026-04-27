"""End-to-end replay test for Phase 4 (T5.10).

Drives :class:`shop_gen.build.loop.RunBuildHarnessLoopStep` through the
hand-crafted ``fixture_build_loop`` cassette starting from the canonical
M4 ``sandbox_shop_v0`` ``data/`` fixture and asserting that:

* the Phase 4 build loop produces a working hydrogen tree under
  ``runs/build/artifact/hydrogen/`` (every cassette mutation lands), and
* every dispatched verifier reports a non-blocking verdict
  (``PASS``/``ADVISORY``/``ERROR``) — no ``FAIL`` — across every
  executor iteration.

Together these satisfy SC3 + SC6 from
``docs/specs/shop_arena/shop_gen.md`` §4.2 under
:class:`harness.runtimes.replay.ReplayRuntime`: the loop driver +
verifier set are exercised deterministically without API keys, the
``shop-backend`` sidecar, the ``pnpm`` toolchain, or the dev server.

Each verifier-side dependency is wired through its public injection
seam (subprocess runner, dev-server factory, schema introspector,
custom allowlist) — no internal monkey-patching. The LLM-judge
verifiers' :class:`harness.runtimes.LLMCompleter` requirement is
satisfied by a tiny replay/completer adapter that delegates iteration
playback to the cassette and returns a canned ``"pass"`` JSON verdict
for ``complete()``.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import threading
from collections.abc import Iterator, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Final

import httpx
import pytest

from harness import AgentRuntime, Verifier
from harness.runtimes.base import RuntimeIterationResult
from harness.runtimes.replay import ReplayRuntime
from harness.verifiers import Verdict
from shop_gen.brands.allowlist import Allowlist
from shop_gen.build.loop import RunBuildHarnessLoopStep, RuntimeFactory, VerifiersFactory
from shop_gen.build.sidecar import SidecarHandle
from shop_gen.build.verifiers import (
    BuildVerifier,
    CrossTaskConsistencyVerifier,
    DataInUseVerifier,
    NavCoverageVerifier,
    NoBrandLeakVerifier,
    QualityJudgeVerifier,
    Routes200Verifier,
    SchemaIntrospection,
    TscVerifier,
)
from shop_gen.build.verifiers._subprocess import CompletedSubprocess
from shop_gen.config import ShopGenConfig
from shop_gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_CASSETTE_DIR: Final[Path] = Path(__file__).resolve().parent / "cassettes" / "fixture_build_loop"
"""Hand-crafted cassette shared with T5.9 (`test_build_loop_replay.py`)."""

_DATA_FIXTURE_DIR: Final[Path] = (
    Path(__file__).resolve().parent / "data_synth" / "fixtures" / "sandbox_shop_v0"
)
"""Canonical M4 dataset fixture shipped under ``data_synth/fixtures/``."""

_FIXTURE_FILES: Final[tuple[str, ...]] = (
    "store.json",
    "products.json",
    "collections.json",
    "pages.json",
    "policies.json",
    "navigation.json",
)
"""SandboxShop dataset files copied verbatim into ``out_dir/data/``."""

_EXPECTED_HYDROGEN_FILES: Final[tuple[str, ...]] = (
    "app/styles/theme.css",
    "app/components/Header.tsx",
    "app/routes/_index.tsx",
    "CONSOLIDATE.md",
)
"""Hydrogen mutations the cassette layers across the four executor iterations."""

_PORT: Final[int] = 54321
"""Fixed port the test workspace's ``.env`` advertises."""

_BASE_URL: Final[str] = f"http://127.0.0.1:{_PORT}"
"""Stand-in storefront URL the stub sidecar reports."""

# Schema covering the canonical Storefront query fields. The cassette
# does not author any GraphQL today; this snapshot keeps the verifier
# wired against a realistic shape so the test stays meaningful when
# future cassette mutations introduce ``graphql`...``` blocks.
_STOREFRONT_FIELDS: Final[frozenset[str]] = frozenset(
    {"shop", "product", "products", "collection", "collections", "page", "cart"},
)

_PASS_JUDGE_PAYLOAD: Final[str] = json.dumps({"verdict": "pass", "feedback": ""})
"""Canned LLM-judge response that decodes to ``Verdict.PASS``."""


# --------------------------------------------------------------------------- #
# Stubs — runtime, sidecar, subprocess
# --------------------------------------------------------------------------- #


class _ReplayCompleterRuntime:
    """Composite ``AgentRuntime`` + :class:`harness.runtimes.LLMCompleter`.

    Delegates ``run_iteration`` to a wrapped :class:`ReplayRuntime` and
    returns a canned ``"pass"`` JSON verdict for ``complete``. The two
    LLM-judge verifiers (``quality_judge`` + ``cross_task_consistency``)
    narrow ``ctx.runtime`` to :class:`LLMCompleter` via ``isinstance`` —
    a runtime exposing both methods satisfies the loop driver and the
    verifier dispatch in a single object.
    """

    def __init__(self, *, replay: ReplayRuntime) -> None:
        """Bind the composite runtime to a replay backend."""
        self._replay = replay

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Forward to the replay runtime."""
        return self._replay.run_iteration(
            run_dir=run_dir,
            iter_dir=iter_dir,
            prompt=prompt,
            timeout=timeout,
        )

    def complete(self, prompt: str, *, timeout: float) -> str:
        """Return a canned ``"pass"`` JSON verdict."""
        del prompt, timeout
        return _PASS_JUDGE_PAYLOAD


def _stub_handle() -> SidecarHandle:
    """Return a :class:`SidecarHandle` for the stub sidecar lifecycle."""
    return SidecarHandle(pid=12345, port=_PORT, base_url=_BASE_URL, store_name="Stub")


@contextlib.contextmanager
def _stub_sidecar_factory(*, argv: Sequence[str], port: int) -> Iterator[SidecarHandle]:
    """Sidecar factory that never spawns a subprocess."""
    del argv
    assert port == _PORT
    yield _stub_handle()


def _passing_subprocess_runner(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
) -> CompletedSubprocess:
    """Stub :class:`SubprocessRunner` that always reports ``returncode=0``.

    Used for ``TscVerifier`` + ``BuildVerifier`` so the SC3 build path
    is exercised without invoking the real ``pnpm`` toolchain.
    """
    del argv, cwd, timeout
    return CompletedSubprocess(returncode=0, stdout="", stderr="")


def _shop_backend_cli_stub() -> Path:
    """Return a path the loop step accepts as the bundled ``shop-backend`` CLI."""
    return Path(__file__).resolve()


# --------------------------------------------------------------------------- #
# Stubs — Routes200 dev server
# --------------------------------------------------------------------------- #


class _AlwaysOkHandler(BaseHTTPRequestHandler):
    """HTTP handler that returns ``200 OK`` for every path."""

    def do_GET(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — stdlib API
        del format, args  # silence default access logs


@contextlib.contextmanager
def _dev_server_factory(hydrogen_dir: Path) -> Iterator[str]:
    """Dev-server factory that boots an in-process HTTP server.

    Every request returns ``200 OK`` so :class:`Routes200Verifier`
    reports ``PASS`` for every probed task route.
    """
    del hydrogen_dir
    server = HTTPServer(("127.0.0.1", 0), _AlwaysOkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


# --------------------------------------------------------------------------- #
# Stubs — DataInUse introspector
# --------------------------------------------------------------------------- #


def _stub_introspector() -> SchemaIntrospection:
    """Return a static :class:`SchemaIntrospection` covering Storefront roots.

    The cassette currently authors zero GraphQL operations — the
    verifier returns ``PASS`` regardless — but the snapshot keeps the
    seam wired against realistic root fields so adding cassette
    mutations later does not silently regress the check.
    """
    return SchemaIntrospection(
        root_fields={
            "Query": _STOREFRONT_FIELDS,
            "Mutation": frozenset(
                {"cartCreate", "cartLinesAdd", "cartLinesUpdate", "cartLinesRemove"},
            ),
        },
    )


# --------------------------------------------------------------------------- #
# Stubs — NoBrandLeak permissive allowlist
# --------------------------------------------------------------------------- #


def _permissive_allowlist() -> Allowlist:
    """Return an :class:`Allowlist` that accepts every cassette token.

    The cassette's hand-written hydrogen mutations include common
    TypeScript/React identifiers (``Header``, ``ReactElement``,
    ``LoaderFunctionArgs``, ``Awaited``, ``ReturnType``, ...) that a
    production allowlist does not list. Production code will iterate
    on the allowlist + safe-noun list as the cassette evolves; for
    T5.10 we promote those identifiers into ``brands`` so the
    verifier returns ``PASS`` and the test stays focused on the
    end-to-end driver behaviour.
    """
    return Allowlist(
        version="t5_10-permissive",
        brands=frozenset(
            {
                # TypeScript/React identifiers used in the cassette.
                "Header",
                "ReactElement",
                "LoaderFunctionArgs",
                "Awaited",
                "ReturnType",
                "Index",
                "Data",
                "Inter",
                # Demo store text.
                "SandboxShop",
                "Welcome",
                "Shop",
                "About",
                "Name",
                # Title-cased collection labels in the cassette nav.
                "Dog",
                "Essentials",
                "Cat",
                "Care",
            },
        ),
        safe_nouns=frozenset(),
    )


# --------------------------------------------------------------------------- #
# Verifier wiring
# --------------------------------------------------------------------------- #


def _build_verifiers_factory(*, data_dir: Path) -> VerifiersFactory:
    """Return a verifiers factory wiring the v0.1 set with passing stubs.

    The factory is closed over ``data_dir`` so :class:`NavCoverageVerifier`
    sees the real M4 fixture's ``collections.json``. The cassette's
    ``Header.tsx`` mentions every M4 collection handle so the verifier
    reports ``PASS`` after ``gen_navigation``.
    """

    def _factory(
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
    ) -> tuple[Verifier, ...]:
        del out_dir, sidecar
        return (
            TscVerifier(runner=_passing_subprocess_runner),
            BuildVerifier(runner=_passing_subprocess_runner),
            Routes200Verifier(
                task_routes={
                    "gen_navigation": ("/",),
                    "gen_homepage": ("/",),
                    "gen_collections": ("/collections",),
                    "gen_product": ("/products/tickless-anti-tick-collar",),
                    "gen_info_pages": ("/pages/about-us",),
                    "consolidate": ("/", "/collections"),
                },
                dev_server_factory=_dev_server_factory,
            ),
            DataInUseVerifier(introspect=_stub_introspector),
            NavCoverageVerifier(data_dir=data_dir),
            NoBrandLeakVerifier(allowlist=_permissive_allowlist()),
            QualityJudgeVerifier(),
            CrossTaskConsistencyVerifier(),
        )

    return _factory


# --------------------------------------------------------------------------- #
# Workspace helpers
# --------------------------------------------------------------------------- #


def _materialise_workspace(out_dir: Path) -> None:
    """Lay the manual + data + hydrogen sub-trees the loop step requires.

    ``data/`` is a verbatim copy of the canonical M4 fixture
    (``sandbox_shop_v0``). The ``manual/`` subtree carries the four
    canonical files (empty payloads are sufficient for replay) so the
    spec §5.5 seed manifest tracks the same set of roots as the
    production driver.
    """
    manual_dir = out_dir / "manual"
    manual_dir.mkdir(parents=True)
    (manual_dir / "capabilities.json").write_text("{}", encoding="utf-8")
    (manual_dir / "manual.md").write_text("# manual\n", encoding="utf-8")
    (manual_dir / "stats.json").write_text("{}", encoding="utf-8")
    (manual_dir / "manifest.json").write_text("{}", encoding="utf-8")

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)
    for name in _FIXTURE_FILES:
        shutil.copy(_DATA_FIXTURE_DIR / name, data_dir / name)

    hydrogen_dir = out_dir / "hydrogen"
    (hydrogen_dir / "app").mkdir(parents=True)
    (hydrogen_dir / "package.json").write_text(
        '{"name":"hydrogen"}\n',
        encoding="utf-8",
    )
    (hydrogen_dir / "app" / "root.tsx").write_text("// root\n", encoding="utf-8")
    (hydrogen_dir / ".env").write_text(
        f"PUBLIC_STORE_DOMAIN=http://localhost:{_PORT}\n",
        encoding="utf-8",
    )


def _build_ctx(out_dir: Path, *, max_iters: int) -> StepContext:
    """Build a :class:`StepContext` rooted at ``out_dir``."""
    seed = out_dir.parent / "seed"
    seed.mkdir(exist_ok=True)
    cfg = ShopGenConfig(seeds=(seed,), out_dir=out_dir, max_iters=max_iters)
    return StepContext(config=cfg, out_dir=out_dir)


def _runtime_factory_for(runtime: AgentRuntime) -> RuntimeFactory:
    """Wrap ``runtime`` in a :class:`RuntimeFactory`."""

    def _factory(config: ShopGenConfig) -> AgentRuntime:
        del config
        return runtime

    return _factory


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_phase4_e2e_replay_produces_working_hydrogen_with_no_blocking_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC3 + SC6: M4 ``data/`` → working ``hydrogen/`` with non-blocking verifiers.

    Drives the cassette under :class:`ReplayRuntime` end-to-end with
    the full v0.1 verifier set wired through its public seams. After
    the loop completes the test asserts:

    * the hydrogen tree at ``runs/build/artifact/hydrogen/`` contains
      every cassette mutation (proxy for SC3 — the executor's writes
      land on the work surface and the rule-based ``tsc``/``build``
      verifiers signed off);
    * every :class:`harness.verifiers.VerifierRun` recorded in
      ``runs/build/run.json`` carries a non-blocking verdict
      (``PASS``/``ADVISORY``/``ERROR`` — no ``FAIL``), which is the
      replay equivalent of SC6;
    * the M4 dataset survives alongside the work surface so future
      iterations could keep reading it (mutable per spec §5.5).
    """
    monkeypatch.setattr(
        "shop_gen.build.loop.find_shop_backend_cli",
        _shop_backend_cli_stub,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    replay = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    runtime = _ReplayCompleterRuntime(replay=replay)

    step = RunBuildHarnessLoopStep(
        runtime_factory=_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_build_verifiers_factory(data_dir=out_dir / "data"),
    )

    # Cassette has 1 plan + 4 executor iterations; budget allows one
    # extra in case the consolidate-fallback resumes the loop.
    step.run(_build_ctx(out_dir, max_iters=6))

    run_dir = out_dir / "runs" / "build"
    summary_path = run_dir / "run.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    # SC3 (proxy): the build loop reached COMPLETED, every cassette
    # mutation landed on the work surface, and the dataset survived.
    assert summary["final_status"] == "completed"
    assert summary["plan_iter_count"] == 1
    assert summary["exec_iter_count"] == 4  # noqa: PLR2004 — cassette task count
    artifact = run_dir / "artifact"
    for relative in _EXPECTED_HYDROGEN_FILES:
        path = artifact / "hydrogen" / relative
        assert path.is_file(), f"missing hydrogen mutation: {relative}"
    for fixture_name in _FIXTURE_FILES:
        assert (artifact / "data" / fixture_name).is_file(), f"missing data fixture: {fixture_name}"

    # SC6: every dispatched verifier reports a non-blocking verdict.
    verifier_runs = summary["verifier_runs"]
    assert verifier_runs, "no verifiers were dispatched — wiring regression"
    blocking = [run for run in verifier_runs if run["verdict"] == Verdict.FAIL.value]
    assert blocking == [], (
        "SC6 violation: the following verifier runs blocked the loop "
        f"with FAIL verdicts:\n{json.dumps(blocking, indent=2)}"
    )

    # Sanity: every verifier in the v0.1 set was actually exercised at
    # least once across the four executor iterations.
    dispatched_names = {run["name"] for run in verifier_runs}
    assert dispatched_names == {
        "tsc",
        "build",
        "routes_200",
        "data_in_use",
        "nav_coverage",
        "no_brand_leak",
        "quality_judge",
        "cross_task_consistency",
    }


def test_phase4_e2e_replay_persists_per_iteration_verifier_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each iteration's ``checks/verifiers/<name>.json`` matches the run summary.

    ``run.json`` aggregates the per-iteration verifier outcomes; the
    per-iteration files keep the full telemetry on disk
    (spec §5.6). Both views must agree on verdict + name.
    """
    monkeypatch.setattr(
        "shop_gen.build.loop.find_shop_backend_cli",
        _shop_backend_cli_stub,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    replay = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    runtime = _ReplayCompleterRuntime(replay=replay)

    step = RunBuildHarnessLoopStep(
        runtime_factory=_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_build_verifiers_factory(data_dir=out_dir / "data"),
    )

    step.run(_build_ctx(out_dir, max_iters=6))

    run_dir = out_dir / "runs" / "build"
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    for run in summary["verifier_runs"]:
        per_verifier_path = run_dir / run["path"]
        assert per_verifier_path.is_file(), f"missing per-verifier telemetry at {per_verifier_path}"
        per_verifier = json.loads(per_verifier_path.read_text(encoding="utf-8"))
        assert per_verifier["name"] == run["name"]
        assert per_verifier["verdict"] == run["verdict"]
        assert per_verifier["task_id"] == run["task_id"]


# --------------------------------------------------------------------------- #
# Sanity — ensure the test module's stubs themselves do what we think
# --------------------------------------------------------------------------- #


def test_passing_subprocess_runner_returns_returncode_zero() -> None:
    """The stubbed runner reports ``returncode=0`` so tsc/build verifiers PASS."""
    completed = _passing_subprocess_runner(
        ("pnpm", "tsc"),
        cwd=Path("."),
        timeout=1.0,
    )
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""
    # Hardening: the helper must not raise :class:`subprocess.TimeoutExpired`
    # (the verifier branches on it explicitly).
    assert not isinstance(completed, subprocess.TimeoutExpired)


def test_replay_completer_runtime_returns_pass_verdict() -> None:
    """The composite runtime emits a parsable ``"pass"`` JSON verdict."""
    replay = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    runtime = _ReplayCompleterRuntime(replay=replay)
    raw = runtime.complete("ignored", timeout=1.0)
    payload = json.loads(raw)
    assert payload == {"verdict": "pass", "feedback": ""}


def test_dev_server_factory_returns_200_for_every_path(tmp_path: Path) -> None:
    """The stub dev server PASSes :class:`Routes200Verifier` against any path."""

    with _dev_server_factory(tmp_path) as base_url:
        response = httpx.get(f"{base_url}/anything", timeout=2.0)
        assert response.status_code == 200  # noqa: PLR2004 — HTTP OK
        response = httpx.get(f"{base_url}/products/whatever", timeout=2.0)
        assert response.status_code == 200  # noqa: PLR2004 — HTTP OK
