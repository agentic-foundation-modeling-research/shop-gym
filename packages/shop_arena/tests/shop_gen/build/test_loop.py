"""Unit + integration tests for :mod:`shop_gen.build.loop`.

Covers the T5.6 requirements from
``docs/impl/shop_gen_implementation.md``:

* Step contract: id, phase, inputs, outputs, depends_on, version.
* Pipeline registration: ``run_build_harness_loop`` surfaces in the
  build phase listing.
* Workspace setup: the manual is seeded under ``run_dir/artifact/``,
  the hydrogen tree + dataset land under ``run_dir/artifact/hydrogen/``
  and ``run_dir/artifact/data/`` *after* the seed manifest is captured,
  the sidecar is held live for the duration of the harness call.
* Integration test under :class:`harness.runtimes.replay.ReplayRuntime`:
  the harness receives the expected :class:`PlanExecLoopConfig`
  (run_dir, prompts, agents_md, artifact_seed_dir, max_iters,
  verifiers).

Tests inject stub seams via :class:`RunBuildHarnessLoopStep`'s
constructor so they never touch the real ``shop-backend`` CLI, ``pnpm``,
or any LLM provider.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

import httpx
import pytest
import respx

from harness import (
    AgentRuntime,
    PlanExecLoopConfig,
    PlanExecLoopResult,
    Verifier,
    VerifierContext,
    VerifierResult,
)
from harness.config import FinalStatus
from harness.runtimes.base import RuntimeIterationResult
from harness.runtimes.replay import ReplayRuntime
from shop_gen.build.loop import (
    RunBuildHarnessLoopStep,
    RuntimeFactory,
    _GraphqlIntrospector,
    default_verifiers_factory,
)
from shop_gen.build.prompts import (
    load_agents_md,
    load_execute_prompt,
    load_planner_prompt,
)
from shop_gen.build.sidecar import SidecarHandle
from shop_gen.build.verifiers import (
    BuildVerifier,
    CrossTaskConsistencyVerifier,
    DataInUseVerifier,
    NavCoverageVerifier,
    NavigationPrimitiveUsageVerifier,
    QualityJudgeVerifier,
    Routes200Verifier,
    TscVerifier,
    VisualJudgeVerifier,
)
from shop_gen.build.verifiers._subprocess import CompletedSubprocess
from shop_gen.config import (
    DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY,
    DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD,
    DEFAULT_VISUAL_RETRY_BUDGET,
    ShopGenConfig,
)
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import FileInput, Step, StepContext, StepInput

# --------------------------------------------------------------------------- #
# Constants + helpers
# --------------------------------------------------------------------------- #

_PORT: Final[int] = 54321
"""Fixed port the test workspace's ``.env`` advertises."""

_BASE_URL: Final[str] = f"http://127.0.0.1:{_PORT}"
"""Base URL the stub sidecar reports on its handle."""

_CFG_MAX_ITERS: Final[int] = 7
"""Arbitrary executor budget threaded into the captured-config test."""


def _stub_handle() -> SidecarHandle:
    """Build a :class:`SidecarHandle` for the stub sidecar lifecycle."""
    return SidecarHandle(pid=12345, port=_PORT, base_url=_BASE_URL, store_name="Stub")


@contextlib.contextmanager
def _stub_sidecar_factory(*, argv: Sequence[str], port: int) -> Iterator[SidecarHandle]:
    """Stub :class:`SidecarFactory` that never spawns a subprocess."""
    del argv
    assert port == _PORT
    yield _stub_handle()


def _stub_install_runner(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
) -> CompletedSubprocess:
    """Stub :class:`SubprocessRunner` for ``pnpm install`` — always succeeds.

    Keeps the loop-step unit tests hermetic: they exercise the artifact-tree
    materialisation path without requiring ``pnpm`` on ``$PATH``.
    """
    del argv, cwd, timeout
    return CompletedSubprocess(returncode=0, stdout="", stderr="")


class _StubRuntime:
    """Bare-bones :class:`AgentRuntime` (the stub loop runner ignores it)."""

    def run_iteration(  # pragma: no cover — captured by stub loop runner.
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del run_dir, iter_dir, prompt, timeout
        raise AssertionError("stub runtime should not run iterations")


def _materialise_workspace(out_dir: Path, *, port: int = _PORT) -> None:
    """Create the minimum on-disk workspace the loop step expects.

    Builds the four upstream sub-trees the step reads:

    * ``manual/`` with the merged-or-copied seed contents.
    * ``data/`` with the canonical six JSON files (empty arrays).
    * ``hydrogen/`` with the cloned template's ``package.json`` sentinel
      plus an ``app/`` directory the executor would mutate.
    * ``hydrogen/.env`` advertising the sidecar port.
    """
    manual_dir = out_dir / "manual"
    manual_dir.mkdir(parents=True)
    (manual_dir / "capabilities.json").write_text("{}", encoding="utf-8")
    (manual_dir / "manual.md").write_text("# manual\n", encoding="utf-8")
    (manual_dir / "stats.json").write_text("{}", encoding="utf-8")
    (manual_dir / "manifest.json").write_text("{}", encoding="utf-8")

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)
    for name in (
        "store.json",
        "products.json",
        "collections.json",
        "pages.json",
        "policies.json",
        "navigation.json",
    ):
        (data_dir / name).write_text("[]", encoding="utf-8")
    # Repopulate products / pages with one record each so the default
    # task-routes mapping lands a deterministic handle.
    (data_dir / "products.json").write_text(
        json.dumps([{"handle": "demo-product"}]),
        encoding="utf-8",
    )
    (data_dir / "pages.json").write_text(
        json.dumps([{"handle": "about-us"}]),
        encoding="utf-8",
    )

    hydrogen_dir = out_dir / "hydrogen"
    (hydrogen_dir / "app").mkdir(parents=True)
    (hydrogen_dir / "package.json").write_text('{"name":"hydrogen"}\n', encoding="utf-8")
    (hydrogen_dir / "app" / "root.tsx").write_text("// root\n", encoding="utf-8")
    (hydrogen_dir / ".env").write_text(
        f"PUBLIC_STORE_DOMAIN=http://localhost:{port}\n",
        encoding="utf-8",
    )


def _build_ctx(
    out_dir: Path,
    *,
    max_iters: int = 5,
    visual_retry_budget: int = 3,
    visual_judge_pass_threshold: float | None = None,
    visual_judge_max_concurrency: int | None = None,
    judges: frozenset[str] | None = None,
) -> StepContext:
    """Construct a :class:`StepContext` rooted at ``out_dir``."""
    seed = out_dir.parent / "seed"
    seed.mkdir(exist_ok=True)
    kwargs: dict[str, object] = {
        "seeds": (seed,),
        "out_dir": out_dir,
        "max_iters": max_iters,
        "visual_retry_budget": visual_retry_budget,
    }
    if judges is not None:
        kwargs["judges"] = judges
    if visual_judge_pass_threshold is not None:
        kwargs["visual_judge_pass_threshold"] = visual_judge_pass_threshold
    if visual_judge_max_concurrency is not None:
        kwargs["visual_judge_max_concurrency"] = visual_judge_max_concurrency
    cfg = ShopGenConfig(**kwargs)  # type: ignore[arg-type]
    return StepContext(config=cfg, out_dir=out_dir)


def _shop_backend_cli_stub() -> Path:
    """A path the loop step accepts as the bundled CLI without spawning anything."""
    # The default sidecar factory is stubbed out in every test that
    # exercises ``run``; the path is therefore never executed. Returning
    # the test runner's own argv[0] avoids the patched ``find_shop_backend_cli``
    # helper hunting through the monorepo.
    return Path(__file__).resolve()


def _empty_verifiers_factory(
    *,
    out_dir: Path,
    sidecar: SidecarHandle,
    judges: frozenset[str] = frozenset(),
    visual_retry_budget: int = 3,
    visual_judge_pass_threshold: float = 7.0,
    visual_judge_max_concurrency: int = 3,
) -> tuple[Verifier, ...]:
    """Return an empty verifier tuple; reused across tests that don't care about dispatch."""
    del out_dir, sidecar, judges, visual_retry_budget
    del visual_judge_pass_threshold, visual_judge_max_concurrency
    return ()


def _stub_runtime_factory_for(runtime: AgentRuntime) -> RuntimeFactory:
    """Build a :class:`RuntimeFactory` that returns ``runtime``."""

    def _factory(config: ShopGenConfig) -> AgentRuntime:
        del config
        return runtime

    return _factory


# --------------------------------------------------------------------------- #
# Step contract
# --------------------------------------------------------------------------- #


def test_run_build_harness_loop_step_satisfies_step_protocol() -> None:
    step = RunBuildHarnessLoopStep()

    assert isinstance(step, Step)
    assert step.id == "run_build_harness_loop"
    assert step.phase == "build"
    assert step.outputs == [Path("runs") / "build" / "run.json"]
    assert step.depends_on == [
        "start_sidecar",
        "assemble_data",
        "validate_hosting",
    ]
    assert step.version == 1


def test_run_build_harness_loop_inputs_cover_upstream_steps_and_env_files() -> None:
    """``inputs`` declares the upstream sidecar/data/hosting deps + env file refs."""
    step = RunBuildHarnessLoopStep()

    step_inputs = [ref for ref in step.inputs if isinstance(ref, StepInput)]
    file_inputs = [ref for ref in step.inputs if isinstance(ref, FileInput)]
    assert sorted(ref.step_id for ref in step_inputs) == [
        "assemble_data",
        "start_sidecar",
        "validate_hosting",
    ]
    assert sorted(str(ref.path) for ref in file_inputs) == sorted(
        [
            str(Path("hydrogen") / "package.json"),
            str(Path("hydrogen") / ".env"),
        ],
    )


def test_run_build_harness_loop_registered_in_build_phase() -> None:
    """``--list-steps`` surfaces ``run_build_harness_loop`` last in the build phase."""
    grouped = list_steps()

    build = grouped["build"]
    assert "run_build_harness_loop" in build
    # Loop driver must come after the env + sidecar prep.
    assert build.index("run_build_harness_loop") > build.index("start_sidecar")
    assert build[-1] == "run_build_harness_loop"


def test_step_forwards_visual_retry_budget_to_verifiers_factory(
    tmp_path: Path,
) -> None:
    """Impl plan T2.3: ``ctx.config.visual_retry_budget`` reaches the factory."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    captured_budgets: list[int] = []

    def _verifiers_factory(
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
        judges: frozenset[str] = frozenset(),
        visual_retry_budget: int = 3,
        visual_judge_pass_threshold: float = 7.0,
        visual_judge_max_concurrency: int = 3,
    ) -> tuple[Verifier, ...]:
        del out_dir, sidecar, judges
        del visual_judge_pass_threshold, visual_judge_max_concurrency
        captured_budgets.append(visual_retry_budget)
        return ()

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir, visual_retry_budget=0))

    assert captured_budgets == [0]


def test_step_forwards_visual_judge_score_and_concurrency_to_verifiers_factory(
    tmp_path: Path,
) -> None:
    """Impl plan T3.6: pass-threshold + max-concurrency reach the factory."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    captured: list[tuple[float, int]] = []

    def _verifiers_factory(
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
        judges: frozenset[str] = frozenset(),
        visual_retry_budget: int = 3,
        visual_judge_pass_threshold: float = 7.0,
        visual_judge_max_concurrency: int = 3,
    ) -> tuple[Verifier, ...]:
        del out_dir, sidecar, judges, visual_retry_budget
        captured.append(
            (visual_judge_pass_threshold, visual_judge_max_concurrency),
        )
        return ()

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(
            _build_ctx(
                out_dir,
                visual_judge_pass_threshold=8.5,
                visual_judge_max_concurrency=6,
            ),
        )

    assert captured == [(8.5, 6)]


def test_step_forwards_judges_to_verifiers_factory(
    tmp_path: Path,
) -> None:
    """Impl plan T3.3: ``ctx.config.judges`` reaches the verifiers factory."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    captured_judges: list[frozenset[str]] = []

    def _verifiers_factory(
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
        judges: frozenset[str] = frozenset(),
        visual_retry_budget: int = 3,
        visual_judge_pass_threshold: float = 7.0,
        visual_judge_max_concurrency: int = 3,
    ) -> tuple[Verifier, ...]:
        del out_dir, sidecar, visual_retry_budget
        del visual_judge_pass_threshold, visual_judge_max_concurrency
        captured_judges.append(judges)
        return ()

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    selected = frozenset({"visual_judge"})
    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir, judges=selected))

    assert captured_judges == [selected]


# --------------------------------------------------------------------------- #
# Step.run wires the harness with the expected config
# --------------------------------------------------------------------------- #


def test_step_run_passes_expected_loop_config_to_harness(tmp_path: Path) -> None:
    """T5.6 contract: harness sees the merged manual + the hydrogen + the dataset.

    Stubs every external seam:

    * the runtime factory returns a no-op runtime;
    * the sidecar factory yields a fake handle;
    * the verifiers factory captures the sidecar handle and returns a
      single sentinel verifier;
    * the loop runner captures the :class:`PlanExecLoopConfig` rather
      than calling :func:`harness.run_plan_exec_loop`.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    captured_configs: list[PlanExecLoopConfig] = []
    captured_runtimes: list[AgentRuntime] = []
    captured_force: list[bool] = []
    captured_handles: list[SidecarHandle] = []

    class _Sentinel:
        name = "sentinel"

        def applies_to(self, task_id: str) -> bool:
            return task_id == "consolidate"

        def run(self, ctx: VerifierContext) -> VerifierResult:  # pragma: no cover
            del ctx
            raise AssertionError("sentinel verifier was dispatched")

    sentinel: Verifier = _Sentinel()

    def _verifiers_factory(
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
        judges: frozenset[str] = frozenset(),
        visual_retry_budget: int = 3,
        visual_judge_pass_threshold: float = 7.0,
        visual_judge_max_concurrency: int = 3,
    ) -> tuple[Verifier, ...]:
        del out_dir, judges, visual_retry_budget
        del visual_judge_pass_threshold, visual_judge_max_concurrency
        captured_handles.append(sidecar)
        return (sentinel,)

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        captured_configs.append(config)
        captured_runtimes.append(runtime)
        captured_force.append(force)
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    stub_runtime = _StubRuntime()
    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(stub_runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir, max_iters=_CFG_MAX_ITERS))

    # Loop runner saw exactly one config + the runtime we injected.
    assert len(captured_configs) == 1
    cfg = captured_configs[0]
    assert captured_runtimes == [stub_runtime]
    assert captured_force == [True]
    assert captured_handles == [_stub_handle()]

    # Run dir lives under <out_dir>/runs/build/.
    assert cfg.run_dir == out_dir / "runs" / "build"
    # Manual is the seed dir per spec §5.5.
    assert cfg.artifact_seed_dir == out_dir / "manual"
    # Prompts are the in-repo bodies from T5.3.
    assert cfg.prompts.planner == load_planner_prompt()
    assert cfg.prompts.execute == load_execute_prompt()
    assert cfg.agents_md == load_agents_md()
    # max_iters tracks ShopGenConfig.
    assert cfg.max_iters == _CFG_MAX_ITERS
    # Verifier set is what the factory returned.
    assert cfg.verifiers == (sentinel,)


def test_step_run_seeds_only_manual_and_layers_hydrogen_data_after(tmp_path: Path) -> None:
    """Spec §5.5: only the manual is seeded; hydrogen + data live alongside it."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    seed_manifest_at_runner: list[set[str]] = []

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        manifest_path = config.run_dir / ".harness" / "seed_manifest.json"
        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            seed_manifest_at_runner.append(set(payload["seeded_roots"]))
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir))

    run_dir = out_dir / "runs" / "build"
    artifact = run_dir / "artifact"

    # Manual landed under the seeded subtree.
    for name in ("capabilities.json", "manual.md", "stats.json", "manifest.json"):
        assert (artifact / name).is_file(), f"missing {name} under {artifact}"

    # Hydrogen + data trees landed alongside it (mutable per spec §5.5).
    assert (artifact / "hydrogen" / "package.json").is_file()
    assert (artifact / "hydrogen" / "app" / "root.tsx").is_file()
    assert (artifact / "data" / "collections.json").is_file()

    # Seed manifest only tracks the manual entries (hydrogen + data are
    # NOT in seeded_roots — they stay outside seed-immutability).
    assert len(seed_manifest_at_runner) == 1
    seeded_roots = seed_manifest_at_runner[0]
    assert "hydrogen" not in seeded_roots
    assert "data" not in seeded_roots
    assert seeded_roots == {
        "capabilities.json",
        "manual.md",
        "stats.json",
        "manifest.json",
    }


def test_step_run_rebuilds_artifact_subtrees_when_source_drifts(tmp_path: Path) -> None:
    """Mutating ``<out_dir>/hydrogen/`` between runs propagates to the artifact tree.

    Spec §§5.5 / 5.7: ``clone_template`` and ``run_build_harness_loop`` cooperate
    via a content-fingerprint stamp under
    ``runs/build/artifact/.shop_gen/source_fingerprint``. When the upstream
    tree changes — e.g. after a ``CloneTemplateStep.version`` bump —
    ``_setup_run_dir`` wipes and re-copies the source-derived subtrees in
    place so the fixed template actually reaches the tree the harness
    boots. Three :meth:`step.run` invocations exercise:

    1. fresh workspace → install runs once;
    2. no source change → fast path, no extra install;
    3. mutated source → drift detected, artifact rebuilt, install re-runs.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    install_invocations: list[Path] = []

    def _tracking_install_runner(
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
    ) -> CompletedSubprocess:
        del argv, timeout
        install_invocations.append(cwd)
        return CompletedSubprocess(returncode=0, stdout="", stderr="")

    def _noop_loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_noop_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_tracking_install_runner,
    )

    artifact_pkg = out_dir / "runs" / "build" / "artifact" / "hydrogen" / "package.json"
    source_pkg = out_dir / "hydrogen" / "package.json"

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        # 1. Fresh workspace — install runs once.
        step.run(_build_ctx(out_dir))
        assert artifact_pkg.read_text(encoding="utf-8") == '{"name":"hydrogen"}\n'
        assert len(install_invocations) == 1

        # 2. No source change — fast path, no extra install.
        step.run(_build_ctx(out_dir))
        assert len(install_invocations) == 1, (
            "install re-ran despite no source change: "
            f"{install_invocations}"
        )

        # Mutate the source tree (simulates clone_template re-running with a
        # fixed template after a version bump).
        source_pkg.write_text('{"name":"hydrogen-v2"}\n', encoding="utf-8")

        # 3. Drift detected — artifact rebuilt, install re-invoked.
        step.run(_build_ctx(out_dir))
        assert artifact_pkg.read_text(encoding="utf-8") == '{"name":"hydrogen-v2"}\n'
        assert len(install_invocations) == 2, (  # noqa: PLR2004
            "install did not re-run after source drift: "
            f"{install_invocations}"
        )

def test_step_run_raises_when_manual_dir_missing(tmp_path: Path) -> None:
    """Missing ``manual/`` is a workflow bug, not a silent fallback."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)
    # Drop the manual dir so the step raises before any harness call.
    for child in (out_dir / "manual").iterdir():
        child.unlink()
    (out_dir / "manual").rmdir()

    def _failing_loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del config, runtime, force
        pytest.fail("loop runner should not be reached")

    step = RunBuildHarnessLoopStep(
        loop_runner=_failing_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with (
        patch(
            "shop_gen.build.loop.find_shop_backend_cli",
            return_value=_shop_backend_cli_stub(),
        ),
        pytest.raises(FileNotFoundError, match="manual_dir"),
    ):
        step.run(_build_ctx(out_dir))


def test_step_run_holds_sidecar_open_for_loop_call(tmp_path: Path) -> None:
    """The sidecar is live for the harness invocation and torn down on exit."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar_active: list[bool] = []
    enter_calls: list[int] = []
    exit_calls: list[int] = []

    @contextlib.contextmanager
    def _tracking_sidecar(*, argv: Sequence[str], port: int) -> Iterator[SidecarHandle]:
        del argv, port
        enter_calls.append(1)
        try:
            yield _stub_handle()
        finally:
            exit_calls.append(1)

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        # The handle has been yielded → enter has been called once and
        # exit has not yet fired.
        sidecar_active.append(len(enter_calls) == 1 and not exit_calls)
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_tracking_sidecar,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir))

    assert sidecar_active == [True]
    assert enter_calls == [1]
    assert exit_calls == [1]


# --------------------------------------------------------------------------- #
# Integration test under ReplayRuntime (impl plan T5.6 check)
# --------------------------------------------------------------------------- #


_REPLAY_PLAN_MD: Final[str] = (
    "# Plan\n\n## Tasks\n- [x] gen_theme   [priority: 9]\n- [x] consolidate   [priority: 1]\n"
)
"""Plan body the replay cassette emits — already-done so the executor loop drains immediately.

Includes the canonical ``consolidate`` task so the orchestrator's
spec §5.5.4 fallback (T5.8) finds the contract already satisfied and
does not re-invoke the harness.
"""


def _seed_replay_cassette(scenario_dir: Path) -> None:
    """Hand-craft a single-iteration replay cassette."""
    plan_dir = scenario_dir / "plan"
    workspace_after = plan_dir / "workspace_after"
    workspace_after.mkdir(parents=True)
    (workspace_after / "plan.md").write_text(_REPLAY_PLAN_MD, encoding="utf-8")
    trajectory = {
        "iter_id": "plan",
        "runtime": "replay",
        "started_at": "2026-04-25T10:40:02.156640+00:00",
        "ended_at": "2026-04-25T10:40:02.500000+00:00",
        "exit_code": 0,
        "prompt_sha256": "0" * 64,
        "steps": [
            {
                "timestamp": "2026-04-25T10:40:02.156640+00:00",
                "kind": "message",
                "role": "assistant",
                "text": "wrote plan",
            },
        ],
    }
    (plan_dir / "trajectory.json").write_text(
        json.dumps(trajectory, indent=2),
        encoding="utf-8",
    )


def test_step_run_drives_real_harness_with_replay_runtime(tmp_path: Path) -> None:
    """End-to-end: ReplayRuntime + the real harness consumes the loop config.

    Asserts the harness:

    * created ``runs/build/run.json`` (loop completed cleanly);
    * persisted the seed manifest only against the manual subtree;
    * preserved the ``run_dir/artifact/hydrogen/`` work surface.

    The cassette emits an already-done plan so no executor iteration is
    needed; the integration covers workspace setup + the planner call
    end-to-end.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    scenario_dir = tmp_path / "cassette"
    _seed_replay_cassette(scenario_dir)

    runtime = ReplayRuntime(scenario_dir)
    step = RunBuildHarnessLoopStep(
        runtime_factory=_stub_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir, max_iters=4))

    run_dir = out_dir / "runs" / "build"
    run_summary = run_dir / "run.json"
    assert run_summary.is_file()
    summary = json.loads(run_summary.read_text(encoding="utf-8"))
    assert summary["final_status"] == "completed"

    # Seed manifest tracks only the manual subtree.
    manifest_path = run_dir / ".harness" / "seed_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["seeded_roots"]) == {
        "capabilities.json",
        "manual.md",
        "stats.json",
        "manifest.json",
    }

    # Hydrogen + data trees survive alongside the seeded entries.
    artifact = run_dir / "artifact"
    assert (artifact / "hydrogen" / "app" / "root.tsx").is_file()
    assert (artifact / "data" / "collections.json").is_file()


# --------------------------------------------------------------------------- #
# Default verifier factory shape (the v0.1 set)
# --------------------------------------------------------------------------- #


def test_default_verifiers_factory_returns_v01_set_when_skill_missing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec §5.5.3 + impl plan T1.5: skill missing → visual_judge omitted with one warning.

    ``NoBrandLeakVerifier`` is deliberately omitted: commit ``e54c98f``
    disabled it in the factory because the allowlist tokenizer flagged
    React / Hydrogen / TS identifiers the template legitimately imports
    (``Route``, ``LoaderArgs``, ``Money``, ``CartForm``, …) and produced
    thousands of false positives the agent could not fix. The brand-
    safety contract is now carried by the AGENTS.md "Don'ts" bullet.

    SC7 (skill-probe failure path): the factory drops ``visual_judge``
    from the tuple and emits exactly one ``WARNING`` with the install
    hint; rule verifiers are still present.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with (
        patch("shop_gen.build.loop.is_playwright_skill_available", return_value=False),
        caplog.at_level("WARNING", logger="shop_gen.build.loop"),
    ):
        verifiers = default_verifiers_factory(out_dir=out_dir, sidecar=sidecar)

    types = [type(v) for v in verifiers]
    assert types == [
        TscVerifier,
        BuildVerifier,
        DataInUseVerifier,
        NavCoverageVerifier,
        NavigationPrimitiveUsageVerifier,
        Routes200Verifier,
        QualityJudgeVerifier,
        CrossTaskConsistencyVerifier,
    ]

    visual_warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "visual_judge" in record.getMessage()
    ]
    assert len(visual_warnings) == 1
    assert "pi-playwright" in visual_warnings[0].getMessage()


def test_default_verifiers_factory_includes_visual_judge_when_skill_present(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Impl plan T1.5: skill present → visual_judge slots between quality_judge and cross_task."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with (
        patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True),
        caplog.at_level("WARNING", logger="shop_gen.build.loop"),
    ):
        verifiers = default_verifiers_factory(out_dir=out_dir, sidecar=sidecar)

    types = [type(v) for v in verifiers]
    assert types == [
        TscVerifier,
        BuildVerifier,
        DataInUseVerifier,
        NavCoverageVerifier,
        NavigationPrimitiveUsageVerifier,
        Routes200Verifier,
        QualityJudgeVerifier,
        VisualJudgeVerifier,
        CrossTaskConsistencyVerifier,
    ]
    # No skill-probe warning when the skill is present.
    assert not [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "visual_judge" in record.getMessage()
    ]


def test_default_verifiers_factory_threads_visual_retry_budget(
    tmp_path: Path,
) -> None:
    """Impl plan T2.3: ``visual_retry_budget`` is forwarded to the verifier."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            visual_retry_budget=0,
        )

    visual = next(v for v in verifiers if isinstance(v, VisualJudgeVerifier))
    assert visual._retry_budget == 0


def test_default_verifiers_factory_uses_default_visual_retry_budget(
    tmp_path: Path,
) -> None:
    """Impl plan T2.3: omitting the kwarg keeps the spec §5.4 default of 3."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True):
        verifiers = default_verifiers_factory(out_dir=out_dir, sidecar=sidecar)

    visual = next(v for v in verifiers if isinstance(v, VisualJudgeVerifier))
    assert visual._retry_budget == DEFAULT_VISUAL_RETRY_BUDGET
    assert visual._pass_threshold == DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD
    assert visual._max_concurrency == DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY


def test_default_verifiers_factory_threads_visual_judge_pass_threshold(
    tmp_path: Path,
) -> None:
    """Impl plan T3.6: ``visual_judge_pass_threshold`` is forwarded to the verifier."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            visual_judge_pass_threshold=8.5,
        )

    visual = next(v for v in verifiers if isinstance(v, VisualJudgeVerifier))
    assert visual._pass_threshold == 8.5  # noqa: PLR2004 -- mirrors fixture


def test_default_verifiers_factory_threads_visual_judge_max_concurrency(
    tmp_path: Path,
) -> None:
    """Impl plan T3.6: ``visual_judge_max_concurrency`` is forwarded to the verifier."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            visual_judge_max_concurrency=6,
        )

    visual = next(v for v in verifiers if isinstance(v, VisualJudgeVerifier))
    assert visual._max_concurrency == 6  # noqa: PLR2004 -- mirrors fixture


def test_default_verifiers_factory_registers_navigation_primitive_usage_as_hard_fail(
    tmp_path: Path,
) -> None:
    """Impl plan T5.1: ``navigation_primitive_usage`` is HARD-FAIL in M5.

    The verifier slots between the rule verifiers and the LLM judges, and is
    constructed without the ``advisory=True`` kwarg so a failing scan blocks
    the iteration (rewriting the selected task's marker back to ``[~]``).
    Promoted from advisory (M4 / T4.2) once the post-M2 cassette validated the
    primitive contract end-to-end via
    ``test_build_loop_replay_post_build_artifact_imports_navigation_primitives``.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True):
        verifiers = default_verifiers_factory(out_dir=out_dir, sidecar=sidecar)

    matches = [v for v in verifiers if isinstance(v, NavigationPrimitiveUsageVerifier)]
    assert len(matches) == 1, "`navigation_primitive_usage` registers exactly once"
    assert matches[0].name == "navigation_primitive_usage"
    assert matches[0]._advisory is False


def test_default_verifiers_factory_judges_empty_returns_only_rule_verifiers(
    tmp_path: Path,
) -> None:
    """Impl plan T3.2: ``judges=frozenset()`` drops every LLM judge; rule verifiers stay."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            judges=frozenset(),
        )

    types = [type(v) for v in verifiers]
    assert types == [
        TscVerifier,
        BuildVerifier,
        DataInUseVerifier,
        NavCoverageVerifier,
        NavigationPrimitiveUsageVerifier,
        Routes200Verifier,
    ]


def test_default_verifiers_factory_judges_visual_only_when_skill_present(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Impl plan T3.2: ``judges={"visual_judge"}`` includes exactly that LLM judge."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with (
        patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True),
        caplog.at_level("WARNING", logger="shop_gen.build.loop"),
    ):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            judges=frozenset({"visual_judge"}),
        )

    types = [type(v) for v in verifiers]
    assert types == [
        TscVerifier,
        BuildVerifier,
        DataInUseVerifier,
        NavCoverageVerifier,
        NavigationPrimitiveUsageVerifier,
        Routes200Verifier,
        VisualJudgeVerifier,
    ]
    assert not [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "visual_judge" in record.getMessage()
    ]


def test_default_verifiers_factory_judges_visual_only_skill_missing_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Impl plan T3.2: ``judges={"visual_judge"}`` + skill missing.

    Expected: rule verifiers only + a single warning logged.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with (
        patch("shop_gen.build.loop.is_playwright_skill_available", return_value=False),
        caplog.at_level("WARNING", logger="shop_gen.build.loop"),
    ):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            judges=frozenset({"visual_judge"}),
        )

    types = [type(v) for v in verifiers]
    assert types == [
        TscVerifier,
        BuildVerifier,
        DataInUseVerifier,
        NavCoverageVerifier,
        NavigationPrimitiveUsageVerifier,
        Routes200Verifier,
    ]
    visual_warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "visual_judge" in record.getMessage()
    ]
    assert len(visual_warnings) == 1
    assert "pi-playwright" in visual_warnings[0].getMessage()


# --------------------------------------------------------------------------- #
# SC5 — judges subset registration (impl plan T3.5, spec §5.5 + §5.9)
# --------------------------------------------------------------------------- #


def test_default_verifiers_factory_sc5_judges_visual_and_quality_excludes_cross_task(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SC5 (case 1): ``--judges visual_judge,quality_judge`` registers exactly those two LLM judges.

    Skill present → ``visual_judge`` is included; ``cross_task_consistency`` is absent.
    Asserts ``verifier_runs by name``: each LLM-judge name appears exactly once,
    ``cross_task_consistency`` does not appear at all, and the rule verifiers
    are still present.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with (
        patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True),
        caplog.at_level("WARNING", logger="shop_gen.build.loop"),
    ):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            judges=frozenset({"visual_judge", "quality_judge"}),
        )

    names_by_count: dict[str, int] = {}
    for v in verifiers:
        names_by_count[v.name] = names_by_count.get(v.name, 0) + 1

    # Both selected LLM judges register exactly once.
    assert names_by_count.get("visual_judge") == 1
    assert names_by_count.get("quality_judge") == 1
    # The unselected LLM judge is absent.
    assert "cross_task_consistency" not in names_by_count
    # Rule verifiers are unaffected by ``judges``.
    for rule_name in (
        "tsc",
        "build",
        "data_in_use",
        "nav_coverage",
        "navigation_primitive_usage",
        "routes_200",
    ):
        assert names_by_count.get(rule_name) == 1, f"missing rule verifier: {rule_name}"
    # Skill present → no probe-failure warning.
    assert not [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "visual_judge" in record.getMessage()
    ]


def test_default_verifiers_factory_sc5_judges_none_registers_zero_llm_judges(
    tmp_path: Path,
) -> None:
    """SC5 (case 2): ``--judges none`` registers zero LLM judges.

    Asserts ``verifier_runs by name``: none of the three known LLM-judge
    names appear in the resolved tuple; only the rule verifiers do.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    sidecar = _stub_handle()
    with patch("shop_gen.build.loop.is_playwright_skill_available", return_value=True):
        verifiers = default_verifiers_factory(
            out_dir=out_dir,
            sidecar=sidecar,
            judges=frozenset(),
        )

    names = [v.name for v in verifiers]
    llm_judges = {"visual_judge", "quality_judge", "cross_task_consistency"}
    assert llm_judges.isdisjoint(names)
    # Rule verifiers still register exactly once each.
    for rule_name in (
        "tsc",
        "build",
        "data_in_use",
        "nav_coverage",
        "navigation_primitive_usage",
        "routes_200",
    ):
        assert names.count(rule_name) == 1, f"missing rule verifier: {rule_name}"


# --------------------------------------------------------------------------- #
# Default introspector wiring
# --------------------------------------------------------------------------- #


_INTROSPECTOR_BASE_URL: Final[str] = "http://127.0.0.1:9999"
"""Loopback URL the introspector tests pretend the sidecar is bound to."""


def _introspection_response(
    *,
    query_fields: Sequence[str] = (),
    mutation_fields: Sequence[str] | None = (),
    subscription_fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Render a GraphQL introspection response with the given root fields.

    A ``None`` value for ``mutation_fields`` / ``subscription_fields``
    encodes the schema not exposing that root (the standard introspection
    shape returns ``null`` for the slot in that case).
    """

    def _slot(names: Sequence[str] | None) -> dict[str, Any] | None:
        if names is None:
            return None
        return {"fields": [{"name": n} for n in names]}

    return {
        "data": {
            "__schema": {
                "queryType": _slot(query_fields),
                "mutationType": _slot(mutation_fields),
                "subscriptionType": _slot(subscription_fields),
            },
        },
    }


@respx.mock
def test_default_introspector_translates_root_fields() -> None:
    """The default introspector POSTs to ``/graphql`` and indexes root fields."""
    route = respx.post(f"{_INTROSPECTOR_BASE_URL}/graphql").mock(
        return_value=httpx.Response(
            200,
            json=_introspection_response(
                query_fields=("shop", "products"),
                mutation_fields=("cartCreate",),
                subscription_fields=None,
            ),
        ),
    )

    schema = _GraphqlIntrospector(base_url=_INTROSPECTOR_BASE_URL)()

    assert route.called
    request = route.calls.last.request
    assert json.loads(request.content)["query"].lstrip().startswith("{")
    assert schema.fields_for("Query") == frozenset({"shop", "products"})
    assert schema.fields_for("Mutation") == frozenset({"cartCreate"})
    # ``subscriptionType: null`` → the verifier sees an empty set, not a KeyError.
    assert schema.fields_for("Subscription") == frozenset()


@respx.mock
def test_default_introspector_raises_on_graphql_errors() -> None:
    """A ``data: null, errors: [...]`` payload is surfaced as ``RuntimeError``."""
    respx.post(f"{_INTROSPECTOR_BASE_URL}/graphql").mock(
        return_value=httpx.Response(
            200,
            json={"errors": [{"message": "schema unavailable"}]},
        ),
    )

    with pytest.raises(RuntimeError, match="schema unavailable"):
        _GraphqlIntrospector(base_url=_INTROSPECTOR_BASE_URL)()


@respx.mock
def test_default_introspector_raises_on_http_error() -> None:
    """A non-2xx response is surfaced as :class:`httpx.HTTPStatusError`."""
    respx.post(f"{_INTROSPECTOR_BASE_URL}/graphql").mock(
        return_value=httpx.Response(500, text="boom"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        _GraphqlIntrospector(base_url=_INTROSPECTOR_BASE_URL)()


# --------------------------------------------------------------------------- #
# Consolidate-task contract (T5.8)
# --------------------------------------------------------------------------- #


_PLAN_WITHOUT_CONSOLIDATE: Final[str] = "# Plan\n\n## Tasks\n- [x] gen_theme — done [priority: 9]\n"
"""Planner output that omitted the mandatory ``consolidate`` task."""

_PLAN_WITH_CONSOLIDATE: Final[str] = (
    "# Plan\n\n## Tasks\n"
    "- [x] gen_theme — done [priority: 9]\n"
    "- [x] consolidate — already-emitted [priority: 1]\n"
)
"""Compliant planner output — consolidate is already emitted."""


def test_step_run_appends_consolidate_when_planner_omits_it(tmp_path: Path) -> None:
    """T5.8: orchestrator appends ``consolidate`` to ``plan.md`` and resumes the harness."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    plan_path = out_dir / "runs" / "build" / "plan.md"
    call_count = {"n": 0}

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        call_count["n"] += 1
        # First call simulates the planner writing a plan WITHOUT consolidate.
        # Subsequent (resume) calls find the appended ``consolidate`` task and
        # are no-ops as far as the test is concerned.
        if call_count["n"] == 1:
            plan_path.write_text(_PLAN_WITHOUT_CONSOLIDATE, encoding="utf-8")
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=1,
            exec_iter_count=1,
            trajectory_paths=(
                "iters/plan/trajectory.json",
                "iters/exec-0001/trajectory.json",
            ),
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir))

    # Loop ran twice: once for the original plan, once after the orchestrator
    # appended the missing consolidate task.
    assert call_count["n"] == 2  # noqa: PLR2004 — 1 initial + 1 resume after fallback

    # The on-disk plan.md now carries a PENDING ``consolidate`` task.
    after = plan_path.read_text(encoding="utf-8")
    assert "consolidate" in after
    consolidate_lines = [
        line for line in after.splitlines() if line.startswith("- [") and "consolidate" in line
    ]
    assert len(consolidate_lines) == 1
    assert consolidate_lines[0].startswith("- [ ] consolidate")


def test_step_run_skips_consolidate_append_when_planner_emits_it(tmp_path: Path) -> None:
    """When the planner emits ``consolidate`` the orchestrator does not double-invoke."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    plan_path = out_dir / "runs" / "build" / "plan.md"
    call_count = {"n": 0}

    def _loop_runner(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        del runtime, force
        call_count["n"] += 1
        if call_count["n"] == 1:
            plan_path.write_text(_PLAN_WITH_CONSOLIDATE, encoding="utf-8")
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=1,
            exec_iter_count=1,
            trajectory_paths=(
                "iters/plan/trajectory.json",
                "iters/exec-0001/trajectory.json",
            ),
        )

    step = RunBuildHarnessLoopStep(
        loop_runner=_loop_runner,
        runtime_factory=_stub_runtime_factory_for(_StubRuntime()),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    before = None
    with patch(
        "shop_gen.build.loop.find_shop_backend_cli",
        return_value=_shop_backend_cli_stub(),
    ):
        step.run(_build_ctx(out_dir))
        before = plan_path.read_text(encoding="utf-8")

    # Single loop call — the planner satisfied the contract.
    assert call_count["n"] == 1
    # Plan.md is unchanged from what the planner wrote.
    assert before == _PLAN_WITH_CONSOLIDATE
