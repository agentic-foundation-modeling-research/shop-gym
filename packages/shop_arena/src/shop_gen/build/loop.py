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
  (``tsc``, ``build``, ``routes_200``, ``data_in_use``, ``nav_coverage``,
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

import contextlib
import json
import shutil
from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Final, Protocol, cast, runtime_checkable

from harness import (
    AgentRuntime,
    PlanExecLoopConfig,
    PlanExecLoopResult,
    Prompts,
    Verifier,
    get_runtime,
    run_plan_exec_loop,
)
from harness.config import FinalStatus
from harness.workspace import Workspace
from shop_gen.build.consolidate import ensure_consolidate_task
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
    NoBrandLeakVerifier,
    QualityJudgeVerifier,
    Routes200Verifier,
    SchemaIntrospection,
    TscVerifier,
)
from shop_gen.config import ShopGenConfig
from shop_gen.data_validation.hosting_check import find_shop_backend_cli
from shop_gen.steps.base import FileInput, InputRef, StepContext, StepInput

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

_DEFAULT_ITER_TIMEOUT_S: Final[float] = 600.0
"""Default per-iteration wall-clock budget. Conservative for cold caches."""

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
    or the dev-server seam (``routes_200``) can be wired against the
    same sidecar the agent talks to.
    """

    def __call__(
        self,
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
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
        iter_timeout_s: float = _DEFAULT_ITER_TIMEOUT_S,
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
            iter_timeout_s: Per-iteration wall-clock budget forwarded to
                the harness. Defaults to :data:`_DEFAULT_ITER_TIMEOUT_S`.
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
        self._iter_timeout_s = iter_timeout_s
        self._force = force

    def run(self, ctx: StepContext) -> None:
        """Drive the build harness loop end-to-end.

        After the harness invocation returns, the spec §5.5.4 mandatory
        ``consolidate`` task contract is enforced via
        :func:`shop_gen.build.consolidate.ensure_consolidate_task`: if
        the planner omitted ``consolidate`` from ``plan.md`` the helper
        appends a canonical bullet and the harness is resumed so the
        executor picks the new PENDING task.

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

        plan_path = run_dir / "plan.md"
        with self._sidecar_factory(argv=argv, port=port) as sidecar:
            verifiers = self._verifiers_factory(out_dir=out_dir, sidecar=sidecar)
            loop_config = harness_config.model_copy(update={"verifiers": verifiers})
            result = self._loop_runner(loop_config, runtime, force=force)

            # Spec §5.5.4: enforce the mandatory ``consolidate`` task contract.
            # The fallback only fires when the planner produced a parseable plan
            # (``plan_iter_count > 0`` and ``final_status`` is not ``invalid_plan``);
            # otherwise the harness already failed and the orchestrator must not
            # silently fix the on-disk plan. When the helper appends a consolidate
            # bullet we resume the harness so the executor picks the new PENDING
            # task; the prior ``completed`` / ``budget_exhausted`` status is not in
            # the §5.5 refusal set so the resume call does not strictly need
            # ``force=True``, but we pass it for symmetry with the T5.7 redo flow.
            if (
                result.plan_iter_count > 0
                and result.final_status is not FinalStatus.INVALID_PLAN
                and plan_path.is_file()
                and ensure_consolidate_task(plan_path) is not None
            ):
                self._loop_runner(loop_config, runtime, force=True)

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

        On a fresh run (``run_dir`` missing or empty) we call
        :meth:`harness.workspace.Workspace.create` ourselves. This seeds
        the manual into ``run_dir/artifact/`` and captures the seed
        manifest *before* we add the mutable hydrogen + data trees, so
        seed-immutability checks ignore them.

        Returns:
            The ``force`` flag to pass to :func:`run_plan_exec_loop`. We
            always return ``True`` in v0.1: a freshly pre-created
            workspace has no ``run.json``, so the harness's resume
            refusal policy would otherwise reject the loop. The redo
            flow under T5.7 will refine this.
        """
        run_dir = harness_config.run_dir
        if not run_dir.exists() or not any(run_dir.iterdir()):
            run_dir.mkdir(parents=True, exist_ok=True)
            workspace = Workspace.create(harness_config)
            artifact_dir = workspace.artifact_dir
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
            # ``Workspace.create`` writes an empty ``plan.md``; the
            # harness then re-enters this run via ``Workspace.open``
            # which validates the plan structure. Seed a minimal
            # ``## Tasks`` heading so ``parse_plan`` accepts it; the
            # planner iteration overwrites the file with the real plan.
            workspace.plan_md.write_text(_EMPTY_PLAN_MD, encoding="utf-8")
        return self._force


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


def default_verifiers_factory(
    *,
    out_dir: Path,
    sidecar: SidecarHandle,
) -> tuple[Verifier, ...]:
    """Build the v0.1 verifier set documented in spec §5.5.3 + §5.5.4.

    The set always contains the eight verifiers listed in the spec
    table; every verifier is pluggable through its own constructor
    seam so this default uses the production wiring (real ``pnpm``
    invocations, the live sidecar's introspection endpoint, the
    shipped allowlist).

    Args:
        out_dir: Run workspace. Used by ``nav_coverage`` to locate
            ``data/collections.json``.
        sidecar: Live :class:`SidecarHandle`. Used by ``data_in_use`` to
            point at the introspection endpoint and by ``routes_200``
            (indirectly via the dev-server factory the caller may
            override).

    Returns:
        Ordered verifier tuple suitable for
        :attr:`PlanExecLoopConfig.verifiers`. The order matches the
        spec table; harness dispatch is independent of order, so it is
        chosen for readability in ``feedback.md``.
    """
    return (
        TscVerifier(),
        BuildVerifier(),
        Routes200Verifier(
            task_routes=_default_task_routes(out_dir / _DATA_DIR),
            dev_server_factory=_unconfigured_dev_server_factory,
        ),
        DataInUseVerifier(
            introspect=_GraphqlIntrospector(base_url=sidecar.base_url),
        ),
        NavCoverageVerifier(data_dir=out_dir / _DATA_DIR),
        NoBrandLeakVerifier(),
        QualityJudgeVerifier(),
        CrossTaskConsistencyVerifier(),
    )


# --------------------------------------------------------------------------- #
# Internals — verifier wiring
# --------------------------------------------------------------------------- #


_PRODUCT_HANDLE_FALLBACK: Final[str] = "placeholder"
_PAGE_HANDLE_FALLBACK: Final[str] = "about"


def _default_task_routes(data_dir: Path) -> dict[str, tuple[str, ...]]:
    """Derive the ``routes_200`` task → routes map from the published dataset.

    Spec §5.5.3 wires ``routes_200`` against ``gen_navigation``,
    ``gen_homepage``, ``gen_collections``, ``gen_product``, and
    ``gen_info_pages`` (plus ``consolidate``). The product / pages
    routes need a sample handle that exists in the dataset; the rest
    are static.
    """
    product_handle = _read_first_handle(
        data_dir / "products.json",
        fallback=_PRODUCT_HANDLE_FALLBACK,
    )
    page_handle = _read_first_handle(
        data_dir / "pages.json",
        fallback=_PAGE_HANDLE_FALLBACK,
    )
    return {
        "gen_navigation": ("/",),
        "gen_homepage": ("/",),
        "gen_collections": ("/collections",),
        "gen_product": (f"/products/{product_handle}",),
        "gen_info_pages": (f"/pages/{page_handle}",),
        "consolidate": ("/", "/collections"),
    }


def _read_first_handle(path: Path, *, fallback: str) -> str:
    """Return the ``handle`` field of the first record under ``path``.

    A missing or unreadable file falls back to ``fallback`` so the
    routes map never carries a `None`. The fallback only triggers when
    the dataset is genuinely incomplete (Phase 2 should have populated
    every file before Phase 4 runs).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback
    if not isinstance(raw, list) or not raw:
        return fallback
    records = cast("list[object]", raw)
    first = records[0]
    if isinstance(first, dict):
        handle = cast("dict[str, object]", first).get("handle")
        if isinstance(handle, str) and handle:
            return handle
    return fallback


@contextlib.contextmanager
def _unconfigured_dev_server_factory(
    hydrogen_dir: Path,
):  # pragma: no cover — production wiring lands alongside playwright_smoke (M6).
    """Placeholder dev-server factory that refuses to boot.

    Calling :class:`Routes200Verifier` against this factory raises a
    :class:`NotImplementedError`. The real `pnpm dev` driver lands with
    M6's playwright smoke; T5.6 ships the loop wiring with the verifier
    constructable so callers (and tests) can swap a working factory in.
    """
    del hydrogen_dir
    raise NotImplementedError(
        "default Routes200Verifier dev-server factory is unconfigured; "
        "inject a `dev_server_factory` via the verifiers_factory seam.",
    )
    yield ""  # pragma: no cover — unreachable; keeps the function a generator.


class _GraphqlIntrospector:
    """Default :class:`Introspector` that POSTs the canonical query at the sidecar.

    The class shape (rather than a closure) keeps the production wiring
    pickle-friendly and trivial to swap with a stub in tests.
    """

    def __init__(self, *, base_url: str) -> None:
        """Bind the introspector to the live sidecar's storefront URL."""
        self._base_url = base_url

    def __call__(self) -> SchemaIntrospection:  # pragma: no cover — production wiring.
        """Return the current schema's root-field index.

        The implementation lands alongside M6's playwright smoke so the
        loop driver (T5.6) and the verifier (T5.4) ship in lockstep.
        Tests inject a stub via the verifiers_factory seam.
        """
        raise NotImplementedError(
            f"default _GraphqlIntrospector is unconfigured (base_url={self._base_url!r}); "
            "inject an `introspect` callable via the verifiers_factory seam.",
        )


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
