"""End-to-end replay test for the Phase 4 build loop (T5.9).

Drives :class:`shop_arena.gen.build.loop.RunBuildHarnessLoopStep` through the
hand-crafted ``fixture_build_loop`` cassette under
:class:`harness.runtimes.replay.ReplayRuntime`. The cassette covers the
four canonical build-loop tasks documented in
``docs/specs/shop_arena/shop_arena.gen.md`` §5.5: ``gen_theme``,
``gen_navigation``, ``gen_homepage``, and the mandatory ``visual_fix``
cleanup pass.

This is the milestone gate for the build-loop driver: the loop step
runs end-to-end without any LLM call, sidecar subprocess, or network
I/O so the Phase 4 driver is exercised deterministically in CI.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

import pytest

from harness import AgentRuntime, Verifier
from harness.plan import parse as parse_plan
from harness.plan.tasks import TaskStatus
from harness.runtimes.replay import ReplayRuntime
from shop_arena.gen.build.loop import RunBuildHarnessLoopStep, RuntimeFactory
from shop_arena.gen.build.sidecar import SidecarHandle
from shop_arena.gen.build.verifiers._subprocess import CompletedSubprocess
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_CASSETTE_DIR: Final[Path] = Path(__file__).resolve().parent / "cassettes" / "fixture_build_loop"
"""Hand-crafted cassette root."""

_EXPECTED_TASK_ORDER: Final[tuple[str, ...]] = (
    "gen_theme",
    "gen_navigation",
    "gen_homepage",
    "visual_fix",
)
"""Order ``select_next`` walks the cassette plan (highest priority wins)."""

_EXPECTED_HYDROGEN_FILES: Final[tuple[str, ...]] = (
    "app/styles/theme.css",
    "app/components/Header.tsx",
    "app/components/Footer.tsx",
    "app/routes/_index.tsx",
    "VISUAL_FIX.md",
)
"""Hydrogen files the four executor iterations layer onto the work surface."""

_PORT: Final[int] = 54321
"""Fixed port the test workspace's ``.env`` advertises."""

_BASE_URL: Final[str] = f"http://127.0.0.1:{_PORT}"
"""Base URL the stub sidecar reports."""


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


def _stub_handle() -> SidecarHandle:
    """Stand-in :class:`SidecarHandle` that the loop's verifier factory sees."""
    return SidecarHandle(pid=12345, port=_PORT, base_url=_BASE_URL, store_name="Stub")


@contextlib.contextmanager
def _stub_sidecar_factory(*, argv: Sequence[str], port: int) -> Iterator[SidecarHandle]:
    """Sidecar factory that never spawns a subprocess."""
    del argv
    assert port == _PORT
    yield _stub_handle()


def _stub_install_runner(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
) -> CompletedSubprocess:
    """Stub :class:`SubprocessRunner` for the per-run ``pnpm install``."""
    del argv, cwd, timeout
    return CompletedSubprocess(returncode=0, stdout="", stderr="")


def _empty_verifiers_factory(
    *,
    out_dir: Path,
    sidecar: SidecarHandle,
    judges: frozenset[str] = frozenset(),
    visual_retry_budget: int = 3,
    visual_judge_pass_threshold: float = 7.0,
    visual_judge_max_concurrency: int = 3,
) -> tuple[Verifier, ...]:
    """Skip the v0.1 verifier set — T5.9 covers the loop driver only."""
    del out_dir, sidecar, judges, visual_retry_budget
    del visual_judge_pass_threshold, visual_judge_max_concurrency
    return ()


def _runtime_factory_for(runtime: AgentRuntime) -> RuntimeFactory:
    """Wrap ``runtime`` in a :class:`RuntimeFactory`."""

    def _factory(config: ShopGenConfig) -> AgentRuntime:
        del config
        return runtime

    return _factory


# --------------------------------------------------------------------------- #
# Workspace fixtures
# --------------------------------------------------------------------------- #


def _materialise_workspace(out_dir: Path) -> None:
    """Lay down the manual + data + hydrogen sub-trees the loop step requires."""
    manual_dir = out_dir / "manual"
    manual_dir.mkdir(parents=True)
    (manual_dir / "capabilities.json").write_text("{}", encoding="utf-8")
    (manual_dir / "manual.md").write_text("# manual\n", encoding="utf-8")
    (manual_dir / "stats.json").write_text("{}", encoding="utf-8")
    (manual_dir / "manifest.json").write_text("{}", encoding="utf-8")

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)
    for name in ("store.json", "collections.json", "policies.json", "navigation.json"):
        (data_dir / name).write_text("[]", encoding="utf-8")
    # Default-task-routes lookup hydrates the first handle from each list.
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


def _shop_backend_cli_stub() -> Path:
    """Path the loop step accepts as the bundled CLI without spawning anything."""
    return Path(__file__).resolve()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_build_loop_replay_drives_four_canonical_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cassette drives planner + four executor iterations end-to-end.

    Asserts the harness:

    * created ``runs/build/run.json`` with ``final_status=completed``;
    * ran the planner plus four executor iterations in priority order
      (``gen_theme`` → ``gen_navigation`` → ``gen_homepage`` →
      ``visual_fix``);
    * preserved the cassette's hydrogen mutations under
      ``runs/build/artifact/hydrogen/``;
    * persisted the seed manifest only against the manual subtree
      (mutable hydrogen + data trees stay outside seed-immutability per
      spec §5.5).

    No LLM is consulted, no sidecar is spawned, no API key is required.
    """
    monkeypatch.setattr(
        "shop_arena.gen.build.loop.find_shop_backend_cli",
        _shop_backend_cli_stub,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    runtime = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    step = RunBuildHarnessLoopStep(
        runtime_factory=_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    step.run(_build_ctx(out_dir, max_iters=len(_EXPECTED_TASK_ORDER) + 1))

    run_dir = out_dir / "runs" / "build"
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    # Loop reached COMPLETED with the planner + four executor iterations.
    assert summary["final_status"] == "completed"
    assert summary["plan_iter_count"] == 1
    assert summary["exec_iter_count"] == len(_EXPECTED_TASK_ORDER)

    # Plan.md ended with every cassette task DONE in priority order.
    plan_md = (run_dir / "plan.md").read_text(encoding="utf-8")
    plan = parse_plan(plan_md)
    assert tuple(t.id for t in plan.tasks) == _EXPECTED_TASK_ORDER
    assert all(t.status is TaskStatus.DONE for t in plan.tasks)

    # Every iteration left a trajectory.json on disk.
    iters_root = run_dir / "iters"
    assert (iters_root / "plan" / "trajectory.json").is_file()
    for n in range(1, len(_EXPECTED_TASK_ORDER) + 1):
        assert (iters_root / f"exec-{n:04d}" / "trajectory.json").is_file(), (
            f"missing trajectory.json for exec-{n:04d}"
        )

    # Cassette hydrogen mutations accumulated alongside the seeded manual.
    artifact = run_dir / "artifact"
    for relative in _EXPECTED_HYDROGEN_FILES:
        path = artifact / "hydrogen" / relative
        assert path.is_file(), f"cassette did not deliver {relative}"

    # Seed manifest tracks only the manual subtree — hydrogen + data stay mutable.
    manifest_path = run_dir / ".harness" / "seed_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["seeded_roots"]) == {
        "capabilities.json",
        "manual.md",
        "stats.json",
        "manifest.json",
    }


def test_build_loop_replay_records_selected_task_per_iteration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each executor iteration's metadata names the task the harness selected.

    Confirms the cassette and the harness agree on which task is in
    flight every iteration. Spec §5.5 + §5.5.4: ``visual_fix`` is
    dispatched last because it has the lowest priority.
    """
    monkeypatch.setattr(
        "shop_arena.gen.build.loop.find_shop_backend_cli",
        _shop_backend_cli_stub,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    runtime = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    step = RunBuildHarnessLoopStep(
        runtime_factory=_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    step.run(_build_ctx(out_dir, max_iters=len(_EXPECTED_TASK_ORDER) + 1))

    iters_root = out_dir / "runs" / "build" / "iters"
    selected_per_iter: list[str] = []
    for n in range(1, len(_EXPECTED_TASK_ORDER) + 1):
        metadata_path = iters_root / f"exec-{n:04d}" / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        selected_per_iter.append(metadata["selected_task_id"])

    assert tuple(selected_per_iter) == _EXPECTED_TASK_ORDER


def test_build_loop_replay_post_build_artifact_imports_navigation_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-`gen_navigation` `Header.tsx` + `Footer.tsx` adopt the M2/M3 primitives.

    Per
    ``docs/specs/shop_arena/template_navigation_primitives.md`` §"Acceptance"
    and the M2 cassette-regeneration check in
    ``docs/impl/template_navigation_primitives_implementation.md`` T2.8: a
    post-build ``Header.tsx`` must import ``<NavMenu>`` and
    ``<HeaderShell>``, and a post-build ``Footer.tsx`` must import
    ``<FooterColumns>``. This test is the concrete gate — a future
    cassette regeneration that drops the imports lights up here, and
    ``navigation_primitive_usage`` (T4.1, advisory in M4 → hard-fail in
    M5) gates the same contract on every live build loop.
    """
    monkeypatch.setattr(
        "shop_arena.gen.build.loop.find_shop_backend_cli",
        _shop_backend_cli_stub,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    runtime = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    step = RunBuildHarnessLoopStep(
        runtime_factory=_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_empty_verifiers_factory,
        install_runner=_stub_install_runner,
    )

    step.run(_build_ctx(out_dir, max_iters=len(_EXPECTED_TASK_ORDER) + 1))

    artifact = out_dir / "runs" / "build" / "artifact" / "hydrogen"
    header_src = (artifact / "app" / "components" / "Header.tsx").read_text(encoding="utf-8")
    footer_src = (artifact / "app" / "components" / "Footer.tsx").read_text(encoding="utf-8")

    has_nav_menu = (
        "from \"~/components/NavMenu\"" in header_src
        or "from '~/components/NavMenu'" in header_src
    )
    has_header_shell = (
        "from \"~/components/HeaderShell\"" in header_src
        or "from '~/components/HeaderShell'" in header_src
    )
    has_footer_columns = (
        "from \"~/components/FooterColumns\"" in footer_src
        or "from '~/components/FooterColumns'" in footer_src
    )
    assert has_nav_menu, "Header.tsx must import <NavMenu> (template_navigation_primitives M2)"
    assert has_header_shell, (
        "Header.tsx must import <HeaderShell> (template_navigation_primitives M2)"
    )
    assert has_footer_columns, (
        "Footer.tsx must import <FooterColumns> (template_navigation_primitives M3)"
    )
