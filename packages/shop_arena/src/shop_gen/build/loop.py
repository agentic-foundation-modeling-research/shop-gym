"""Phase 4 ``run_build_harness_loop`` step (spec §5.5, T5.6).

Wires :class:`harness.PlanExecLoopConfig` against ``shop_gen``'s prompts
and verifier set, spawns the long-lived ``shop-backend`` sidecar the
build loop talks to, and invokes :func:`harness.run_plan_exec_loop`.

Spec contract (§5.5):

* The ``artifact_seed_dir`` is ``<out_dir>/manual/`` — only the manual
  is seeded (immutable). The cloned hydrogen tree under
  ``<out_dir>/hydrogen/`` and the assembled ``<out_dir>/data/`` tree are
  copied into ``<run_dir>/artifact/hydrogen/`` and
  ``<run_dir>/artifact/data/`` respectively *after* the harness
  populates the seed manifest, so they live outside the seeded subtree
  and stay mutable.
* The harness ``run_dir`` is ``<out_dir>/runs/build/``. The hydrogen
  work surface lives at ``<run_dir>/artifact/hydrogen/``.
* The verifier list is the v0.1 set from spec §5.5.3 + §5.5.4
  (``tsc``, ``build``, ``data_in_use``, ``nav_coverage``,
  ``no_brand_leak``, ``quality_judge``, ``cross_task_consistency``);
  callers can override via the ``verifiers_factory`` seam.

Step contract (spec §5.7.1):

* ``id``: ``run_build_harness_loop``.
* ``phase``: ``build``.
* ``inputs``: :class:`StepInput` for ``start_sidecar``, ``assemble_data``,
  and ``validate_hosting`` plus :class:`FileInput` references for
  ``hydrogen/package.json`` (clone sentinel) and ``hydrogen/.env``
  (sidecar URL source).
* ``outputs``: ``[runs/build/run.json]`` — the harness rewrites this
  after every iteration (plan_exec_loop spec §5.7).
* ``depends_on``: ``[start_sidecar, assemble_data, validate_hosting]``.

The defaults stitch together the production runtime / sidecar lifecycle
/ harness call. Tests inject stubs through the four seams
(``loop_runner``, ``runtime_factory``, ``sidecar_factory``,
``verifiers_factory``) so the integration test can drive a complete
loop config under :class:`harness.runtimes.replay.ReplayRuntime` without
spawning a real sidecar or shelling out to ``pnpm``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Final, Protocol, cast, runtime_checkable

import httpx

from harness import (
    AgentRuntime,
    PlanExecLoopConfig,
    PlanExecLoopResult,
    Prompts,
    Verifier,
    get_runtime,
    run_plan_exec_loop,
)
from harness.workspace import Workspace
from shop_gen.build.env import _CLONE_STEP_VERSION
from shop_gen.build.prompts import (
    load_agents_md,
    load_execute_prompt,
    load_planner_prompt,
)
from shop_gen.build.sidecar import (
    SidecarHandle,
    parse_port_from_env,
    sidecar_lifecycle,
)
from shop_gen.build.verifiers import (
    BuildVerifier,
    CrossTaskConsistencyVerifier,
    DataInUseVerifier,
    NavCoverageVerifier,
    NavigationPrimitiveUsageVerifier,
    QualityJudgeVerifier,
    Routes200Verifier,
    SchemaIntrospection,
    TscVerifier,
    VisualJudgeVerifier,
)
from shop_gen.build.verifiers._skills import is_playwright_skill_available
from shop_gen.build.verifiers._subprocess import (
    SubprocessRunner,
    default_subprocess_runner,
    truncate_stream,
)
from shop_gen.config import (
    DEFAULT_JUDGES,
    DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY,
    DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD,
    DEFAULT_VISUAL_RETRY_BUDGET,
    ShopGenConfig,
)
from shop_gen.data_validation.hosting_check import find_shop_backend_cli
from shop_gen.final_eval.dev_server import pnpm_dev_factory
from shop_gen.final_eval.playwright_smoke import DevServerFactory
from shop_gen.steps.base import FileInput, InputRef, StepContext, StepInput

_log = logging.getLogger(__name__)


_PHASE: Final[str] = "build"
_STEP_ID: Final[str] = "run_build_harness_loop"
_STEP_VERSION: Final[int] = 1

_UPSTREAM_START_SIDECAR: Final[str] = "start_sidecar"
_UPSTREAM_ASSEMBLE_DATA: Final[str] = "assemble_data"
_UPSTREAM_VALIDATE_HOSTING: Final[str] = "validate_hosting"

_HYDROGEN_DIR: Final[Path] = Path("hydrogen")
"""Run-relative path the template was cloned into (T5.1)."""

_HYDROGEN_ENV: Final[Path] = _HYDROGEN_DIR / ".env"
"""Run-relative path of the ``.env`` file produced by ``write_env_file``."""

_HYDROGEN_SENTINEL: Final[Path] = _HYDROGEN_DIR / "package.json"
"""Run-relative clone sentinel that mirrors ``CloneTemplateStep``'s output."""

_SOURCE_STAMP: Final[Path] = Path(".shop_gen") / "source_fingerprint"
"""Run-relative path of the artifact tree's source-fingerprint stamp.

Records the fingerprint of the source state (``<out_dir>/hydrogen/`` +
``<out_dir>/data/`` content, mixed with :data:`shop_gen.build.env._CLONE_STEP_VERSION`)
at the moment ``runs/build/`` was last materialised. ``_setup_run_dir``
compares this stamp against the current source fingerprint on every
invocation. A mismatch means the upstream source has changed (template
edited, ``CloneTemplateStep.version`` bumped, or ``assemble_data``
regenerated the data tree) and the prior ``runs/build/`` is rebuilt
from scratch — the executor's prior plan + iters are no longer
coherent with the new source.
"""

_DATA_DIR: Final[Path] = Path("data")
"""Run-relative path of the assembled SandboxShop dataset."""

_MANUAL_DIR: Final[Path] = Path("manual")
"""Run-relative path of the merged-or-copied manual."""

_RUN_DIR: Final[Path] = Path("runs") / "build"
"""Run-relative path of the harness ``run_dir``."""

_RUN_SUMMARY: Final[Path] = _RUN_DIR / "run.json"
"""Run-relative path of the harness's per-attempt run summary."""

_ARTIFACT_DIRNAME: Final[str] = "artifact"
"""Top-level subdir the harness owns under ``run_dir``."""

_DEFAULT_ITER_TIMEOUT_S: Final[float] = 3600.0
"""Default per-iteration wall-clock budget (1 hour). Conservative for cold
caches and long executor iterations that fan out into many tool calls."""

_INSTALL_TIMEOUT_S: Final[float] = 300.0
"""Wall-clock budget for the per-run ``pnpm install`` inside the artifact tree.

Cold pnpm-store on a fresh checkout fetches the full Hydrogen dep set
(~500 MB across hundreds of packages); 5 minutes leaves headroom. Warm
installs reuse the global content-addressable store and complete in
5-10 s, so the budget is rarely the binding constraint.
"""

_EMPTY_PLAN_MD: Final[str] = "# Plan\n\n## Tasks\n"
"""Minimal valid ``plan.md`` body the loop step writes after pre-creating
the workspace. The harness's ``Workspace.open`` re-entry path validates
``plan.md`` with :func:`harness.plan.parser.parse`, which requires a
``## Tasks`` heading. The planner iteration immediately overwrites this
stub with the real plan."""


# --------------------------------------------------------------------------- #
# Injection seams
# --------------------------------------------------------------------------- #


@runtime_checkable
class LoopRunner(Protocol):
    """Callable that drives one ``run_plan_exec_loop`` invocation.

    Production callers pass :func:`harness.run_plan_exec_loop` directly;
    tests inject a wrapper that captures the config payload before
    delegating (or stops short of the real harness for unit tests).
    """

    def __call__(
        self,
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        *,
        force: bool,
    ) -> PlanExecLoopResult:
        """Run the harness against ``config`` + ``runtime`` and return the result."""
        ...


@runtime_checkable
class RuntimeFactory(Protocol):
    """Callable that materialises an :class:`AgentRuntime` from the run config."""

    def __call__(self, config: ShopGenConfig) -> AgentRuntime:
        """Build the iteration-driving runtime for ``config``."""
        ...


@runtime_checkable
class SidecarFactory(Protocol):
    """Callable that yields a live :class:`SidecarHandle` for the build loop."""

    def __call__(
        self,
        *,
        argv: Sequence[str],
        port: int,
    ) -> AbstractContextManager[SidecarHandle]:
        """Return a context manager that owns the long-lived sidecar."""
        ...


@runtime_checkable
class VerifiersFactory(Protocol):
    """Callable that builds the ordered v0.1 verifier list at run time.

    The factory receives the run workspace + the live sidecar handle so
    verifiers that need the schema-introspection seam (``data_in_use``)
    can be wired against the same sidecar the agent talks to.
    """

    def __call__(
        self,
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
        judges: frozenset[str] = ...,
        visual_retry_budget: int = ...,
        visual_judge_pass_threshold: float = ...,
        visual_judge_max_concurrency: int = ...,
    ) -> tuple[Verifier, ...]:
        """Return the verifier tuple the harness should dispatch."""
        ...


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class RunBuildHarnessLoopStep:
    """Phase 4 ``run_build_harness_loop`` step (spec §5.5, T5.6).

    Builds the harness :class:`PlanExecLoopConfig`, spawns the
    long-lived sidecar, and invokes :func:`harness.run_plan_exec_loop`.
    The spec-mandated split between *seeded* (manual) and *mutable*
    (hydrogen, data) artifact-tree contents is enforced here: the
    workspace is created up front with the manual seeded, then the
    hydrogen tree and dataset are layered into ``run_dir/artifact/``
    *after* the seed manifest is captured.

    Attributes:
        id: Step id (``run_build_harness_loop``).
        phase: ``build``.
        inputs: :class:`StepInput` for ``start_sidecar`` /
            ``assemble_data`` / ``validate_hosting`` plus
            :class:`FileInput` references for ``hydrogen/package.json``
            and ``hydrogen/.env``.
        outputs: ``[runs/build/run.json]``.
        depends_on: ``[start_sidecar, assemble_data, validate_hosting]``.
        version: Bumped when the loop driver contract changes.
    """

    def __init__(
        self,
        *,
        loop_runner: LoopRunner | None = None,
        runtime_factory: RuntimeFactory | None = None,
        sidecar_factory: SidecarFactory | None = None,
        verifiers_factory: VerifiersFactory | None = None,
        install_runner: SubprocessRunner | None = None,
        iter_timeout_s: float = _DEFAULT_ITER_TIMEOUT_S,
        install_timeout_s: float = _INSTALL_TIMEOUT_S,
        force: bool = True,
    ) -> None:
        """Build the step with optional injection seams.

        Args:
            loop_runner: Callable invoked with the assembled
                :class:`PlanExecLoopConfig` and runtime. Defaults to
                :func:`harness.run_plan_exec_loop`.
            runtime_factory: Callable that builds the iteration-driving
                :class:`AgentRuntime`. Defaults to a thin wrapper around
                :func:`harness.get_runtime` keyed off
                :attr:`ShopGenConfig.runtime` / :attr:`ShopGenConfig.model`.
            sidecar_factory: Callable that yields the long-lived sidecar
                context. Defaults to :func:`sidecar_lifecycle`.
            verifiers_factory: Callable that builds the v0.1 verifier
                set bound to the live sidecar. Defaults to
                :func:`default_verifiers_factory`.
            install_runner: Subprocess runner used to spawn ``pnpm install``
                inside the artifact tree on first creation. Defaults to
                :func:`shop_gen.build.verifiers._subprocess.default_subprocess_runner`.
                Tests inject a stub.
            iter_timeout_s: Per-iteration wall-clock budget forwarded to
                the harness. Defaults to :data:`_DEFAULT_ITER_TIMEOUT_S`.
            install_timeout_s: Wall-clock budget for the per-run
                ``pnpm install``. Defaults to :data:`_INSTALL_TIMEOUT_S`.
            force: Forwarded to :func:`harness.run_plan_exec_loop` as
                ``force=...``. v0.1 always passes ``True`` because the
                step pre-creates the workspace itself (so the harness
                always enters via ``Workspace.open`` with no prior
                ``run.json``); the seam stays open for the redo flow
                landing under T5.7.
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            StepInput(step_id=_UPSTREAM_START_SIDECAR),
            StepInput(step_id=_UPSTREAM_ASSEMBLE_DATA),
            StepInput(step_id=_UPSTREAM_VALIDATE_HOSTING),
            FileInput(path=_HYDROGEN_SENTINEL),
            FileInput(path=_HYDROGEN_ENV),
        ]
        self.outputs: list[Path] = [_RUN_SUMMARY]
        self.depends_on: list[str] = [
            _UPSTREAM_START_SIDECAR,
            _UPSTREAM_ASSEMBLE_DATA,
            _UPSTREAM_VALIDATE_HOSTING,
        ]
        self.version: int = _STEP_VERSION

        self._loop_runner: LoopRunner = loop_runner or _default_loop_runner
        self._runtime_factory: RuntimeFactory = runtime_factory or _default_runtime_factory
        self._sidecar_factory: SidecarFactory = sidecar_factory or _default_sidecar_factory
        self._verifiers_factory: VerifiersFactory = verifiers_factory or default_verifiers_factory
        self._install_runner: SubprocessRunner = install_runner or default_subprocess_runner
        self._iter_timeout_s = iter_timeout_s
        self._install_timeout_s = install_timeout_s
        self._force = force

    def run(self, ctx: StepContext) -> None:
        """Drive the build harness loop end-to-end.

        The planner emits the canonical 8-task plan (spec §5.5.4); the
        mandatory ``visual_fix`` task is the lowest-priority bullet and
        the harness drives it inline like any other task — no
        post-loop fixup is required.

        Args:
            ctx: Execution context. ``ctx.runtime`` is unused — the
                harness drives its own iteration runtime selected by
                :class:`RuntimeFactory`. ``ctx.config.max_iters`` is
                forwarded to the harness as the executor budget.

        Raises:
            FileNotFoundError: ``hydrogen/``, ``manual/``, or ``data/``
                is missing under ``ctx.out_dir``.
            shop_gen.build.sidecar.SidecarLifecycleError: ``hydrogen/.env``
                is missing or malformed.
            shop_gen.data_validation.hosting_check.HostingValidationError:
                ``packages/shop_backend/dist/cli.js`` cannot be located.
            Exception: Any exception raised by the harness, runtime, or
                the loop runner propagates after the sidecar is torn
                down.
        """
        out_dir = ctx.out_dir
        manual_dir = out_dir / _MANUAL_DIR
        data_dir = out_dir / _DATA_DIR
        hydrogen_src = out_dir / _HYDROGEN_DIR
        run_dir = out_dir / _RUN_DIR
        env_path = out_dir / _HYDROGEN_ENV

        _require_dir(manual_dir, "manual_dir")
        _require_dir(hydrogen_src, "hydrogen tree")
        _require_dir(data_dir, "data dir")

        port = parse_port_from_env(env_path)
        cli_path = find_shop_backend_cli()
        argv: list[str] = ["node", str(cli_path), str(data_dir), str(port)]

        harness_config = self._build_loop_config(
            run_dir=run_dir,
            manual_dir=manual_dir,
            max_iters=ctx.config.max_iters,
            verifiers=(),  # filled in inside the sidecar context once the handle is live
        )

        # Pre-create the workspace ourselves so we can layer the
        # mutable hydrogen + data trees into ``run_dir/artifact/``
        # *after* the seed manifest is captured (spec §5.5).
        force = self._setup_run_dir(
            harness_config,
            hydrogen_src=hydrogen_src,
            data_dir=data_dir,
        )

        runtime = self._runtime_factory(ctx.config)

        with self._sidecar_factory(argv=argv, port=port) as sidecar:
            verifiers = self._verifiers_factory(
                out_dir=out_dir,
                sidecar=sidecar,
                judges=ctx.config.judges,
                visual_retry_budget=ctx.config.visual_retry_budget,
                visual_judge_pass_threshold=ctx.config.visual_judge_pass_threshold,
                visual_judge_max_concurrency=ctx.config.visual_judge_max_concurrency,
            )
            loop_config = harness_config.model_copy(update={"verifiers": verifiers})
            self._loop_runner(loop_config, runtime, force=force)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_loop_config(
        self,
        *,
        run_dir: Path,
        manual_dir: Path,
        max_iters: int,
        verifiers: tuple[Verifier, ...],
    ) -> PlanExecLoopConfig:
        """Assemble the :class:`PlanExecLoopConfig` for this step's invocation."""
        prompts = Prompts(
            planner=load_planner_prompt(),
            execute=load_execute_prompt(),
        )
        return PlanExecLoopConfig(
            run_dir=run_dir,
            prompts=prompts,
            agents_md=load_agents_md(),
            artifact_seed_dir=manual_dir,
            max_iters=max_iters,
            timeout=self._iter_timeout_s,
            verifiers=verifiers,
        )

    def _setup_run_dir(
        self,
        harness_config: PlanExecLoopConfig,
        *,
        hydrogen_src: Path,
        data_dir: Path,
    ) -> bool:
        """Materialise the workspace and inject the mutable subtrees.

        Two coherent outcomes — fast path or full reset:

        * **Fast path**: ``run_dir`` exists, is non-empty, and the
          persisted source fingerprint matches the current source. The
          existing artifact tree, ``plan.md``, ``iters/`` and
          ``run.json`` are left untouched and the harness resumes via
          :meth:`harness.workspace.Workspace.open` against them.
        * **Full reset**: ``run_dir`` is missing or empty (fresh
          workspace), or the stamp differs from the current source
          fingerprint (drift). On drift the entire ``run_dir`` is
          torn down with ``shutil.rmtree`` so plan / iters / artifact
          stay coherent, then a fresh :meth:`Workspace.create` seeds
          the manual; the mutable hydrogen + data trees are layered
          in *after* the seed manifest is captured, so seed-immutability
          checks ignore them.

        Drift is the right behaviour for any real source change
        (template edit, ``CloneTemplateStep.version`` bump,
        regenerated data) because the executor's prior plan markers
        (``plan.md`` task statuses, ``iters/<id>/`` records) implicitly
        assert "the artifact tree contains the work I described". Once
        the source changes that assertion no longer holds, so the
        cleanest recovery is to throw the prior loop away and re-plan.

        After a fresh-or-reset workspace is in place we run
        ``pnpm install --ignore-workspace --frozen-lockfile`` inside the
        artifact's hydrogen tree. The vendored template ships a
        normalised ``package.json`` + ``pnpm-lock.yaml`` but no
        ``node_modules/``; the install hydrates dependencies from
        pnpm's global content-addressable store. ``--ignore-workspace``
        is the load-bearing flag — without it pnpm walks up to the
        repo root, finds ``pnpm-workspace.yaml``, fails to register the
        artifact directory as a member, and refuses to resolve the
        template's dependencies.

        Returns:
            The ``force`` flag to pass to :func:`run_plan_exec_loop`. We
            always return ``True`` in v0.1: a freshly pre-created
            workspace has no ``run.json``, so the harness's resume
            refusal policy would otherwise reject the loop. The redo
            flow under T5.7 will refine this.

        Raises:
            RuntimeError: ``pnpm install`` exited with a non-zero
                status. The captured stdout/stderr (truncated) is
                included in the message.
            subprocess.TimeoutExpired: ``pnpm install`` exceeded
                ``self._install_timeout_s``. Propagated unchanged so
                the runner records the step ``FAILED``.
        """
        run_dir = harness_config.run_dir
        current_fp = _compute_source_fingerprint(hydrogen_src, data_dir)

        if run_dir.exists() and any(run_dir.iterdir()):
            if _read_source_stamp(run_dir / _ARTIFACT_DIRNAME) == current_fp:
                return self._force
            _log.info(
                "build artifact source-fingerprint drift detected — "
                "resetting %s",
                run_dir,
            )
            shutil.rmtree(run_dir)

        run_dir.mkdir(parents=True, exist_ok=True)
        workspace = Workspace.create(harness_config)
        artifact_dir = workspace.artifact_dir
        # ``Workspace.create`` writes an empty ``plan.md``; the harness
        # then re-enters this run via ``Workspace.open`` which validates
        # the plan structure. Seed a minimal ``## Tasks`` heading so
        # ``parse_plan`` accepts it; the planner iteration overwrites
        # the file with the real plan.
        workspace.plan_md.write_text(_EMPTY_PLAN_MD, encoding="utf-8")

        # ``out_dir/hydrogen/`` is a pure source tree by contract —
        # ``CloneTemplateStep`` is the only writer and explicitly
        # excludes / purges ``node_modules/``. Trust that invariant
        # here: a ``node_modules/`` showing up in ``hydrogen_src`` is a
        # clone_template bug, not something to silently work around.
        shutil.copytree(
            hydrogen_src,
            artifact_dir / _HYDROGEN_DIR.name,
            dirs_exist_ok=False,
        )
        shutil.copytree(
            data_dir,
            artifact_dir / _DATA_DIR.name,
            dirs_exist_ok=False,
        )
        self._install_artifact_deps(artifact_dir / _HYDROGEN_DIR.name)
        _write_source_stamp(artifact_dir, current_fp)
        return self._force

    def _install_artifact_deps(self, hydrogen_dir: Path) -> None:
        """Run ``pnpm install --ignore-workspace --frozen-lockfile`` in ``hydrogen_dir``.

        Idempotent on a populated ``node_modules/`` matching the
        lockfile: pnpm's own up-to-date check short-circuits the
        install. A non-zero exit raises :class:`RuntimeError` with
        truncated stdout/stderr embedded for debugging.
        """
        completed = self._install_runner(
            ("pnpm", "install", "--ignore-workspace", "--frozen-lockfile"),
            cwd=hydrogen_dir,
            timeout=self._install_timeout_s,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "pnpm install failed inside the artifact hydrogen tree "
                f"({hydrogen_dir}); returncode={completed.returncode}.\n"
                f"stdout:\n{truncate_stream(completed.stdout)}\n"
                f"stderr:\n{truncate_stream(completed.stderr)}",
            )


# --------------------------------------------------------------------------- #
# Source-fingerprint helpers
# --------------------------------------------------------------------------- #


def _compute_source_fingerprint(hydrogen_src: Path, data_dir: Path) -> str:
    """Hash the upstream source state into a deterministic stamp.

    The digest mixes three signals:

    1. :data:`shop_gen.build.env._CLONE_STEP_VERSION` so a version bump
       always invalidates the stamp, even when ``clone_template``
       wrote byte-identical content (the version is the canonical
       "upstream generation changed" signal per spec §5.7.1).
    2. Every file under ``hydrogen_src`` *except* ``node_modules/``
       (owned by the artifact-tree's ``pnpm install``, never present
       in source per ``CloneTemplateStep``'s contract) and ``.env``
       (its port is reallocated on every ``write_env_file`` run —
       incidental to the build, not a real source change).
    3. Every file under ``data_dir``.

    Files are visited in lexicographic order so the digest is stable
    across filesystems. Both trees are small (~100 files for hydrogen,
    a handful of JSON files for data); the cost is negligible compared
    to ``pnpm install``.

    Args:
        hydrogen_src: Source hydrogen directory (``<out_dir>/hydrogen/``).
        data_dir: Source data directory (``<out_dir>/data/``).

    Returns:
        Lowercase hex sha256 digest mixing the clone version + tree content.
    """
    digest = hashlib.sha256()
    digest.update(b"clone_template_version\x00")
    digest.update(str(_CLONE_STEP_VERSION).encode("ascii"))
    digest.update(b"\n")
    for label, root in (("hydrogen", hydrogen_src), ("data", data_dir)):
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "node_modules" in path.parts:
                continue
            if root is hydrogen_src and path.name == ".env":
                continue
            digest.update(label.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(b"\x00")
            digest.update(path.read_bytes())
            digest.update(b"\n")
    return digest.hexdigest()


def _read_source_stamp(artifact_dir: Path) -> str | None:
    """Return the previously persisted source fingerprint, or ``None``."""
    stamp = artifact_dir / _SOURCE_STAMP
    if not stamp.is_file():
        return None
    return stamp.read_text(encoding="utf-8").strip() or None


def _write_source_stamp(artifact_dir: Path, fingerprint: str) -> None:
    """Persist ``fingerprint`` to ``<artifact_dir>/.shop_gen/source_fingerprint``."""
    stamp = artifact_dir / _SOURCE_STAMP
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(fingerprint + "\n", encoding="utf-8")

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #


def _default_loop_runner(
    config: PlanExecLoopConfig,
    runtime: AgentRuntime,
    *,
    force: bool,
) -> PlanExecLoopResult:
    """Default :class:`LoopRunner` — straight pass-through to the harness."""
    return run_plan_exec_loop(config, runtime, force=force)


def _default_runtime_factory(config: ShopGenConfig) -> AgentRuntime:
    """Default :class:`RuntimeFactory` — :func:`harness.get_runtime`.

    Drops ``model=None`` from the kwargs so the runtime adapter sees no
    ``model`` keyword at all when the user opted out of pinning a model.
    """
    kwargs: dict[str, str] = {}
    if config.model is not None:
        kwargs["model"] = config.model
    return get_runtime(config.runtime, **kwargs)


def _default_sidecar_factory(
    *,
    argv: Sequence[str],
    port: int,
) -> AbstractContextManager[SidecarHandle]:
    """Default :class:`SidecarFactory` — :func:`sidecar_lifecycle`."""
    return sidecar_lifecycle(argv=argv, port=port)


_default_dev_server_factory: DevServerFactory = pnpm_dev_factory()
"""Production :class:`DevServerFactory` — :func:`pnpm_dev_factory`.

Boots the freshly built hydrogen tree via ``pnpm dev`` on a free TCP
port, polls ``/health``, and tears the subprocess down on exit. Tests
still inject a stub through the :func:`default_verifiers_factory`
``dev_server_factory`` seam; production callers get this default.
Replaces the v0.1 ``_unconfigured_dev_server_factory`` placeholder
(impl plan T6.1).
"""


def default_verifiers_factory(
    *,
    out_dir: Path,
    sidecar: SidecarHandle,
    judges: frozenset[str] = DEFAULT_JUDGES,
    dev_server_factory: DevServerFactory | None = None,
    visual_retry_budget: int = DEFAULT_VISUAL_RETRY_BUDGET,
    visual_judge_pass_threshold: float = DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD,
    visual_judge_max_concurrency: int = DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY,
) -> tuple[Verifier, ...]:
    """Build the v0.1 verifier set documented in spec §5.5.3 + §5.5.4.

    Every verifier is pluggable through its own constructor seam; this
    default uses the production wiring (real ``pnpm`` invocations, the
    live sidecar's introspection endpoint, the shipped allowlist).

    LLM-judge verifiers are gated by the ``judges`` set (spec §5.5,
    impl plan T3.2): only judges whose name appears in ``judges``
    are constructed. Rule verifiers are always present. The default
    is :data:`~shop_gen.config.DEFAULT_JUDGES` (every known judge).

    The ``visual_judge`` branch is additionally gated behind the
    :func:`~shop_gen.build.verifiers._skills.is_playwright_skill_available`
    probe (impl plan T1.5): when ``visual_judge`` is requested but the
    ``pi-playwright`` skill is missing the verifier is omitted from the
    tuple and a single warning is logged with the install hint.

    Args:
        out_dir: Run workspace. Used by ``nav_coverage`` to locate
            ``data/collections.json`` and by ``visual_judge`` to locate
            ``data/{collections,products,pages}.json``.
        sidecar: Live :class:`SidecarHandle`. Used by ``data_in_use`` to
            point at the introspection endpoint.
        judges: Set of LLM-judge verifier names to construct (spec
            §5.5). Names outside this set are omitted; rule verifiers
            are always included. Defaults to
            :data:`~shop_gen.config.DEFAULT_JUDGES`.
        dev_server_factory: :class:`DevServerFactory` that boots the
            hydrogen dev server for the visual-judge sub-iteration.
            Defaults to :data:`_default_dev_server_factory`
            (production ``pnpm dev`` runner; impl plan T6.1).
        visual_retry_budget: Per-task cap on consecutive ``visual_judge``
            FAILs before the verifier downgrades to ADVISORY (spec §5.4).
            ``0`` disables the budget. Forwarded to the verifier ctor.
        visual_judge_pass_threshold: Score floor for the §9.3 pass→fail
            coercion rule. Forwarded to the verifier ctor.
        visual_judge_max_concurrency: Page-bucket fan-out worker count
            (spec §5.2.1 step 5, §5.6). Forwarded to the verifier ctor;
            consumed by the M5 fan-out arm.

    Returns:
        Ordered verifier tuple suitable for
        :attr:`PlanExecLoopConfig.verifiers`. The order matches the
        spec table; harness dispatch is independent of order, so it is
        chosen for readability in ``feedback.md``.
    """
    factory: DevServerFactory = dev_server_factory or _default_dev_server_factory
    verifiers: list[Verifier] = [
        TscVerifier(),
        BuildVerifier(),
        DataInUseVerifier(
            introspect=_GraphqlIntrospector(base_url=sidecar.base_url),
        ),
        NavCoverageVerifier(data_dir=out_dir / _DATA_DIR),
        # `navigation_primitive_usage` registers as HARD-FAIL in M5 (impl plan T5.1):
        # the verifier blocks the iteration when `gen_navigation` outputs bypass the
        # navigation primitives, locking in the contract validated end-to-end by the post-M2
        # cassette (`test_build_loop_replay_post_build_artifact_imports_navigation_primitives`).
        # Was advisory in M4 (T4.2); promotion drops the `advisory=True` kwarg.
        NavigationPrimitiveUsageVerifier(),
        # `routes_200` boots a transient dev server and asserts every bucket
        # route returns HTTP 2xx (spec §5.3 / impl plan T4.1). Slotted before
        # the LLM judges so a broken hydrogen tree (e.g. SSR 500s) surfaces
        # as a cheap, route-by-route FAIL with actionable feedback rather
        # than burning the visual-judge agent's wall-clock budget rendering
        # error pages.
        Routes200Verifier(
            data_dir=out_dir / _DATA_DIR,
            dev_server_factory=factory,
        ),
        # NoBrandLeakVerifier(),  # temporarily disabled — broken; re-add import + line to revive.
    ]
    if "quality_judge" in judges:
        verifiers.append(QualityJudgeVerifier())
    if "visual_judge" in judges:
        if is_playwright_skill_available():
            verifiers.append(
                VisualJudgeVerifier(
                    data_dir=out_dir / _DATA_DIR,
                    dev_server_factory=factory,
                    retry_budget=visual_retry_budget,
                    pass_threshold=visual_judge_pass_threshold,
                    max_concurrency=visual_judge_max_concurrency,
                ),
            )
        else:
            _log.warning(
                "`visual_judge` skipped: pi-playwright skill not found. "
                "Install with `pnpm add -g pi-playwright` (or `npm i -g pi-playwright`) to enable.",
            )
    if "cross_task_consistency" in judges:
        verifiers.append(CrossTaskConsistencyVerifier())
    return tuple(verifiers)


# --------------------------------------------------------------------------- #
# Internals — verifier wiring
# --------------------------------------------------------------------------- #


_INTROSPECTION_QUERY: Final[str] = """\
{
  __schema {
    queryType { fields { name } }
    mutationType { fields { name } }
    subscriptionType { fields { name } }
  }
}
"""
"""Minimal introspection query — only the per-root-type field names the
:class:`DataInUseVerifier` diffs against. Avoids pulling the full type
graph that a stock ``IntrospectionQuery`` would return."""

_INTROSPECT_TIMEOUT_S: Final[float] = 5.0
"""Wall-clock budget for the introspection POST. The sidecar is loopback
and the schema fetch is small, so a tight bound is appropriate."""

_GRAPHQL_PATH: Final[str] = "/graphql"
"""Endpoint the ``shop_backend`` sidecar mounts via graphql-yoga
(see ``packages/shop_backend/src/server.ts``)."""

_OPERATION_ROOT_SLOTS: Final[tuple[tuple[str, str], ...]] = (
    ("queryType", "Query"),
    ("mutationType", "Mutation"),
    ("subscriptionType", "Subscription"),
)
"""Maps each ``__schema`` root slot to the canonical name the verifier
keys on. The schema's actual type names (e.g. ``QueryRoot``) are
discarded — the verifier addresses roots by operation kind, not by the
type label the server happens to use."""


class _GraphqlIntrospector:
    """Default :class:`Introspector` that POSTs the canonical query at the sidecar.

    The class shape (rather than a closure) keeps the production wiring
    pickle-friendly and trivial to swap with a stub in tests.
    """

    def __init__(self, *, base_url: str) -> None:
        """Bind the introspector to the live sidecar's storefront URL."""
        self._base_url = base_url

    def __call__(self) -> SchemaIntrospection:
        """Return the current schema's root-field index.

        Raises:
            RuntimeError: The sidecar replied with an HTTP error, a
                GraphQL ``errors`` payload, or an unexpectedly shaped
                response. :class:`DataInUseVerifier` converts this into
                a structured ``FAIL`` rather than propagating, so the
                build loop never deadlocks on a transient sidecar hiccup.
            httpx.HTTPError: The POST never reached the sidecar (e.g.
                connection refused). Same handling applies.
        """
        url = f"{self._base_url}{_GRAPHQL_PATH}"
        response = httpx.post(
            url,
            json={"query": _INTROSPECTION_QUERY},
            timeout=_INTROSPECT_TIMEOUT_S,
        )
        response.raise_for_status()
        payload = cast("dict[str, Any]", response.json())
        return _schema_from_introspection(payload)


def _schema_from_introspection(payload: dict[str, Any]) -> SchemaIntrospection:
    """Translate a GraphQL introspection response into :class:`SchemaIntrospection`.

    Args:
        payload: Parsed JSON body from ``POST /graphql``.

    Returns:
        :class:`SchemaIntrospection` with one entry per root type the
        server actually exposes. Roots returned as ``null`` (e.g. a
        schema without mutations) are omitted, matching
        :meth:`SchemaIntrospection.fields_for`'s empty-set fallback.

    Raises:
        RuntimeError: The payload carries a top-level ``errors`` array
            or does not match the introspection shape we expect.
    """
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"GraphQL introspection errors: {errors!r}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"introspection response missing `data`: {payload!r}")
    schema = cast("dict[str, Any]", data).get("__schema")
    if not isinstance(schema, dict):
        raise RuntimeError(f"introspection response missing `__schema`: {payload!r}")
    schema_dict = cast("dict[str, Any]", schema)
    root_fields: dict[str, frozenset[str]] = {}
    for slot, canonical in _OPERATION_ROOT_SLOTS:
        slot_value = schema_dict.get(slot)
        if slot_value is None:
            continue
        if not isinstance(slot_value, dict):
            raise RuntimeError(
                f"introspection `{slot}` is not an object: {slot_value!r}",
            )
        fields = cast("dict[str, Any]", slot_value).get("fields")
        if not isinstance(fields, list):
            raise RuntimeError(
                f"introspection `{slot}.fields` is not a list: {fields!r}",
            )
        names: set[str] = set()
        for entry in cast("list[Any]", fields):
            if not isinstance(entry, dict):
                raise RuntimeError(
                    f"introspection `{slot}.fields` entry is not an object: {entry!r}",
                )
            name = cast("dict[str, Any]", entry).get("name")
            if not isinstance(name, str):
                raise RuntimeError(
                    f"introspection `{slot}.fields[].name` is not a string: {name!r}",
                )
            names.add(name)
        root_fields[canonical] = frozenset(names)
    return SchemaIntrospection(root_fields=root_fields)


# --------------------------------------------------------------------------- #
# Internals — validation
# --------------------------------------------------------------------------- #


def _require_dir(path: Path, label: str) -> None:
    """Raise :class:`FileNotFoundError` when ``path`` is not a directory."""
    if not path.is_dir():
        raise FileNotFoundError(
            f"{label} not found at {path}; did the upstream Phase 4 step run?",
        )


__all__ = [
    "LoopRunner",
    "RunBuildHarnessLoopStep",
    "RuntimeFactory",
    "SidecarFactory",
    "VerifiersFactory",
    "default_verifiers_factory",
]
